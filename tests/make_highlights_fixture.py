"""見どころ(highlights)・夜の中の順位(night_rank)・地点の出どころ(origin)の入った星の見本を作る
(tests/fixtures/hoshibiyori_hl/ と tests/fixtures/shelf_hl/)。通信しない。テストでは使わない(見本を作り直すときだけ)。
段階 3 の見本(tests/fixtures/hoshibiyori/・tests/fixtures/shelf_day/。1.2.0 の古い形)は消さない・書き換えない(古い形の確かめに使う)。

  python -X utf8 tests/make_highlights_fixture.py [--stars C:/temp/hoshi-followup-20261127/after3/st_nights.out.json]
                                                  [--milkyway C:/temp/hoshi-followup-20261127/after3/mw_nights.out.json]
                                                  [--schema C:/hoshibiyori/schemas/hoshibiyori-explore.schema.json]

もと(どちらも実物。置き場のファイルは読むだけ):
- 星: ホシビヨリ main(PR #42 のコード。出力の commit は bfc0a92)の --json-out(2026-11-27 09:05〜09:06、固定キャッシュ、主軸 146 地点、
  14 夜ぶんの --nights つき)。地点を SITES だけに減らす(段階 3 と同じ減らし方)。highlights は地点によらないので、そのまま。
- 山: 段階 3 の見本の棚(tests/fixtures/shelf_day/。2026-11-23 16:53 時点の実物を 12 座に減らしたもの)を、そのまま使う。
- スキーマ: ホシビヨリの main の schemas/hoshibiyori-explore.schema.json を写す(取り出した版のスキーマで検査するため)。

決まり: 数字を作らない・直さない。減らすのは、地点の一覧(site_index・requested_nights[].sites・finals・outlooks)だけ。
night_rank は実物の値のまま(減らした見本の中では、番号が飛ぶ)。夜ごとの件数(counts)・fetch・thresholds は実物のまま。
実物に無い種類(見どころが null の夜・origin が viewpoint の地点・流星群の極大が聞かれた夜に入る夜・MSM の候補の夜)は作らない。

棚の木は、今の取得の側(collect.run)で偽のホシビヨリ(tests/fixtures/hoshibiyori/explore_hoshibiyori.py の写し)を実行し、
その成果物に山のファイルを入れて、今の棚の組み立て(collect.shelf.prepare)で作る(make_stars_fixture.py と同じ)。"""
import argparse
import json
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
from collect.common import JST, read_json, write_json  # noqa: E402
from collect.run import collect  # noqa: E402

OLD_HOSHI = ROOT / "tests" / "fixtures" / "hoshibiyori"
OLD_SHELF = ROOT / "tests" / "fixtures" / "shelf_day"
HOSHI = ROOT / "tests" / "fixtures" / "hoshibiyori_hl"
OUT = ROOT / "tests" / "fixtures" / "shelf_hl"
FIXED = datetime(2026, 11, 27, 9, 6, 17, tzinfo=JST)      # 星空・星座モードの generated_at(2 つのうち遅いほう)
SITES = (
    # 段階 3 の見本の地点のうち、主軸 146 地点にあるもの(山の近く・リフト要・近くに山が無い・250km の外)
    "美し森展望台(北杜市(清里高原))", "白駒の池(佐久穂町・小海町)", "苗場スキー場(湯沢町)", "山中湖パノラマ台(山中湖村)", "丹沢湖(山北町)",
    "奥多摩湖ダムサイトパーキング(奥多摩町)", "千畳敷カール(駒ヶ根市)", "神磯の鳥居・大洗海岸(大洗町)", "八丈富士(八丈町)",
    # 横浜から近い順の先頭(11/28 の実物で night_rank 26・25。今までの並びなら先頭になる地点)
    "城ヶ島（馬の背洞門）(三浦市)", "安房埼灯台(三浦市(城ヶ島))",
    # night_rank の上の地点(11/28 の 2・4・5・12 位、11/29 の 3 位。どれも横浜から直線 250km 以内)
    "日光白根山ロープウェイ山頂駅(日光市)", "西伊豆スカイライン（仁科峠）(西伊豆町)", "野島埼灯台(南房総市)",
    "富士山五合目（富士スバルライン）(富士宮市)", "石廊崎(南伊豆町)")


def reduce_stars(doc):
    ids = {}
    for label in SITES:
        hit = [x["site_id"] for x in doc["site_index"] if x["label"] == label]
        assert len(hit) == 1 and hit[0] is not None, label
        ids[hit[0]] = label
    doc["site_index"] = [x for x in doc["site_index"] if x["site_id"] in ids]
    for r in doc["requested_nights"]:
        r["sites"] = [s for s in r["sites"] if s["site_id"] in ids]
    for key in ("finals", "outlooks"):
        doc[key] = [x for x in doc[key] if x["site_id"] in ids]
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stars", default="C:/temp/hoshi-followup-20261127/after3/st_nights.out.json")
    ap.add_argument("--milkyway", default="C:/temp/hoshi-followup-20261127/after3/mw_nights.out.json")
    ap.add_argument("--schema", default="C:/hoshibiyori/schemas/hoshibiyori-explore.schema.json")
    a = ap.parse_args()
    (HOSHI / "schemas").mkdir(parents=True, exist_ok=True)
    (HOSHI / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OLD_HOSHI / "explore_hoshibiyori.py", HOSHI / "explore_hoshibiyori.py")
    shutil.copyfile(OLD_HOSHI / ".claude-plugin" / "plugin.json", HOSHI / ".claude-plugin" / "plugin.json")      # 版は 1.2.0 のまま(実物も 1.2.0)
    shutil.copyfile(a.schema, HOSHI / "schemas" / "hoshibiyori-explore.schema.json")
    for mode, src in (("stars", a.stars), ("milkyway", a.milkyway)):
        doc = json.loads(Path(src).read_text(encoding="utf-8"))
        assert doc["target"] == mode and "highlights" in doc, src
        write_json(HOSHI / f"{mode}.json", reduce_stars(doc))
    old_man = read_json(OLD_SHELF / "manifest.json")
    tmp = Path(tempfile.mkdtemp(prefix="biyori-hl-fix-"))
    try:
        art = tmp / "art"
        with mock.patch("collect.run.now_jst", return_value=FIXED), mock.patch("collect.runner.now_jst", return_value=FIXED):
            collect(agents=["hoshibiyori"], out_dir=art, checkouts={"hoshibiyori": HOSHI}, pythons={"hoshibiyori": sys.executable},
                    hoshibiyori_data_dir=tmp / "hd", meta_fetch=lambda ph: None)      # 星を取ったときの予報の回は分からない(null のまま)
        run = read_json(art / "run.json")
        assert run["agents"]["hoshibiyori"]["status"] == "ok", run["agents"]
        run["agents"]["hoshibiyori"]["commit"] = read_json(HOSHI / "stars.json")["commit"]      # 出力に入っている実物の commit
        hp = read_json(art / "proposals" / "hoshibiyori.json")
        hp["agent"]["commit"] = run["agents"]["hoshibiyori"]["commit"]
        hp["diagnostics"]["runtime_s"] = 0.0
        write_json(art / "proposals" / "hoshibiyori.json", hp)
        run["agents"]["hoshibiyori"]["runtime_s"] = 0.0                       # 偽のホシビヨリの秒(作るたびに変わるので 0 にする)
        for m in run["agents"]["hoshibiyori"]["modes"]:
            m["runtime_s"] = 0.0
        run["agents"]["yamabiyori"] = old_man["agents"]["yamabiyori"]          # 段階 3 の見本の山(11/23 の実物)の記録のまま
        run["requested_agents"] = ["yamabiyori", "hoshibiyori"]
        run["yamabiyori_ref"] = "main"
        write_json(art / "run.json", run)
        for rel in ("yamabiyori/explore.json", "yamabiyori/mountains.json", "proposals/yamabiyori.json"):
            write_json(art / rel, read_json(OLD_SHELF / rel))
        ex = tmp / "empty"
        ex.mkdir()
        pub = tmp / "pub"
        print(shelf.prepare(art, ex, pub)["outcome"])
        if OUT.exists():
            shutil.rmtree(OUT)
        shutil.copytree(pub, OUT)
        print(f"作りました: {OUT}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
