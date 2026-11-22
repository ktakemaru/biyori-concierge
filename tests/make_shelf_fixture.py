"""見本の棚 tests/fixtures/shelf/ を作り直す(答える側のテスト用)。通信しない。

  python -X utf8 tests/make_shelf_fixture.py

作り方: 偽のヤマビヨリ(tests/fixtures/yamabiyori/。記録済みの explore.json を書くだけ)を、今の取得の側(collect.run.collect)で
実行して artifact を作り、今の棚の組み立て(collect.shelf.prepare)で木にする。時刻は固定(2026-10-15 05:00 JST。
取得の時刻・変換の時刻・data_time がこの時刻になる)。commit の欄は作った時点のこのリポジトリの HEAD(見本なので意味はない)。
値はヤマビヨリの記録済みの入力のままで、本物の今の予報ではない(3 座・2026-10-12〜19)。"""
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import nonet  # noqa: F401,E402  (ソケット禁止)

from collect import shelf  # noqa: E402
from collect.common import JST, read_json  # noqa: E402
from collect.run import collect  # noqa: E402

FIXED = datetime(2026, 10, 15, 5, 0, 0, tzinfo=JST)
OUT = ROOT / "tests" / "fixtures" / "shelf"


def main():
    tmp = Path(tempfile.mkdtemp(prefix="biyori-shelf-fix-"))
    try:
        art = tmp / "art"
        with mock.patch("collect.run.now_jst", return_value=FIXED), mock.patch("collect.runner.now_jst", return_value=FIXED):
            collect(agents=["yamabiyori"], out_dir=art, checkouts={"yamabiyori": ROOT / "tests" / "fixtures" / "yamabiyori"},
                    pythons={"yamabiyori": sys.executable}, yama_limit=None,
                    meta_fetch=lambda ph: read_json(ROOT / "tests" / "fixtures" / "meta" / "before.json"))
        ex = tmp / "empty"
        ex.mkdir()
        pub = tmp / "pub"
        shelf.prepare(art, ex, pub)
        if OUT.exists():
            shutil.rmtree(OUT)
        shutil.copytree(pub, OUT)
        print(f"作りました: {OUT}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
