"""verify: 下書きを資料と照らす。合格なら送る文(印を取り除いた最終の文)を返す。決定論・通信なし。
考え方はイキモノビヨリ ikimonobiyori/guide_verify.py・docs/guide-mode.md にそろえた(コードは import しない・写さない)。
検査のコード名・何を止めるか・直し方は docs/answer-checks.md。語の一覧と値は concierge/data/verify.yaml(仮置き)。

下書きの形:
- 種類 A の事実を含む文の終わりに根拠の印 [Y003] など(1 文にいくつでも)。決まった文は資料の文をそのまま写して [L1] など。
- 最後の行に「[おすすめ] Y003, Y005」(すすめた事実の id。なければ「[おすすめ] なし」)。送る文からは取り除く。"""
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from .common import NL, config, verify_rules

PH = ""           # 決まった文を写した部分の置き換え
MT = ""           # 山の名前の置き換え
DATE_RES = (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), re.compile(r"(\d{1,2})月(\d{1,2})日"),
            re.compile(r"(?<![\d.])(\d{1,2})/(\d{1,2})(?![\d/])"))
WD_RES = (re.compile(r"([月火水木金土日])曜日?"), re.compile(r"\(([月火水木金土日])\)"))
TIME_RE = re.compile(r"(?<![\d.])(\d{1,2}):(\d{2})(?!\d)")
URL_RE = re.compile(r"https?://\S+|www\.\S+")


def _norm(s):
    s = unicodedata.normalize("NFKC", s or "").replace("°C", "℃")
    return re.sub(r"(?<=\d),(?=\d{3})", "", s)


def _num_re(units):
    alts = "|".join(re.escape(u) for u in sorted(units, key=len, reverse=True))
    return re.compile(r"(約)?\s*([-−]?\d+(?:\.\d+)?)\s*(" + alts + r")?")


class Ctx:
    """資料から作った、照らすための索引。"""

    def __init__(self, brief):
        self.b = brief
        self.R = verify_rules()
        self.num_re = _num_re(self.R["numbers"]["units"])
        self.ids = {}
        for f in brief["facts"]:
            self.ids[f["id"]] = ("Y", f)
        for k in brief["cards"]:
            self.ids[k["id"]] = ("K", k)
        for g in brief["gaps"]:
            self.ids[g["id"]] = ("G", g)
        L = brief["lines"]
        self.lines = [x for x in (L["data_time"], L["coverage"], L["lead_time"], L["attribution"]) if x] + list(L["hazards"])
        for x in self.lines:
            self.ids[x["id"]] = ("L", x)
        self.target_days = [date.fromisoformat(d["date"]) for d in brief["when"]["days"]]
        self.target_wd = {d["weekday"] for d in brief["when"]["days"]}
        # 山の名前: 76 座の全部(資料の mountain_index)→ 置き換えの表(長い順)
        self.names = []
        for m in brief.get("mountain_index") or []:
            n = m["name"]
            forms = {n, n.split("(")[0]}
            inner = n[n.find("(") + 1:-1] if "(" in n and n.endswith(")") else ""
            if inner and re.search(r"(山|岳|峰|嶺|頭)$", inner):
                forms.add(inner)
            for x in forms:
                if x:
                    self.names.append((_norm(x), m["id"]))
        self.names.sort(key=lambda x: -len(x[0]))
        self.in_brief = {f["mountain_id"] for f in brief["facts"]}
        names_in_brief = set()
        for c in brief["candidates"]:
            names_in_brief.update(c["outside_top_names"])
        for g in brief["gaps"]:
            names_in_brief.update(g["say"])
        self.in_brief |= {mid for n, mid in self.names if n in {_norm(x) for x in names_in_brief}}
        self.question = _norm(brief.get("question") or "")
        self.q_mountains = {mid for n, mid in self.names if n in self.question}

    # -- 表記の解析 --
    def tokens(self, text):
        """→ {dates: {(月,日)}, wds: {曜}, times: {(時,分)}, nums: [(約, 値, 単位, 後ろの文字)], urls}。"""
        t = _norm(text)
        out = {"dates": set(), "wds": set(), "times": set(), "nums": [], "urls": URL_RE.findall(t)}
        t = URL_RE.sub(" ", t)
        for i, rx in enumerate(DATE_RES):
            for m in rx.finditer(t):
                g = m.groups()
                out["dates"].add((int(g[1]), int(g[2])) if i == 0 else (int(g[0]), int(g[1])))
            t = rx.sub(" ", t)
        if "土日" in t:
            out["wds"].update({"土", "日"})
            t = t.replace("土日", " ")
        for rx in WD_RES:
            out["wds"].update(rx.findall(t))
            t = rx.sub(" ", t)
        for m in TIME_RE.finditer(t):
            out["times"].add((int(m.group(1)), int(m.group(2))))
        t = TIME_RE.sub(" ", t)
        for m in self.num_re.finditer(t):
            try:
                v = Decimal(m.group(2).replace("−", "-"))
            except InvalidOperation:
                continue
            after = t[m.end():m.end() + 3]
            out["nums"].append((bool(m.group(1)), v, m.group(3), after))
        return out

    def allowed(self, marks):
        """印の事実の「書いてよい表記」から、書いてよい数・日付・曜日・時刻・山を集める。"""
        a = {"dates": set(), "wds": set(), "times": set(), "nums": set(), "values": set(), "mountains": set(), "hazards": set()}
        texts = []
        for mid in marks:
            kind, x = self.ids[mid]
            if kind == "Y":
                texts += x["say"]
                a["mountains"].add(x["mountain_id"])
                a["hazards"].update((h["label"], h["level"]) for h in x["hazards"])
            elif kind == "K":
                texts += x["say"] + [x["text"]]
                a["mountains"].update(x["mountains"])
            elif kind == "G":
                texts += x["say"] + [x["text"]]
            else:
                texts.append(x["text"])
        if not any(self.ids[m][0] == "Y" for m in marks):
            for d in self.target_days:
                a["dates"].add((d.month, d.day))
            a["wds"] |= self.target_wd
        for s in texts:
            tk = self.tokens(s)
            a["dates"] |= tk["dates"]
            a["wds"] |= tk["wds"]
            a["times"] |= tk["times"]
            for ap, v, u, _ in tk["nums"]:
                a["nums"].add((ap, v, u))
                a["values"].add(v)
            for n, mid in self.names:
                if n in _norm(s):
                    a["mountains"].add(mid)
        return a

    def mask_names(self, t):
        """山の名前を置き換える。→ (置き換えた文, 出てきた山の ID の集合)。"""
        found = set()
        for n, mid in self.names:
            if n in t:
                found.add(mid)
                t = t.replace(n, MT)
        return t, found


def split_draft(text, R):
    """→ (本文の行, おすすめの id のリスト or None)。"""
    body, picks = [], None
    head = R["draft"]["picks_heading"]
    for line in (text or "").replace("\r\n", NL).split(NL):
        s = line.strip()
        if s.startswith(head):
            rest = s[len(head):].strip()
            picks = [] if rest in ("", "なし", "(なし)") else [x for x in re.split(r"[\s,、，]+", rest) if x]
            continue
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    return body, picks


def sentences(body_text, mre):
    """本文 → [{line, text(印つき), clean(印なし), ids}]。行の頭の印は前の文のもの。"""
    out = []
    for ln, line in enumerate(body_text.split(NL), 1):
        if not line.strip():
            continue
        segs = re.findall(r"[^。！？!?]+[。！？!?]?", line)
        for s in segs:
            m = re.match(r"^\s*((?:\[[YLKG]\d{1,3}\]\s*)+)(.*)$", s)
            if m and out:
                out[-1]["text"] += m.group(1).strip()
                out[-1]["ids"] = mre.findall(out[-1]["text"])
                s = m.group(2)
            if not s.strip():
                continue
            ids = mre.findall(s)
            clean = re.sub(r"\s*" + mre.pattern, "", s).strip()
            clean = re.sub(r"^(?:[-*・#>\s]+|\d{1,2}[.)．]\s+|[①-⑨]\s*)+", "", clean).replace("**", "").strip()
            if clean:
                out.append({"line": ln, "text": s.strip(), "clean": clean, "ids": ids})
    return out


def _err(code, s, detail, fix):
    return {"code": code, "line": (s or {}).get("line", 0), "sentence": (s or {}).get("clean", "")[:120], "detail": detail, "fix": fix}


def _has_any(t, words):
    return [w for w in words if w in t]


def check(draft, brief):
    """→ {ok, errors, final, picks}。"""
    X = Ctx(brief)
    R = X.R
    W = R["words"]
    mre = re.compile(R["draft"]["marker_re"])
    errs = []
    body_lines, picks = split_draft(draft, R)
    body = NL.join(body_lines)
    # 決まった文: そのまま写してあるか(印つき)。写した部分は置き換えてから文に分ける
    present = set()
    masked = body
    for x in X.lines:
        if x["text"] in masked:
            present.add(x["id"])
            masked = masked.replace(x["text"], PH + "。")
    for mid in set(mre.findall(body)):
        if mid in X.ids and X.ids[mid][0] == "L" and mid not in present:
            errs.append(_err("line_altered", None, f"[{mid}] の決まった文が書き換えてある", f"資料の [{mid}] の文を一字一句そのまま写す"))
    sents = sentences(masked, mre)
    exempt_re = re.compile("|".join(re.escape(w) for w in sorted(W["safety_exempt"], key=len, reverse=True)))
    lodging_ok = set(W["lodging_ok"])
    for s in sents:
        clean = s["clean"].replace(PH, "")
        if not clean.strip("。 "):
            continue
        ids = s["ids"]
        bad = [i for i in ids if i not in X.ids]
        if bad:
            errs.append(_err("unknown_mark", s, f"資料にない印 {', '.join(bad)}", "資料にある事実の印だけを付ける"))
            ids = [i for i in ids if i in X.ids]
        t = _norm(clean)
        tm, mentioned = X.mask_names(t)
        tk = X.tokens(tm)
        exempt = bool(exempt_re.search(t))
        kinds = {X.ids[i][0] for i in ids}
        # 76 座にない山の名前(形で見る。質問に書かれた名前は通す)
        for m in re.finditer(W["mountain_re"], tm):
            w = m.group(0)
            if any(w.endswith(c) for c in W["mountain_common"]) or w in X.question:
                continue
            errs.append(_err("unknown_mountain", s, f"資料にない山の名前「{w}」", "資料にある山だけを書く(76 座にない山は「足りないもの」を使う)"))
        if ids:
            a = X.allowed(ids)
            a["mountains"] |= X.q_mountains          # 質問に書かれた山は、名前を出してよい(数字などは印の事実と照らす)
            for mid in sorted(mentioned - a["mountains"]):
                code = "mountain_unmarked" if mid in X.in_brief else "mountain_not_in_brief"
                errs.append(_err(code, s, f"印の事実にない山({mid})を書いている",
                                 "その山の事実の印も付ける(比べる文はそれぞれの印が要る)" if code == "mountain_unmarked" else "資料にない山を書かない"))
            for d in sorted(tk["dates"] - a["dates"]):
                errs.append(_err("date_mismatch", s, f"日付 {d[0]}月{d[1]}日 が印の事実と合わない", "印の事実の日付を書く"))
            for w in sorted(tk["wds"] - a["wds"]):
                errs.append(_err("date_mismatch", s, f"曜日「{w}」が印の事実と合わない", "印の事実の曜日を書く"))
            for tm_ in sorted(tk["times"] - a["times"]):
                errs.append(_err("time_mismatch", s, f"時刻 {tm_[0]}:{tm_[1]:02d} が資料にない", "資料にある時刻だけを書く"))
            for ap, v, u, after in tk["nums"]:
                if u is None and any(after.startswith(c) for c in R["numbers"]["counters"]):
                    continue
                ok = (ap, v, u) in a["nums"] if u else v in a["values"]
                if not ok:
                    errs.append(_err("number_mismatch", s, f"数「{'約' if ap else ''}{v}{u or ''}」が印の事実の書いてよい表記にない",
                                     "事実の「書いてよい表記」をそのまま使う(自分で丸めない)"))
            for kind in W["hazard_kinds"]:
                for lv in W["hazard_levels"]:
                    if re.search(re.escape(kind) + r"\s*[のが:は]?\s*" + re.escape(lv), tm) and (kind, lv) not in a["hazards"]:
                        if not (lv == "警戒" and (kind, "警戒以上") in a["hazards"]):
                            errs.append(_err("hazard_mismatch", s, f"危険信号「{kind}{lv}」が印の事実と合わない", "印の事実の危険信号の語を書く"))
            if tk["urls"]:
                errs.append(_err("url_not_in_brief", s, "URL を書いている", "URL を書かない"))
        else:
            if tk["dates"] or (tk["wds"] - X.target_wd):
                errs.append(_err("date_unmarked", s, "印のない文に日付・対象の日でない曜日", "日付は事実の印を付けて書く(印なしで書けるのは今日・明日・今週末・来週末・対象の日の曜日だけ)"))
            if tk["times"]:
                errs.append(_err("time_unmarked", s, "印のない文に時刻", "時刻は事実の印を付けて書く"))
            nums = [(ap, v, u) for ap, v, u, after in tk["nums"] if u]
            if nums:
                errs.append(_err("number_unmarked", s, "印のない文に数字と単位(" + "・".join(f"{v}{u}" for _, v, u in nums[:3]) + ")",
                                 "数字は事実の印を付けて、書いてよい表記で書く"))
            if tk["urls"]:
                errs.append(_err("url_unmarked", s, "印のない文に URL", "URL を書かない"))
            t_w = tm
            for w in W["weather_ok"] + W["safety"]:       # 安全の語(積雪・雪山など)は種類 C の検査で見る
                t_w = t_w.replace(w, " ")
            hits = _has_any(t_w, W["weather"])
            if hits:
                errs.append(_err("weather_unmarked", s, f"印のない文に天気の語「{'・'.join(hits[:3])}」",
                                 "天気・予報の話は事実の印を付けて書く(一般的な話なら天気の語を使わない)"))
            hz = [k for k in W["hazard_kinds"] if k in tm and k not in hits]
            if hz:
                errs.append(_err("hazard_unmarked", s, f"印のない文に危険信号の語「{'・'.join(hz)}」", "危険信号は事実の印を付けて書く"))
            for mid in sorted(mentioned - X.in_brief):
                if not any(n in X.question for n, m_ in X.names if m_ == mid):
                    errs.append(_err("mountain_not_in_brief", s, f"資料にない山({mid})を書いている", "資料にある山だけを書く"))
        # 種類 C(山の安全): 危険信号の事実・知識カード・足りないものの印、または「判断できません」の形
        sc = _has_any(exempt_re.sub(" ", t), W["safety"])
        if sc and not exempt:
            basis = "G" in kinds or "K" in kinds or any(X.ids[i][0] == "Y" and X.ids[i][1]["hazards"] for i in ids)
            if not basis:
                errs.append(_err("safety_without_basis", s, f"山の安全に関わる語「{'・'.join(sc[:3])}」に裏づけがない",
                                 "資料に無いなら「この予報からは判断できません」の形で書き、足りないものの印 [G…] を付ける"))
        # おすすめの語と、宣言したおすすめ
        if picks is not None and _has_any(t, W["recommend"]):
            ys = [i for i in ids if X.ids[i][0] == "Y"]
            if ys and not set(ys) & set(picks):
                errs.append(_err("pick_undeclared", s, f"すすめている山({', '.join(ys)})が [おすすめ] にない", "[おすすめ] の行にその事実の id を書く"))
        # ビヨリをまたいで点を比べる
        if re.search(r"\d\s*点|点数", t) and _has_any(t, W["other_biyori"]):
            errs.append(_err("score_across_biyori", s, "山の点とほかのビヨリの話を 1 文で比べている", "ビヨリ間で点数を比べない"))
        for m in re.finditer(W["lodging_re"], tm):
            if m.group(0) not in lodging_ok:
                errs.append(_err("lodging_name", s, f"宿・山小屋の名前らしい語「{m.group(0)}」", "宿・山小屋の名前を書かない(「泊まりにすると」まで)"))
    # 全体
    L = brief["lines"]
    for key in ("data_time", "coverage", "attribution"):
        if L[key] and L[key]["id"] not in present:
            errs.append(_err("line_missing", None, f"決まった文 {key}([{L[key]['id']}])がない", f"[{L[key]['id']}] の文をそのまま写す"))
    plan_main = {p["main"]["fact"] for p in brief["plans"]}
    if picks is None:
        errs.append(_err("picks_missing", None, "最後の行の [おすすめ] がない", "最後の行に「[おすすめ] Y…」(なければ「[おすすめ] なし」)を書く"))
        picks_ = []
    else:
        picks_ = picks
    for pid in picks_:
        x = X.ids.get(pid)
        if not x or x[0] != "Y":
            errs.append(_err("pick_unknown", None, f"[おすすめ] の {pid} が山の事実にない", "山の事実の id を書く"))
            continue
        f = x[1]
        if not f["main_ok"]:
            errs.append(_err("pick_not_allowed", None, f"{f['name']}({f['label']})は主役にできない山", "主役にできる山だけをすすめる(見送りとして書く)"))
            continue
        if pid not in plan_main:
            errs.append(_err("pick_not_in_plans", None, f"{pid} が組み合わせの案にない", "資料の組み合わせにある主役だけをすすめる"))
        for h in L["hazards"]:
            if h["fact"] == pid and h["id"] not in present:
                errs.append(_err("hazard_line_missing", None, f"{f['name']}({f['label']})の危険信号の文([{h['id']}])がない",
                                 f"[{h['id']}] の文をそのまま写す"))
        if not f["reliable"] and not (L["lead_time"] and L["lead_time"]["id"] in present):
            errs.append(_err("lead_time_missing", None, f"{f['label']}は信用してよい範囲の外なのに、先の予報である旨の文がない",
                             f"[{(L['lead_time'] or {}).get('id', 'L…')}] の文をそのまま写す"))
    final = strip_marks(body, mre)
    plain = final
    for x in X.lines:
        plain = plain.replace(x["text"], " ")
    plain_n = exempt_re.sub(" ", _norm(plain))
    for line in plain_n.split(NL):
        for rx in W["internal"]:
            m = re.search(rx, line)
            if m:
                errs.append(_err("internal_word", {"line": 0, "clean": line}, f"内部の言葉「{m.group(0)}」", "利用者の言葉に言い換える"))
                break
        if re.search(W["english_re"], line):
            errs.append(_err("english_note", {"line": 0, "clean": line}, "英語の文・メモ", "英語のメモを書かない"))
    for s in sentences(plain, mre):
        for rx in W["question"]:
            if re.search(rx, s["clean"]):
                errs.append(_err("question_in_answer", s, "読む人への問いかけ", "質問をしない(答えだけを書く)"))
                break
        for rx in W["offer"]:
            if re.search(rx, s["clean"]):
                errs.append(_err("offer_in_answer", s, "できないことの提案", "「〜しましょうか」と提案しない"))
                break
    mx = brief["limits"]["max_chars"]
    if len(final) > mx:
        errs.append(_err("too_long", None, f"{len(final)} 字({mx} 字まで)", "短くする"))
    return {"ok": not errs, "errors": errs, "final": final, "picks": picks_, "checked": len(sents),
            "marked": sum(1 for s in sents if s["ids"])}


def strip_marks(body, mre):
    out = []
    for line in body.split(NL):
        line = re.sub(r"\s*" + mre.pattern, "", line).rstrip()
        out.append(line)
    text = NL.join(out).strip(NL)
    return re.sub(r"\n{3,}", "\n\n", text) + NL


def report(res):
    out = [f"{res['status']}(照らした文 {res['checked']}・印のある文 {res['marked']}・{res['attempt']} 回目)"]
    for e in res["errors"]:
        where = f"{e['line']}行目 " if e.get("line") else ""
        out.append(f"NG [{e['code']}] {where}{e['detail']}" + (f"\n   文: {e['sentence']}" if e.get("sentence") else "") + f"\n   直し方: {e['fix']}")
    if res["status"] == "FAIL":
        out.append(f"書き直しはあと {res['left']} 回です。直して同じコマンドをもう一度実行します。")
    return NL.join(out) + NL


def max_rewrites():
    return int(config()["answer"]["max_rewrites"])


def run(draft_text, bid, base, now):
    """→ {status: PASS / FAIL / FALLBACK, text, errors, attempt, left}。回数は置き場の briefs/<id>.verify.json で数える。"""
    import json
    from pathlib import Path

    from . import brief as B
    from . import fallback as F
    from .common import dump_json, iso, read_json, write_text
    b = B.load(bid, base)
    if b is None:
        return {"status": "NO_BRIEF", "text": None, "errors": [], "attempt": 0, "left": 0, "checked": 0, "marked": 0}
    st_path = B.brief_dir(base) / f"{bid}.verify.json"
    st = read_json(st_path) or {"attempts": 0, "history": []}
    st["attempts"] += 1
    r = check(draft_text, b)
    rewrites = st["attempts"] - 1
    mx = max_rewrites()
    if r["ok"]:
        status, text = "PASS", r["final"]
    elif rewrites >= mx:
        fb = check(F.draft(b), b)
        status, text = "FALLBACK", fb["final"]
    else:
        status, text = "FAIL", None
    st["history"].append({"attempt": st["attempts"], "status": status, "errors": sorted({e["code"] for e in r["errors"]})})
    write_text(st_path, dump_json(st))
    if text:
        write_text(B.brief_dir(base) / f"{bid}.final.txt", text)
    row = {"brief": bid, "at": iso(now), "result": {"PASS": "合格", "FAIL": "不合格", "FALLBACK": "控え"}[status],
           "rewrites": rewrites, "failed": sorted({e["code"] for e in r["errors"]})}
    p = Path(base) / "logs" / "answers.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + NL)
    return {"status": status, "text": text, "errors": r["errors"], "attempt": st["attempts"], "left": max(0, mx - rewrites),
            "checked": r["checked"], "marked": r["marked"]}
