"""1回の取得(collect ジョブの中身)。成果物のフォルダ(artifact)を作る。棚(data ブランチ)には書かない(それは publish)。

成果物の形(out_dir):
  run.json                      この回の結果(スキーマ biyori-collect-run/1)。publish が manifest を作る材料
  yamabiyori/explore.json       成功したときだけ
  yamabiyori/mountains.json     成功したときだけ
  proposals/yamabiyori.json     成功したときだけ
  logs/requests.json            通信の集計(ホスト別・ステータス別・失敗の種類(例外の名前)別の回数だけ)
  raw/                          フックの記録(JSONL)と標準出力の末尾。artifact にだけ残し、棚には載せない

ビヨリの失敗(終了コード≠0・429・フックの中止・出力の形が違う)は、そのビヨリを status≠ok にするだけで、ほかのビヨリは続ける。
"""
import shutil
import sys
from pathlib import Path

from . import meta as meta_mod
from . import yamabiyori as yama
from .common import allow_hosts, config, iso, now_jst, read_json, schema_errors, write_json
from .runner import child_summary, read_request_log, run_hooked, summarize

AGENTS = ("yamabiyori", "hoshibiyori")
RUN_SCHEMA = "biyori-collect-run/1"


def slot_of(t):
    """日本時間の午前 = morning、午後 = evening。"""
    return "morning" if t.astimezone(t.tzinfo).hour < 12 else "evening"


def _fail(reason, **kw):
    return dict({"status": "failed", "reason": reason}, **kw)


def run_yamabiyori(*, checkout, python, out_dir, limit, model_runs_fn=None):
    """ヤマビヨリを1回だけ実行して、成果物を out_dir に置く。→ run.json の agents.yamabiyori"""
    out_dir, raw = Path(out_dir), Path(out_dir) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    checkout = Path(checkout).resolve()
    commit, version = yama.git_commit(checkout), yama.load_version(checkout)
    base = {"commit": commit, "version": version, "limit": limit}
    try:
        mountains = yama.load_mountains(checkout)
    except (OSError, ValueError, SyntaxError) as e:
        return dict(_fail("mountains_unreadable", detail=str(e)[:300]), **base, requests=0, runtime_s=0.0, data_time=None)
    json_out = raw / "yamabiyori-explore.json"
    cfg = config()["collect"]["agents"]["yamabiyori"]
    res = run_hooked(yama.command(python, checkout, json_out, limit), cwd=checkout, req_log=(raw / "yamabiyori-requests.jsonl").resolve(),
                     max_requests=cfg["max_requests"], allow=allow_hosts("yamabiyori"), timeout_s=cfg["timeout_s"])
    (raw / "yamabiyori-output.txt").write_text(res.stdout_tail + "\n--- stderr ---\n" + res.stderr_tail, encoding="utf-8", newline="\n")
    fetch = child_summary(res)
    entry = dict(base, requests=fetch["requests"], runtime_s=res.runtime_s, data_time=None, fetch=fetch)
    if res.rate_limited:
        return dict(entry, status="rate_limited", reason="rate_limited")
    if res.timed_out:
        return dict(entry, status="failed", reason="timeout")
    if res.blocked_host:
        return dict(entry, status="failed", reason="blocked_host", detail=res.blocked_host)
    if res.hook_aborted:
        return dict(entry, status="failed", reason="hook_aborted", detail=res.abort)
    if res.returncode != 0:
        return dict(entry, status="failed", reason=f"exit_{res.returncode}")
    native = read_json(json_out)
    if native is None:
        return dict(entry, status="failed", reason="no_output")
    probs = yama.output_problems(native)
    if probs:
        return dict(entry, status="failed", reason="unexpected_output", detail="; ".join(probs)[:500])
    fetched_at = res.finished_at
    runs = model_runs_fn() if model_runs_fn else {}
    sun = yama.load_sun_times(checkout / "cache", mountains)
    try:
        prop = yama.convert(native, now=now_jst(), fetched_at=fetched_at, native_path="yamabiyori/explore.json",
                            agent_version=version, agent_commit=commit, mountains=mountains, model_runs=runs, sun_times=sun)
    except ValueError as e:
        return dict(entry, status="failed", reason="convert_failed", detail=str(e)[:500])
    prop["diagnostics"].update(api_calls=fetch["requests"], cache_hit=(fetch["requests"] == 0), runtime_s=res.runtime_s)
    errs = schema_errors(prop, "biyori-proposal")
    mdoc = yama.mountains_doc(mountains, commit, version)
    errs += schema_errors(mdoc, "biyori-mountains")
    if errs:
        return dict(entry, status="failed", reason="schema_invalid", detail="; ".join(errs)[:500])
    (out_dir / "yamabiyori").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(json_out, out_dir / "yamabiyori" / "explore.json")          # --json-out そのまま
    write_json(out_dir / "yamabiyori" / "mountains.json", mdoc)
    write_json(out_dir / "proposals" / "yamabiyori.json", prop)
    return dict(entry, status="ok", reason=None, data_time=iso(fetched_at), proposal_status=prop["status"],
                proposals=len(prop["proposals"]), model_runs=runs)


def collect(*, agents, out_dir, checkouts, pythons, yama_limit=None, trigger="workflow_dispatch", concierge_commit=None,
            meta_fetch=None):
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
                                        limit=yama_limit, model_runs_fn=runs_now)
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
    except ValueError as e:
        print(f"中止(通信していません): {e}", file=sys.stderr)
        return 2
    run = collect(agents=agents, out_dir=args.out, checkouts={"yamabiyori": args.yamabiyori_checkout},
                  pythons={"yamabiyori": args.yamabiyori_python or sys.executable}, yama_limit=limit,
                  trigger=args.trigger, concierge_commit=args.concierge_commit or None)
    for a, r in run["agents"].items():
        print(f"{a}: {r['status']}" + (f" ({r.get('reason')})" if r.get("reason") else "")
              + f" requests={r.get('requests')} runtime_s={r.get('runtime_s')}")
    logs = read_json(Path(args.out) / "logs" / "requests.json") or {}
    for name, x in (("metadata", logs.get("metadata") or {}), ("total", logs.get("total") or {})):
        print(f"{name}: by_status={x.get('by_status')} by_error={x.get('by_error') or 'なし'}")
    return 0
