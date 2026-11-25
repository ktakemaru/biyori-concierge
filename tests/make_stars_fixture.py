"""星の見本を作り直す(tests/fixtures/hoshibiyori/ と tests/fixtures/shelf_day/)。通信しない。テストでは使わない(見本を作り直すときだけ)。

  python -X utf8 tests/make_stars_fixture.py [--stars C:/temp/stage3/stars.json] [--milkyway C:/temp/stage3/milkyway.json]

もと(どちらも実物):
- 星: ホシビヨリ 1.2.0 の --json-out(2026-11-25 22:08 と 22:34。14 夜ぶんの --nights つき)。地点を SITES だけに減らす。
- 山: 手元に取り込んである棚 origin/data(2026-11-23 16:53 時点。`git show` で読むだけ)。山を MOUNTAINS だけに減らす。

決まり: 数字を作らない・直さない。減らすのは、地点の一覧(site_index・requested_nights[].sites・finals・outlooks)と山の行だけ。
夜ごとの件数(counts)・sites・fetch・thresholds・山の coverage(76 座のうち 76 座)は、実物のままにする(減らした見本の数とは合わない)。
山の時点(11/23)は星の時点(11/25)より前なので、星の時刻で見ると山は「古い予報」になる。山も新しい形のテストは、テストの中で
山の時点だけを書き換える(作り物と分かるように書く)。

棚の木は、今の取得の側(collect.run)で偽のホシビヨリを実行し、その成果物に山のファイルを入れて、今の棚の組み立て(collect.shelf.prepare)で作る。"""
import argparse
import json
import shutil
import subprocess
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

HOSHI = ROOT / "tests" / "fixtures" / "hoshibiyori"
OUT = ROOT / "tests" / "fixtures" / "shelf_day"
FIXED = datetime(2026, 11, 25, 22, 34, 21, tzinfo=JST)      # 天の川モードの generated_at
# 今までの山の見本(tests/fixtures/shelf)の 3 座(赤岳・横岳・谷川岳)と、その近くの地点 / 段階 3 の流れに使う山とその近くの地点 / 近くに山が無い地点
MOUNTAINS = ("八ヶ岳(赤岳)", "横岳", "谷川岳", "石割山", "鍋割山", "大山(伊勢原)", "高尾山", "陣馬山", "御岳山", "筑波山(女体山)", "木曽駒ヶ岳", "三ツ峠山(開運山)")
SITES = ("美し森展望台(北杜市(清里高原))", "第1展望台(茅野市)", "白駒の池(佐久穂町・小海町)", "谷川岳展望台(みなかみ町)", "苗場スキー場(湯沢町)",
         "石割山(山中湖村)", "山中湖パノラマ台(山中湖村)", "丹沢湖(山北町)", "菰釣山(道志村)", "奥多摩湖ダムサイトパーキング(奥多摩町)", "猿橋(大月市)",
         "千畳敷カール(駒ヶ根市)",                                   # リフト要の地点
         "神磯の鳥居・大洗海岸(大洗町)", "八丈富士(八丈町)")            # 近くに山が無い地点


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


def git_show(rel):
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"origin/data:{rel}"], capture_output=True, check=True)
    return json.loads(r.stdout.decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stars", default="C:/temp/stage3/stars.json")
    ap.add_argument("--milkyway", default="C:/temp/stage3/milkyway.json")
    a = ap.parse_args()
    for mode, src in (("stars", a.stars), ("milkyway", a.milkyway)):
        write_json(HOSHI / f"{mode}.json", reduce_stars(json.loads(Path(src).read_text(encoding="utf-8"))))
    man = git_show("manifest.json")
    mountains = git_show("yamabiyori/mountains.json")
    keep = {m["id"]: m["name"] for m in mountains["mountains"] if m["name"] in MOUNTAINS}
    assert len(keep) == len(MOUNTAINS), sorted(set(MOUNTAINS) - set(keep.values()))
    prop = git_show("proposals/yamabiyori.json")
    prop["proposals"] = [p for p in prop["proposals"] if p["place"]["site_ref"].split(":")[1] in keep]
    explore = git_show("yamabiyori/explore.json")
    for d in explore["days"]:
        for key in ("rows", "all"):
            d[key] = [r for r in d[key] if r.get("id") in keep]
    tmp = Path(tempfile.mkdtemp(prefix="biyori-stars-fix-"))
    try:
        art = tmp / "art"
        with mock.patch("collect.run.now_jst", return_value=FIXED), mock.patch("collect.runner.now_jst", return_value=FIXED):
            collect(agents=["hoshibiyori"], out_dir=art, checkouts={"hoshibiyori": HOSHI}, pythons={"hoshibiyori": sys.executable},
                    hoshibiyori_data_dir=tmp / "hd", meta_fetch=lambda ph: None)      # 星を取ったときの予報の回は分からない(null のまま)
        run = read_json(art / "run.json")
        assert run["agents"]["hoshibiyori"]["status"] == "ok", run["agents"]
        real = man["agents"]["yamabiyori"]
        run["agents"]["hoshibiyori"]["commit"] = read_json(HOSHI / "stars.json")["commit"]      # 出力に入っている実物の commit
        hp = read_json(art / "proposals" / "hoshibiyori.json")
        hp["agent"]["commit"] = run["agents"]["hoshibiyori"]["commit"]
        hp["diagnostics"]["runtime_s"] = 0.0
        write_json(art / "proposals" / "hoshibiyori.json", hp)
        run["agents"]["hoshibiyori"]["runtime_s"] = 0.0                       # 偽のホシビヨリの秒(作るたびに変わるので 0 にする)
        for m in run["agents"]["hoshibiyori"]["modes"]:
            m["runtime_s"] = 0.0
        run["agents"]["yamabiyori"] = {k: real.get(k) for k in shelf.ENTRY_KEYS} | {"status": "ok", "reason": None, "requests": real["requests"],
                                                                                   "runtime_s": real["runtime_s"]}
        run["agents"]["yamabiyori"] = {k: v for k, v in run["agents"]["yamabiyori"].items() if v is not None or k in ("reason", "retry_stop", "limit")}
        run["requested_agents"] = ["yamabiyori", "hoshibiyori"]
        run["yamabiyori_ref"] = "main"
        write_json(art / "run.json", run)
        write_json(art / "yamabiyori" / "explore.json", explore)
        write_json(art / "yamabiyori" / "mountains.json", mountains)
        write_json(art / "proposals" / "yamabiyori.json", prop)
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
