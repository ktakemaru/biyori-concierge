"""答える側のテストの共通部品。見本の棚(tests/fixtures/shelf/。作り方は tests/make_shelf_fixture.py)を一時の置き場に写す。"""
import json
import os
import shutil
from pathlib import Path
from unittest import mock

from helpers import FIX, tmpdir

SHELF_FIX = FIX / "shelf"
NOW = "2026-10-15T08:00:00+09:00"          # 見本の棚(2026-10-15 05:00 時点)の 3 時間後。今週末は 10/17(土)・10/18(日)
QUESTION = "今週末、登山に行くならどこ?"


def base_with_shelf(test, shelf=True, edit=None):
    """一時の置き場を作り、BIYORI_CONCIERGE_DATA_DIR をそこへ向ける(テストのあいだだけ)。edit(shelf_dir) で見本を書き換える。"""
    base = tmpdir(test, "biyori-cdata-")
    p = mock.patch.dict(os.environ, {"BIYORI_CONCIERGE_DATA_DIR": str(base)})
    p.start()
    test.addCleanup(p.stop)
    if shelf:
        shutil.copytree(SHELF_FIX, base / "shelf")
        if edit:
            edit(base / "shelf")
    return base


def edit_json(path, fn):
    path = Path(path)
    d = json.loads(path.read_text(encoding="utf-8"))
    fn(d)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def make_hazard(mid, day, level="危険", hazard="wind"):
    """作り物: 見本の提案の 1 件(山 mid・日 day)に危険信号を足す(見本に警戒・危険の山がないため)。"""
    label = {"thunder": "雷", "wind": "強風", "cold": "低体温症"}[hazard]

    def fn(shelf_dir):
        def f(d):
            for p in d["proposals"]:
                if p["id"] == f"yamabiyori:explore:{day}:{mid}":
                    p["constraints"] = [c for c in p.get("constraints") or [] if c.get("hazard") != hazard]
                    p["constraints"].append({"kind": "hazard", "hazard": hazard, "level": level, "text": f"{label}:{level}",
                                             "hard": level in ("警戒", "危険")})
        edit_json(Path(shelf_dir) / "proposals" / "yamabiyori.json", f)
    return fn


def build(base, **kw):
    from concierge import brief as B
    from concierge.common import parse_now
    args = {"question": QUESTION, "when": "今週末", "now": parse_now(kw.pop("now", NOW)), "base": base}
    args.update(kw)
    doc = B.build(**args)
    B.save(doc, base)
    return doc


def fact(doc, name, day):
    return next(f for f in doc["facts"] if f["name"].startswith(name) and f["date"] == day)


def named_line(doc):
    """1 文だけの検査を見るテストの下書きに足す行: 名指しの山の名前を全部出す(答えに出ていないと named_missing で止まるため)。名指しが無ければ空。"""
    names = list(dict.fromkeys(f["name"] for f in doc["facts"] if f["named"]))
    return ("・".join(names) + "という名前の由来には、いくつかの説があるといわれます。" + chr(10)) if names else ""


def line_for(doc, fid):
    return next(h for h in doc["lines"]["hazards"] if h["fact"] == fid)
