"""棚(data ブランチ)に置く木を組み立てる(publish ジョブの中身)。通信なし・git は使わない・取得のコードは実行しない。
考え方は biyori-hub hub/cloud_data.py の prepare(許可リストだけ取り込む・パスの検査)。中身は新しく書いた(docs/ported-from-hub.md)。

  python -X utf8 -m collect prepare --artifact <成果物> --existing <今の data の中身(無ければ空)> --out <空のフォルダ>

決まり(指示書 4 章):
- ビヨリごとに「成功したら入れ替える」。この回が ok で、ファイルがそろい、検査に通ったときだけ artifact のファイルを使う。
  それ以外は、前回の棚のファイルをそのまま残し status: kept_previous と理由を書く。前回が無ければ status: failed(ファイルなし)。
- 取り込むのは許可リストのファイルだけ。シンボリックリンク・想定外のファイルは無視する。
- 個人の設定(出発地など)は入れない。"""
import shutil
from pathlib import Path

from .common import COLLECT, dump_json, read_json, schema_errors

SHELF_SCHEMA = "biyori-shelf/1"
AGENT_FILES = {
    "yamabiyori": {"yamabiyori/explore.json": "native_explore", "yamabiyori/mountains.json": "biyori-mountains",
                   "proposals/yamabiyori.json": "biyori-proposal"},
    "hoshibiyori": {"hoshibiyori/milkyway.json": "native_hoshi", "hoshibiyori/stars.json": "native_hoshi",
                    "proposals/hoshibiyori.json": "biyori-proposal"},
}
NATIVE_SCHEMA = {"native_explore": "yamabiyori-report-data/1", "native_hoshi": "hoshibiyori-explore/1"}
ENTRY_KEYS = ("commit", "version", "data_time", "model_runs", "proposal_status", "proposals", "limit")


def _plain(p):
    p = Path(p)
    return p.is_file() and not p.is_symlink()


def file_problems(path, kind):
    """1ファイルの検査。→ 問題の文のリスト(空なら合格)。"""
    if not _plain(path):
        return [f"{path.name}: ない(またはシンボリックリンク)"]
    doc = read_json(path)
    if doc is None:
        return [f"{path.name}: JSON として読めない"]
    if kind in NATIVE_SCHEMA:
        return [] if isinstance(doc, dict) and doc.get("schema") == NATIVE_SCHEMA[kind] else [f"{path.name}: schema が {NATIVE_SCHEMA[kind]} でない"]
    return [f"{path.name}: {e}" for e in schema_errors(doc, kind)[:5]]


def agent_files_problems(root, agent):
    probs = []
    for rel, kind in AGENT_FILES[agent].items():
        probs += file_problems(Path(root) / rel, kind)
    return probs


def load_manifest(existing):
    m = read_json(Path(existing) / "manifest.json")
    return m if isinstance(m, dict) and not schema_errors(m, "biyori-shelf") else None


def build_manifest(run, previous, outcome):
    """run(この回の run.json)・previous(前回の manifest または None)・outcome({agent: "new"|"kept"|"failed"})→ manifest。"""
    agents = {}
    prev_agents = (previous or {}).get("agents") or {}
    for agent in AGENT_FILES:
        r = (run.get("agents") or {}).get(agent)
        how = outcome.get(agent)
        if how is None:
            continue
        this_run = {"requests": (r or {}).get("requests", 0), "runtime_s": (r or {}).get("runtime_s", 0.0)}
        if how == "new":
            e = {"status": "ok", **{k: r.get(k) for k in ENTRY_KEYS}, **this_run, "kept_from": None,
                 "files": sorted(AGENT_FILES[agent])}
        elif how == "kept":
            p = prev_agents[agent]
            kept_from = p.get("kept_from") if p.get("status") == "kept_previous" else previous.get("finished_at")
            e = {"status": "kept_previous", **{k: p.get(k) for k in ENTRY_KEYS}, **this_run, "kept_from": kept_from,
                 "reason": (r or {}).get("reason") or ((r or {}).get("status") if r else "not_requested"),
                 "files": sorted(AGENT_FILES[agent])}
        else:
            e = {"status": "failed", "commit": (r or {}).get("commit"), "version": (r or {}).get("version"), "data_time": None,
                 **this_run, "kept_from": None, "reason": (r or {}).get("reason") or "failed", "files": []}
        if r and r.get("detail"):
            e["detail"] = str(r["detail"])[:500]
        agents[agent] = e
    return {"schema": SHELF_SCHEMA, "slot": run["slot"], "trigger": run["trigger"], "started_at": run["started_at"],
            "finished_at": run["finished_at"], "concierge_commit": run.get("concierge_commit"),
            "model_runs": run.get("model_runs") or {}, "agents": agents,
            "requests": run.get("requests"),
            "notes": ["時刻はすべて ISO 8601・オフセットつき。分からない値は null",
                      "agents.*.model_runs はそのビヨリのファイルを取得したときの予報の回。最上位の model_runs はこの回の実行のもの",
                      "requests・runtime_s はこの回の実行の値。kept_previous のとき commit・version・data_time は残したファイルのもの"]}


def prepare(artifact, existing, out):
    """→ 要約 dict。out は無いか空。"""
    art, ex, out = Path(artifact), Path(existing), Path(out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f"出力先が空でない: {out}")
    run = read_json(art / "run.json")
    if not isinstance(run, dict) or schema_errors(run, "biyori-collect-run"):
        raise ValueError("artifact の run.json がない・スキーマに合わない(公開しない)")
    previous = load_manifest(ex)
    prev_agents = (previous or {}).get("agents") or {}
    outcome, reasons = {}, {}
    for agent in AGENT_FILES:
        r = (run.get("agents") or {}).get(agent)
        if r and r.get("status") == "ok":
            probs = agent_files_problems(art, agent)
            if not probs:
                outcome[agent] = "new"
                continue
            r["status"], r["reason"], r["detail"] = "failed", "artifact_invalid", "; ".join(probs)[:500]
        prev = prev_agents.get(agent)
        if prev and prev.get("status") in ("ok", "kept_previous") and not agent_files_problems(ex, agent):
            outcome[agent] = "kept"
        elif r and r.get("status") != "skipped":
            outcome[agent] = "failed"
        if r:
            reasons[agent] = r.get("reason")
    manifest = build_manifest(run, previous, outcome)
    errs = schema_errors(manifest, "biyori-shelf")
    if errs:
        raise RuntimeError("manifest がスキーマに合わない(コードの不具合): " + "; ".join(errs))
    out.mkdir(parents=True, exist_ok=True)
    for agent, how in outcome.items():
        if how == "failed":
            continue
        src = art if how == "new" else ex
        for rel in AGENT_FILES[agent]:
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / rel, dst)
    logs = read_json(art / "logs" / "requests.json")
    if isinstance(logs, dict) and not schema_errors(logs, "biyori-request-log"):
        (out / "logs").mkdir(exist_ok=True)
        (out / "logs" / "requests.json").write_text(dump_json(logs), encoding="utf-8", newline="\n")
    shutil.copyfile(COLLECT / "ATTRIBUTION.md", out / "ATTRIBUTION.md")
    (out / "manifest.json").write_text(dump_json(manifest), encoding="utf-8", newline="\n")
    return {"outcome": outcome, "reasons": reasons,
            "files": sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())}


def _tally(d):
    return ", ".join(f"{k} {v} 件" for k, v in d.items()) if d else "なし"


def render_summary(artifact):
    """$GITHUB_STEP_SUMMARY 用の Markdown(通信なし。run.json が無くても落ちない)。"""
    run = read_json(Path(artifact) / "run.json")
    logs = read_json(Path(artifact) / "logs" / "requests.json") or {}
    lines = ["## 取得の結果", ""]
    if not isinstance(run, dict):
        return "\n".join(lines + ["run.json がありません(取得の前に止まった可能性。collect ジョブのログを見る)。", ""])
    lines += [f"- 開始 {run.get('started_at')} / 終了 {run.get('finished_at')}(slot: {run.get('slot')}, trigger: {run.get('trigger')})", ""]
    lines += ["| ビヨリ | 状態 | 理由 | 通信の回数 | 所要(秒) | データの時刻 |", "|---|---|---|---|---|---|"]
    for a, r in (run.get("agents") or {}).items():
        lines.append(f"| {a} | {r.get('status')} | {r.get('reason') or ''} {r.get('detail') or ''} | {r.get('requests')} | {r.get('runtime_s')} | {r.get('data_time') or 'なし'} |")
    lines += ["", "| モデル | 初期時刻 | 公開 | 前後で同じ |", "|---|---|---|---|"]
    for m, r in (run.get("model_runs") or {}).items():
        lines.append(f"| {m} | {r.get('init') or 'なし'} | {r.get('available') or 'なし'} | {r.get('same_before_after')} |")
    t = logs.get("total") or {}
    lines += ["", f"- 通信: 合計 {t.get('requests')} 件、ホスト別 {t.get('by_host')}、ステータス別 {t.get('by_status')}、推定 call {t.get('estimated_calls')}(推定)"]
    lines.append(f"- 失敗の種類(例外の名前): {_tally(t.get('by_error'))}")
    md = logs.get("metadata") or {}
    lines.append(f"- メタデータ(meta.json): {md.get('requests')} 件、ステータス別 {md.get('by_status')}、失敗の種類 {_tally(md.get('by_error'))}")
    blocked = [f"{a}: {x.get('blocked_host')}" for a, x in (logs.get("agents") or {}).items() if x.get("blocked_host")]
    lines.append(f"- 止められたホスト: {', '.join(blocked) if blocked else 'なし'}")
    rl = [a for a, r in (run.get("agents") or {}).items() if r.get("status") == "rate_limited"]
    lines.append(f"- 429: {'あり(' + ', '.join(rl) + ')' if rl else 'なし'}")
    return "\n".join(lines) + "\n"
