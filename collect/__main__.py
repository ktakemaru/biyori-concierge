"""取得の側のコマンド。

  python -X utf8 -m collect run --agents yamabiyori|hoshibiyori|both --out <dir> --yamabiyori-checkout <dir>
                               [--yamabiyori-python <venv の python>] --yama-limit all|N [--yamabiyori-ref <ref>(既定 main)]
                               [--trigger schedule|workflow_dispatch] [--concierge-commit <sha>]
                                                                   … 実通信(Actions の collect ジョブの中だけで使う)
  python -X utf8 -m collect check-inputs --yama-limit all|N --yamabiyori-ref <ref>  … 手動実行の入力の検査(通信なし。取り出しの前に使う)
  python -X utf8 -m collect prepare --artifact <dir> --existing <dir> --out <dir>   … 棚の木を組み立てる(通信なし)
  python -X utf8 -m collect summary --artifact <dir>                                … 実行の要約(Markdown。通信なし)
  python -X utf8 -m collect verdict --artifact <dir>                                … 要求したビヨリがすべて ok なら 0、そうでなければ 1
  python -X utf8 -m collect diagnose --out <dir>                                    … 診断: IP アドレスごとの応答(実通信。diagnose.yml の中だけで使う)
  python -X utf8 -m collect diagnose-summary --artifact <dir>                       … 診断の要約(Markdown。通信なし)
"""
import argparse
import json
import sys

from . import shelf
from .common import read_json


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m collect", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--agents", required=True, choices=["yamabiyori", "hoshibiyori", "both"])
    r.add_argument("--out", required=True)
    r.add_argument("--yamabiyori-checkout")
    r.add_argument("--yamabiyori-python")
    r.add_argument("--yama-limit", required=True, help="山の数。all = 全座、または 1 以上の整数(空・0 以下はエラー)")
    r.add_argument("--yamabiyori-ref", default="main", help="取り出したヤマビヨリのブランチ・commit(main 以外の回は棚に載せない)")
    r.add_argument("--trigger", default="workflow_dispatch")
    r.add_argument("--concierge-commit", default=None)
    c = sub.add_parser("check-inputs")
    c.add_argument("--yama-limit", required=True)
    c.add_argument("--yamabiyori-ref", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--artifact", required=True)
    p.add_argument("--existing", required=True)
    p.add_argument("--out", required=True)
    s = sub.add_parser("summary")
    s.add_argument("--artifact", required=True)
    v = sub.add_parser("verdict")
    v.add_argument("--artifact", required=True)
    g = sub.add_parser("diagnose")
    g.add_argument("--out", required=True)
    gs = sub.add_parser("diagnose-summary")
    gs.add_argument("--artifact", required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "run":
        if a.agents in ("yamabiyori", "both") and not a.yamabiyori_checkout:
            ap.error("--yamabiyori-checkout が必要")
        from .run import main_run
        return main_run(a)
    if a.cmd == "check-inputs":
        from .run import MAIN_REF, parse_yama_limit, parse_yamabiyori_ref
        try:
            limit, ref = parse_yama_limit(a.yama_limit), parse_yamabiyori_ref(a.yamabiyori_ref)
        except ValueError as e:
            print(f"中止(通信していません): {e}", file=sys.stderr)
            return 2
        print(f"yama_limit={'all' if limit is None else limit} yamabiyori_ref={ref}"
              + ("" if ref == MAIN_REF else "(main でないので、この回は棚に載せません)"))
        return 0
    if a.cmd == "prepare":
        print(json.dumps(shelf.prepare(a.artifact, a.existing, a.out), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "summary":
        sys.stdout.write(shelf.render_summary(a.artifact))
        return 0
    if a.cmd in ("diagnose", "diagnose-summary"):
        from . import diag
        if a.cmd == "diagnose-summary":
            sys.stdout.write(diag.render_summary(a.artifact))
            return 0
        d = diag.diagnose(a.out)
        print(f"diagnose: returncode={d['returncode']} requests={d['hook']['requests']} by_status={d['hook']['by_status']}")
        return 0 if isinstance(d.get("probe"), dict) else 1
    run = read_json(f"{a.artifact}/run.json") or {}
    agents = run.get("agents") or {}
    bad = [k for k in run.get("requested_agents", []) if agents.get(k, {}).get("status") != "ok"]
    if not run or bad:
        # incomplete(全座そろわない)も ok ではないので赤にする。publish ジョブは always() なので、この結果では止まらない
        print("ok でないビヨリ: " + (", ".join(f"{k}({agents.get(k, {}).get('status')}"
                                             + (f": {agents[k]['detail']}" if agents.get(k, {}).get("detail") else "") + ")"
                                             for k in bad) if bad else "run.json なし"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
