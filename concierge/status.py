"""status: 棚の写しが「いつ時点か・どの回か・何時間前か・何座のうち何座か・ヤマビヨリの版」を出す。止まらない。"""
from . import shelf as S
from .common import config
from .texts import SLOT_JA, coverage_counts, data_time_label, runs_text

PROBLEM_JA = {"no_shelf": "手元に棚の写しがありません(`python -X utf8 -m concierge sync` で取り込みます)。",
              "broken_manifest": "棚の写しの目次(manifest)が壊れているか、検査に通りません。",
              "no_yamabiyori": "棚に山の予報がありません(取得に失敗した回の可能性)。",
              "broken_files": "棚の写しの山のファイルが壊れているか、検査に通りません。"}


def render(base, now):
    sh = S.load(base)
    lines = ["# 棚の写しの状態", ""]
    e, m = sh["entry"], sh["manifest"]
    if sh["problem"] in ("no_shelf", "broken_manifest"):
        lines.append(f"- 山: {PROBLEM_JA[sh['problem']]}")
    else:
        if e and e.get("data_time"):
            age = S.age_hours(e, now)
            stale = config()["collect"]["stale_after_hours"]
            total, pool, fetched = coverage_counts(e)
            lines.append(f"- 山: {data_time_label(e)} 時点({SLOT_JA.get(m.get('slot'), m.get('slot'))}の回。{runs_text(e.get('model_runs'))})")
            lines.append(f"  - {age} 時間前" + (f"({stale} 時間以上前の古い予報)" if age is not None and age >= stale else ""))
            lines.append(f"  - {total} 座のうち {fetched} 座(この回に調べた山 {pool} 座)。状態 {e.get('status')}"
                         + (f"(前回のファイルを残した回: {e.get('kept_from')})" if e.get("status") == "kept_previous" else ""))
            lines.append(f"  - ヤマビヨリ {e.get('version')}(commit {str(e.get('commit') or '')[:7]})")
        if sh["problem"]:
            lines.append(f"- 山: {PROBLEM_JA[sh['problem']]}")
    lines.append("- 星: まだありません(段階 3 から)")
    sy = sh["sync"]
    if sy:
        lines.append(f"- 最後の取り込み: {sy.get('at')} — {sy.get('message')}")
    return "\n".join(lines) + "\n"
