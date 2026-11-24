"""Claude Code の Stop フック: 資料(concierge brief)を使った答えを、verify を通さずに・verify の文と違う文で送るのを止める。
通信しない・決定的。決まりと切り方は docs/stop-hook.md、語と値は concierge/data/stop_hook.yaml。
考え方はイキモノビヨリ ikimonobiyori/stop_hook.py・docs/guide-mode.md 3 章にそろえた(import しない・写さない)。

止めるとき(この回に concierge brief を実行したときだけ見る):
- 最後の brief のあとに concierge verify … --brief を実行していない。
- 最後のメッセージが、verify の出した文(合格した最終の文か控えの文)と一致しない(前後の空白と改行の形の違いは見ない)。
- 予報が古いのに「おすすめ」と言い切っている・生の雲量が 0 % の山に雲量の数字などを書いている。
止めないとき: brief を使っていない回・開発の作業の回(利用者の文の語、git や unittest、リポジトリの中のファイルの書き込み)・
同じ回で上限の回数だけ止めたあと・切ってあるとき・入力や記録が読めないとき・フックの中のエラー。**迷う場合は通す。**"""
import hashlib
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import yaml

from collect.common import ROOT

from .common import DATA, NL, data_dir, read_json, write_text
from .verify import LAST_ANSWER, Ctx, cloud_errors, sentences, stale_assertions

BRIEF_ID = re.compile(r"\bb\d{8}-\d{6}-[0-9a-f]{8}\b")


@lru_cache(maxsize=None)
def cfg():
    return yaml.safe_load((DATA / "stop_hook.yaml").read_text(encoding="utf-8"))


# ---- 会話の記録(JSONL)から、この回を取り出す ----
def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return NL.join(str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _result(block):
    c = block.get("content")
    if isinstance(c, list):
        return NL.join(str(x.get("text") or "") for x in c if isinstance(x, dict))
    return c if isinstance(c, str) else ""


def _starts_a_turn(e, c):
    """利用者の文か(道具の結果・メタの行・サブエージェントの行・このフックの理由は除く)。
    スラッシュコマンドと裏の作業の知らせも回の区切りにする(前の回の brief を次の回に数えないため。迷う場合は通す側)。"""
    if e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain"):
        return False
    content = (e.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    t = _text(content).strip()
    return bool(t) and not any(t.startswith(p) for p in c["not_prompt_prefixes"]) and c["reason_marker"] not in t


def read_turn(lines, c=None):
    """→ {prompt, key, calls: [{name, input, result}]} または None(利用者の文が見つからない)。"""
    c = c or cfg()
    rows = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            rows.append(e)
    start = next((i for i in range(len(rows) - 1, -1, -1) if _starts_a_turn(rows[i], c)), None)
    if start is None:
        return None
    prompt = _text(rows[start]["message"]["content"]).strip()
    key = str(rows[start].get("uuid") or hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16])
    calls, by_id = [], {}
    for e in rows[start + 1:]:
        content = (e.get("message") or {}).get("content")
        if e.get("isSidechain") or not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if e.get("type") == "assistant" and b.get("type") == "tool_use":
                call = {"name": b.get("name") or "", "input": b.get("input") if isinstance(b.get("input"), dict) else {}, "result": ""}
                calls.append(call)
                by_id[b.get("id")] = call
            elif e.get("type") == "user" and b.get("type") == "tool_result" and b.get("tool_use_id") in by_id:
                by_id[b["tool_use_id"]]["result"] = _result(b)
    return {"prompt": prompt, "key": key, "calls": calls}


# ---- 判定 ----
def _command(call, c):
    return str(call["input"].get("command") or "") if call["name"] in c["shell_tools"] else ""


def _runs(calls, sub, c):
    """concierge の sub(brief・verify)の実行 → [(呼び出しの番号, コマンドの中の位置)]。"""
    rx = re.compile(c["command_head"] + sub + r"\b")
    out = []
    for i, k in enumerate(calls):
        cmd = _command(k, c)
        for m in rx.finditer(cmd):
            if sub == "brief" and any(w in k["result"] for w in c["brief_failed"]):
                continue
            if sub == "verify" and "--brief" not in cmd[m.end():]:
                continue
            out.append((i, m.start()))
    return out


def _in_repo(path):
    try:
        p = Path(str(path)).resolve()
    except (OSError, ValueError):
        return False
    return p == ROOT or ROOT in p.parents


def exempt(turn, c=None):
    """検査しない回なら理由の語、検査する回なら None。"""
    c = c or cfg()
    if any(w in turn["prompt"] for w in c["skip_words"]):
        return "skip_word"
    for k in turn["calls"]:
        if any(re.search(p, _command(k, c)) for p in c["dev_commands"]):
            return "dev_command"
        if k["name"] in c["edit_tools"] and _in_repo(k["input"].get("file_path") or k["input"].get("notebook_path") or ""):
            return "dev_edit"
    return None


def _norm(s):
    return (s or "").replace("\r\n", NL).strip()


def _brief_ids(calls, c):
    ids = []
    for k in calls:
        if _command(k, c) and re.search(c["command_head"] + r"(?:brief|verify)\b", _command(k, c)):
            ids += BRIEF_ID.findall(_command(k, c)) + BRIEF_ID.findall(k["result"])
    return list(dict.fromkeys(ids))


def accepted_texts(turn, base, c=None):
    """送ってよい文: verify が出した最後の文と、この回の資料ごとに verify が出した文。"""
    c = c or cfg()
    ids = _brief_ids(turn["calls"], c)
    out = []
    last = read_json(Path(base) / LAST_ANSWER) or {}
    if last.get("text") and (not ids or last.get("brief") in ids):
        out.append(last["text"])
    for bid in ids:
        p = Path(base) / "briefs" / f"{bid}.final.txt"
        if p.is_file():
            out.append(p.read_text(encoding="utf-8"))
    return [t for t in dict.fromkeys(_norm(x) for x in out) if t]


def matches(message, texts):
    """メッセージが送ってよい文と一致するか(1 回に 2 問以上答えたときは、送ってよい文だけを並べた形も通す)。"""
    m = _norm(message)
    if m in texts:
        return True
    rest = m
    for t in sorted(texts, key=len, reverse=True):
        rest = rest.replace(t, "")
    return bool(texts) and rest != m and not rest.strip()


def decide(message, turn, base, c=None):
    """→ {block, why}。why は no_verify・mismatch(止める)、ほか(通す)。"""
    c = c or cfg()
    if not _norm(message):
        return {"block": False, "why": "no_message"}
    briefs = _runs(turn["calls"], "brief", c)
    if not briefs:
        return {"block": False, "why": "no_brief"}
    why = exempt(turn, c)
    if why:
        return {"block": False, "why": why}
    if not any(v > briefs[-1] for v in _runs(turn["calls"], "verify", c)):
        return {"block": True, "why": "no_verify"}
    if not matches(message, accepted_texts(turn, base, c)):
        return {"block": True, "why": "mismatch"}
    if _stale_assertion(message, turn, base, c):
        return {"block": True, "why": "stale"}
    if _cloud_violation(message, turn, base, c):
        return {"block": True, "why": "cloud"}
    return {"block": False, "why": "ok"}


def _stale_assertion(message, turn, base, c):
    """この回の資料の予報が古いのに、「おすすめします」と言い切った文か(verify の検査と同じ決まり。資料が読めなければ見ない)。"""
    for bid in _brief_ids(turn["calls"], c):
        doc = read_json(Path(base) / "briefs" / f"{bid}.json")
        if isinstance(doc, dict) and isinstance(doc.get("shelf"), dict) and doc["shelf"].get("stale") and stale_assertions(message):
            return True
    return False


def _cloud_violation(message, turn, base, c):
    """生の雲量が 0 % の山(資料の cloud_clear)に、雲量の数字・「快晴」などの言い切りを書いた文か(verify の検査と同じ決まり。
    どの山のことか決められない文と、資料が読めないときは見ない)。"""
    docs = [read_json(Path(base) / "briefs" / f"{bid}.json") for bid in _brief_ids(turn["calls"], c)]
    docs = [d for d in docs if isinstance(d, dict) and d.get("facts")]
    facts = [f for d in docs for f in d["facts"] if isinstance(f, dict)]      # 1 回に資料が 2 つ以上あれば、全部の事実で見る
    if not any(f.get("cloud_clear") for f in facts):
        return False
    try:
        X = Ctx(docs[-1])
        hits = cloud_errors(X, sentences(message, re.compile(X.R["draft"]["marker_re"])), lambda s: facts, carry=True)
    except (KeyError, TypeError, ValueError):
        return False
    return any(code in ("cloud_number", "cloud_assertion") for _, code, _ in hits)


# ---- 止めた回数(同じ回で上限まで) ----
def _count(base, key, c, add=False):
    p = Path(base) / c["state_file"]
    st = read_json(p)
    st = st if isinstance(st, dict) else {}
    n = st.get(key, 0)
    n = n if isinstance(n, int) else 0
    if add:
        st.pop(key, None)
        st[key] = n + 1
        write_text(p, json.dumps(dict(list(st.items())[-c["state_keep"]:]), ensure_ascii=False))
    return n


def run(payload, env=None):
    """フックの入力 → 止める理由の文(str)か None(通す)。"""
    env = os.environ if env is None else env
    c = cfg()
    if str(env.get(c["env_switch"], "")).strip().lower() == "off":
        return None
    try:
        lines = Path(payload["transcript_path"]).read_text(encoding="utf-8", errors="replace").split(NL)
    except (KeyError, OSError, TypeError):
        return None
    turn = read_turn(lines, c)
    if turn is None:
        return None
    base = data_dir(env)
    d = decide(payload.get("last_assistant_message"), turn, base, c)
    if not d["block"]:
        return None
    key = f"{payload.get('session_id') or ''}:{turn['key']}"
    if _count(base, key, c) >= c["max_blocks_per_turn"]:
        return None
    _count(base, key, c, add=True)
    return f"{c['reason_marker']} {c['reasons'][d['why']]}"


def to_output(reason, c=None):
    if (c or cfg())["output"] == "block":
        return {"decision": "block", "reason": reason}
    return {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}


def main(stdin=None, stdout=None):
    """フックの入口。どんな失敗でも終了コード 0 で通す。"""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        raw = stdin.buffer.read().decode("utf-8") if hasattr(stdin, "buffer") else stdin.read()
        payload = json.loads(raw or "{}")
        reason = run(payload) if isinstance(payload, dict) else None
        if reason:
            stdout.write(json.dumps(to_output(reason), ensure_ascii=False))
            stdout.flush()
    except Exception:                     # 失敗したら通す(応答を止めない)
        return 0
    return 0
