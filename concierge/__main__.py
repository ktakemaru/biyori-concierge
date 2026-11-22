"""python -X utf8 -m concierge <sync|status|brief|verify>(指示書 6.1)。どれも通信しない(sync の git だけ)。"""
import argparse
import sys
from pathlib import Path

from .common import data_dir, parse_now


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -X utf8 -m concierge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="data ブランチを取り込んで手元の置き場に写す(失敗しても止めない)")
    p = sub.add_parser("status", help="棚の写しがいつ時点か・どの回か・何時間前か")
    p.add_argument("--now")
    p = sub.add_parser("brief", help="質問のための資料を作る")
    p.add_argument("--question", required=True)
    p.add_argument("--when", default="今週末")
    p.add_argument("--region", action="append")
    p.add_argument("--interest", action="append")
    p.add_argument("--origin")
    p.add_argument("--mountain", action="append")
    p.add_argument("--now")
    p = sub.add_parser("verify", help="下書きを資料と照らす")
    p.add_argument("draft")
    p.add_argument("--brief", required=True)
    p.add_argument("--now")
    a = ap.parse_args(argv)
    try:
        base = data_dir()
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if a.cmd == "sync":
        from . import shelf
        r = shelf.sync(base, parse_now(None))
        print(r["message"])
        return 0
    if a.cmd == "status":
        from . import status
        sys.stdout.write(status.render(base, parse_now(a.now)))
        return 0
    if a.cmd == "brief":
        from . import brief
        try:
            now = parse_now(a.now)
            doc = brief.build(question=a.question, when=a.when, region=a.region, interest=a.interest, origin=a.origin,
                              mountains=a.mountain, now=now, base=base)
        except ValueError as e:
            print(f"資料を作れませんでした: {e}", file=sys.stderr)
            return 2
        jp, mp = brief.save(doc, base)
        print(doc["id"])
        print(jp)
        print(mp)
        return 0
    if a.cmd == "verify":
        from . import verify
        try:
            text = Path(a.draft).read_text(encoding="utf-8")
        except OSError as e:
            print(f"下書きを読めませんでした: {e}", file=sys.stderr)
            return 2
        res = verify.run(text, a.brief, base, parse_now(a.now))
        if res["status"] == "NO_BRIEF":
            print(f"資料 {a.brief} がありません(brief を先に実行する)", file=sys.stderr)
            return 2
        if res["status"] == "FAIL":
            sys.stderr.write(verify.report(res))
            return 1
        if res["status"] == "FALLBACK":
            sys.stderr.write(verify.report(res) + "3 回目も不合格のため、控えの文を出しました。\n")
        sys.stdout.write(res["text"])
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
