"""1回の取得(collect ジョブの中身)。成果物のフォルダ(artifact)を作る。棚(data ブランチ)には書かない(それは publish)。

成果物の形(out_dir):
  run.json                      この回の結果(スキーマ biyori-collect-run/1)。publish が manifest を作る材料
  yamabiyori/explore.json       成功したときだけ
  yamabiyori/mountains.json     成功したときだけ
  proposals/yamabiyori.json     成功したときだけ
  logs/requests.json            通信の集計(ホスト別・ステータス別・失敗の種類(例外の名前)別の回数だけ)
  raw/                          フックの記録(JSONL)と標準出力の末尾(ヤマビヨリは回ごと: yamabiyori-<回>-*)。artifact にだけ残し、棚には載せない

ビヨリの失敗(終了コード≠0・429・フックの中止・出力の形が違う)は、そのビヨリを status≠ok にするだけで、ほかのビヨリは続ける。
ヤマビヨリが対象の山を全部は取れなかった回(explore.json の fetched < pool_size)は status: incomplete(ok にしない)。
"""
import re
import shutil
import sys
import time
from pathlib import Path

from . import meta as meta_mod
from . import yamabiyori as yama
from .common import allow_hosts, config, iso, now_jst, read_json, schema_errors, write_json
from .runner import read_request_log, run_hooked, summarize

AGENTS = ("yamabiyori", "hoshibiyori")
RUN_SCHEMA = "biyori-collect-run/1"
# 棚に載せてよいヤマビヨリの ref。定期実行は常にこれ。手動実行で別の ref(試しのブランチ・commit)を使った回は棚に載せない
MAIN_REF = "main"
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


def slot_of(t):
    """日本時間の午前 = morning、午後 = evening。"""
    return "morning" if t.astimezone(t.tzinfo).hour < 12 else "evening"


def _fail(reason, **kw):
    return dict({"status": "failed", "reason": reason}, **kw)


def _attempt_failure(res, native_problems=None, has_output=True):
    """1 回の実行の結果 → (状態, 理由, 詳しく) または None(成功)。"""
    if res.rate_limited:
        return "rate_limited", "rate_limited", None
    if res.timed_out:
        return "failed", "timeout", None
    if res.blocked_host:
        return "failed", "blocked_host", res.blocked_host
    if res.hook_aborted:
        return "failed", "hook_aborted", res.abort
    if res.returncode != 0:
        return "failed", f"exit_{res.returncode}", None
    if not has_output:
        return "failed", "no_output", None
    if native_problems:
        return "failed", "unexpected_output", "; ".join(native_problems)[:500]
    return None


def run_yamabiyori(*, checkout, python, out_dir, limit, ref=MAIN_REF, model_runs_fn=None, cfg=None, clock=time.monotonic):
    """ヤマビヨリを実行して、成果物を out_dir に置く。→ run.json の agents.yamabiyori

    取り直し: 1 回目のあと fetched < pool_size なら、同じコマンドをもう一度実行する(1 回目を含めて最大 max_runs 回)。
    ヤマビヨリは変えない。取れた山の通信はヤマビヨリのキャッシュ(cache/、3 時間)で通信なしになる
    (mountain_weather_core.py の fetch_open_meteo。docs/collect-run4-analysis.md 7 章)。回ごとの通信の回数を残すので、計測フックの数で確かめられる。
    上限: 通信の回数(max_requests)は全部の回の合計。時間(total_timeout_s)も全部の回の合計で、超えたら次の回を始めない。
    2 回目以降が失敗したとき: 429 ならこのビヨリは rate_limited(指示書 5.2: 429 は即中止)、許可外のホストなら failed。
    それ以外(時間切れ・上限・終了コード≠0 など)は取り直しをやめ、それまでで最も多く取れた回の出力を使う。"""
    cfg = cfg or config()["collect"]["agents"]["yamabiyori"]
    out_dir, raw = Path(out_dir), Path(out_dir) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    checkout = Path(checkout).resolve()
    commit, version = yama.git_commit(checkout), yama.load_version(checkout)
    base = {"ref": ref, "commit": commit, "version": version, "limit": limit}
    try:
        mountains = yama.load_mountains(checkout)
    except (OSError, ValueError, SyntaxError) as e:
        return dict(_fail("mountains_unreadable", detail=str(e)[:300]), **base, requests=0, runtime_s=0.0, data_time=None)
    max_runs, max_req, total_s = int(cfg["max_runs"]), int(cfg["max_requests"]), float(cfg["total_timeout_s"])
    t0 = clock()
    attempts, results, best, stop = [], [], None, None
    for n in range(1, max_runs + 1):
        used = sum(len(r.records) for r in results)
        elapsed = clock() - t0
        if n > 1:
            if used >= max_req:
                stop = "request_budget"
                break
            if elapsed >= total_s:
                stop = "time_budget"
                break
        json_out = raw / f"yamabiyori-{n}-explore.json"
        res = run_hooked(yama.command(python, checkout, json_out, limit), cwd=checkout,
                         req_log=(raw / f"yamabiyori-{n}-requests.jsonl").resolve(),
                         max_requests=max_req - used, allow=allow_hosts("yamabiyori"),
                         timeout_s=max(1.0, min(float(cfg["timeout_s"]), total_s - elapsed)))
        (raw / f"yamabiyori-{n}-output.txt").write_text(res.stdout_tail + "\n--- stderr ---\n" + res.stderr_tail, encoding="utf-8", newline="\n")
        results.append(res)
        native = read_json(json_out) if res.returncode == 0 and not res.hook_aborted and not res.timed_out else None
        fail = _attempt_failure(res, yama.output_problems(native) if native is not None else None, has_output=native is not None)
        att = {"n": n, "status": "ok" if fail is None else fail[0], "reason": None if fail is None else fail[1],
               "requests": len(res.records), "runtime_s": res.runtime_s, "pool_size": None, "fetched": None}
        if fail is not None and fail[2]:
            att["detail"] = str(fail[2])[:500]
        if fail is None:
            att.update(pool_size=native["pool_size"], fetched=native["fetched"])
            prev_missing = attempts[-1]["pool_size"] - attempts[-1]["fetched"] if attempts and attempts[-1]["fetched"] is not None else None
            # 取れた山がキャッシュで通信なしになっていれば、2 回目以降の通信は「前の回に欠けた山 × 3 回の通信 × ヤマビヨリの 3 回の試行」以下
            if prev_missing is not None:
                att["cache_suspect"] = len(res.records) > prev_missing * 3 * 3
        attempts.append(att)
        if fail is not None:
            if n == 1 or fail[1] in ("rate_limited", "blocked_host"):
                break
            stop = f"run_{n}_{fail[1]}"
            break
        if best is None or native["fetched"] >= best[1]["fetched"]:
            best = (n, native, json_out, res)
        if native["fetched"] >= native["pool_size"]:
            break
    else:
        if best is not None and best[1]["fetched"] < best[1]["pool_size"]:
            stop = "max_runs"
    all_recs = [x for r in results for x in r.records]
    last = results[-1]
    fetch = summarize(all_recs, last.abort)
    fetch["blocked_host"] = next((r.blocked_host for r in results if r.blocked_host), None)
    runtime = round(clock() - t0, 1)
    entry = dict(base, requests=len(all_recs), runtime_s=runtime, data_time=None, fetch=fetch, attempts=attempts,
                 retry_stop=stop)
    if any(r.rate_limited for r in results):
        return dict(entry, status="rate_limited", reason="rate_limited")
    if fetch["blocked_host"]:
        return dict(entry, status="failed", reason="blocked_host", detail=fetch["blocked_host"])
    if best is None:
        a = attempts[0]                     # 1 回目が失敗(取り直しはしない)
        return dict(entry, status=a["status"], reason=a["reason"], **({"detail": a["detail"]} if a.get("detail") else {}))
    n_best, native, json_out, res = best
    fetched_at = res.finished_at
    runs = model_runs_fn() if model_runs_fn else {}
    sun = yama.load_sun_times(checkout / "cache", mountains)
    try:
        prop = yama.convert(native, now=now_jst(), fetched_at=fetched_at, native_path="yamabiyori/explore.json",
                            agent_version=version, agent_commit=commit, mountains=mountains, model_runs=runs, sun_times=sun)
    except ValueError as e:
        return dict(entry, status="failed", reason="convert_failed", detail=str(e)[:500])
    prop["diagnostics"].update(api_calls=len(all_recs), cache_hit=(len(all_recs) == 0), runtime_s=runtime)
    errs = schema_errors(prop, "biyori-proposal")
    mdoc = yama.mountains_doc(mountains, commit, version)
    errs += schema_errors(mdoc, "biyori-mountains")
    if errs:
        return dict(entry, status="failed", reason="schema_invalid", detail="; ".join(errs)[:500])
    (out_dir / "yamabiyori").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(json_out, out_dir / "yamabiyori" / "explore.json")          # --json-out そのまま(最も多く取れた回)
    write_json(out_dir / "yamabiyori" / "mountains.json", mdoc)
    write_json(out_dir / "proposals" / "yamabiyori.json", prop)
    cov = yama.coverage(native, mountains)
    complete = cov["missing"] == 0
    extra = {} if complete else {"detail": yama.coverage_text(cov)}
    # 全座そろわない回は ok にしない(incomplete)。棚には載せる(利用者の決定 A。shelf.py の PUBLISHABLE)
    return dict(entry, coverage=cov, used_run=n_best, status="ok" if complete else "incomplete",
                reason=None if complete else "partial_fetch", **extra,
                data_time=iso(fetched_at), proposal_status=prop["status"], proposals=len(prop["proposals"]), model_runs=runs)


def collect(*, agents, out_dir, checkouts, pythons, yama_limit=None, yamabiyori_ref=MAIN_REF, trigger="workflow_dispatch",
            concierge_commit=None, meta_fetch=None):
    """1回の取得。meta_fetch(phase) → meta.json の dict(テストでは偽物を渡す。既定は計測フックつきの子プロセス)。"""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw").mkdir(exist_ok=True)
    started = now_jst()
    meta_results = []

    def default_meta(phase):
        doc, res = meta_mod.fetch_meta(meta_mod.python_for_meta(), out_dir / "raw" / f"meta-{phase}.json",
                                       out_dir / "raw" / f"meta-{phase}-requests.jsonl")
        meta_results.append(res)
        return doc
    meta_fetch = meta_fetch or default_meta
    before = meta_fetch("before")
    rate_limited_early = any(r.rate_limited for r in meta_results)
    after_box = {}

    def runs_now():
        if "after" not in after_box:
            after_box["after"] = meta_fetch("after")
        return meta_mod.model_runs(before, after_box["after"])

    results = {}
    for a in AGENTS:
        if a not in agents:
            continue
        if rate_limited_early:
            results[a] = {"status": "rate_limited", "reason": "rate_limited_at_metadata", "requests": 0, "runtime_s": 0.0, "data_time": None}
        elif a == "yamabiyori":
            results[a] = run_yamabiyori(checkout=checkouts["yamabiyori"], python=pythons["yamabiyori"], out_dir=out_dir,
                                        limit=yama_limit, ref=yamabiyori_ref, model_runs_fn=runs_now)
        else:
            results[a] = {"status": "skipped", "reason": "not_implemented", "requests": 0, "runtime_s": 0.0, "data_time": None}
    model_runs = runs_now() if not rate_limited_early else meta_mod.model_runs(before, None)
    finished = now_jst()
    all_recs = []
    for f in sorted((out_dir / "raw").glob("*requests.jsonl")):
        all_recs += read_request_log(f)[0]
    totals = summarize(all_recs)
    totals.pop("aborted", None)
    logs = {"schema": "biyori-request-log/1", "started_at": iso(started), "finished_at": iso(finished),
            "estimated_calls_note": "estimated_calls は推定(Open-Meteo の公式の換算式は未確認。config.yaml の estimated_calls)",
            "total": totals,
            "agents": {a: {k: r.get("fetch", {}).get(k) for k in ("requests", "by_host", "by_status", "by_error", "estimated_calls", "aborted", "blocked_host")}
                       for a, r in results.items()},
            "metadata": summarize([x for m in meta_results for x in m.records])}
    write_json(out_dir / "logs" / "requests.json", logs)
    run = {"schema": RUN_SCHEMA, "slot": slot_of(started), "trigger": "schedule" if trigger == "schedule" else "workflow_dispatch",
           "started_at": iso(started), "finished_at": iso(finished), "concierge_commit": concierge_commit,
           "model_runs": {m: {k: v for k, v in r.items() if k != "init_before"} for m, r in model_runs.items()},
           "requested_agents": [a for a in AGENTS if a in agents], "yama_limit": yama_limit,
           "yamabiyori_ref": yamabiyori_ref if "yamabiyori" in agents else None,
           "publish_blocked": publish_blocked(agents, yamabiyori_ref),
           "agents": {a: {k: v for k, v in r.items() if k != "fetch"} for a, r in results.items()},
           "requests": {"total": totals["requests"], "by_host": totals["by_host"], "estimated_calls": totals["estimated_calls"]}}
    for a, r in run["agents"].items():
        if "model_runs" in r:
            r["model_runs"] = {m: {k: v for k, v in x.items() if k != "init_before"} for m, x in r["model_runs"].items()}
    errs = schema_errors(run, "biyori-collect-run")
    if errs:
        raise RuntimeError("run.json がスキーマに合わない(コードの不具合): " + "; ".join(errs))
    write_json(out_dir / "run.json", run)
    return run


def publish_blocked(agents, yamabiyori_ref):
    """この回を棚に載せない理由(載せてよいなら None)。ヤマビヨリを main 以外の ref で取った回は載せない(利用者の決定)。"""
    if "yamabiyori" in agents and yamabiyori_ref != MAIN_REF:
        return "yamabiyori_ref_not_main"
    return None


def parse_yamabiyori_ref(raw):
    """--yamabiyori-ref の値(ブランチ名・タグ名・commit)を検査して返す。空・空白・記号で始まる・".." を含むなどはエラー(ValueError)。
    前後の空白も取り除かずエラーにする(" main" を main と見なして棚に載せないため)。"""
    s = "" if raw is None else str(raw)
    if not s.strip():
        raise ValueError("ヤマビヨリの ref(yamabiyori_ref)が空です。いつもは main を入れてください")
    if not REF_RE.fullmatch(s) or ".." in s or "//" in s or s.endswith(("/", ".", ".lock")):
        raise ValueError(f"ヤマビヨリの ref(yamabiyori_ref)は、英数字と . _ / - だけのブランチ名か commit にしてください(入力: {s!r})")
    return s


def parse_yama_limit(raw):
    """--yama-limit の値 → 山の数(int)または None(全座)。
    "all" = 全座、1 以上の整数 = その数。空・all 以外の文字・0 以下はエラー(ValueError)。
    空を「全座」にしない: 手動実行の画面で欄を空にしても、初期値 3 で動いたことがあったため(原因は未確認)。"""
    s = "" if raw is None else str(raw).strip()
    if s == "all":
        return None
    if not s:
        raise ValueError("山の数(yama_limit)が空です。全座なら all、一部なら 1 以上の整数を入れてください")
    if not s.isascii() or not s.isdigit():
        raise ValueError(f"山の数(yama_limit)は all か 1 以上の整数にしてください(入力: {s!r})")
    n = int(s)
    if n <= 0:
        raise ValueError(f"山の数(yama_limit)は 1 以上にしてください(入力: {s!r})")
    return n


def main_run(args):
    agents = {"both": ["yamabiyori", "hoshibiyori"]}.get(args.agents, [args.agents])
    try:
        limit = parse_yama_limit(args.yama_limit)            # 通信の前に検査する
        ref = parse_yamabiyori_ref(getattr(args, "yamabiyori_ref", MAIN_REF))
    except ValueError as e:
        print(f"中止(通信していません): {e}", file=sys.stderr)
        return 2
    run = collect(agents=agents, out_dir=args.out, checkouts={"yamabiyori": args.yamabiyori_checkout},
                  pythons={"yamabiyori": args.yamabiyori_python or sys.executable}, yama_limit=limit, yamabiyori_ref=ref,
                  trigger=args.trigger, concierge_commit=args.concierge_commit or None)
    if run.get("yamabiyori_ref") is not None:
        print(f"yamabiyori: ref={run['yamabiyori_ref']} commit={run['agents'].get('yamabiyori', {}).get('commit')}")
    if run.get("publish_blocked"):
        print(f"この回は棚に載せません({run['publish_blocked']}: ヤマビヨリの ref が {MAIN_REF} でない)。publish にチェックがあっても載せません")
    for a, r in run["agents"].items():
        print(f"{a}: {r['status']}" + (f" ({r.get('reason')})" if r.get("reason") else "")
              + (f" 山={yama.coverage_text(r['coverage'])}" if "coverage" in r else "")
              + f" requests={r.get('requests')} runtime_s={r.get('runtime_s')}")
        for t in r.get("attempts") or []:
            print(f"  {a} {t['n']}回目: {t['status']}" + (f" ({t['reason']})" if t.get("reason") else "")
                  + f" requests={t['requests']} fetched={t['fetched']}/{t['pool_size']} runtime_s={t['runtime_s']}"
                  + (" キャッシュが効いていない疑い" if t.get("cache_suspect") else ""))
    logs = read_json(Path(args.out) / "logs" / "requests.json") or {}
    for name, x in (("metadata", logs.get("metadata") or {}), ("total", logs.get("total") or {})):
        print(f"{name}: by_status={x.get('by_status')} by_error={x.get('by_error') or 'なし'}")
    return 0
