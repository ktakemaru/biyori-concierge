"""ホシビヨリの新しい項目(夜の中の順位 night_rank・見どころ highlights・地点の出どころ origin)への対応(段階 3 見どころ)。通信しない。

見本の棚は tests/fixtures/shelf_hl/(作り方は tests/make_highlights_fixture.py)。星はホシビヨリ main の実物(2026-11-27 09:06、主軸 146 地点)を
16 地点に減らしたもの、山は段階 3 の見本(2026-11-23 の実物)。古い形(1.2.0。新しい項目が無い)の確かめは段階 3 の見本 tests/fixtures/shelf_day/。
実物に無い種類(見どころが null の夜・流星群の夜・origin が viewpoint の地点・MSM の候補の夜)は、テストの中で作り物を足す(作り物と書く)。"""
import shutil
import unittest

from concierge_helpers import build, edit_json
from helpers import FIX, tmpdir

from collect import hoshibiyori as H
from collect.common import read_json, schema_errors
from concierge import stars as ST
from concierge.common import brief_schema_errors, parse_now

HL_FIX = FIX / "shelf_hl"
DAY_FIX = FIX / "shelf_day"
NOW = "2026-11-27T10:00:00+09:00"          # 星を取った 1 時間後(山は 2026-11-23 の実物なので古い予報)
Q = "土曜の夜に星を見たい。昼は何をするといい?"
STARS, BOTH = ["星空"], ["登山・ハイキング", "星空"]


def base_of(test, fix=HL_FIX, edit=None):
    base = tmpdir(test, "biyori-chl-")
    shutil.copytree(fix, base / "shelf")
    if edit:
        edit(base / "shelf")
    return base


def stars_edit(fn, modes=("stars",)):
    def edit(shelf_dir):
        for m in modes:
            edit_json(shelf_dir / "hoshibiyori" / f"{m}.json", fn)
    return edit


def make(test, when="2026-11-28", interest=STARS, edit=None, q=Q, fix=HL_FIX, **kw):
    return build(base_of(test, fix=fix, edit=edit), question=q, when=when, interest=interest, now=kw.pop("now", NOW), **kw)


def drop_night_rank(d):
    for r in d["requested_nights"]:
        for s in r["sites"]:
            s.pop("night_rank", None)


class NightRank(unittest.TestCase):
    """第 2 部: 聞かれた夜の順位で星の地点を並べる。"""

    def test_weekend_night_is_ordered_by_night_rank_not_distance(self):
        # 段階 3 の報告書の例と同じ形(2026-11-28・出発地 横浜。候補の上位の夜でない)。今までは出発地に近い三浦半島の海沿いが先頭だった
        doc = make(self)
        self.assertEqual(brief_schema_errors(doc), [])
        top = [f for f in doc["stars"]["facts"] if f["selected_by"] == "top"]
        self.assertTrue(all(f["rank"] is None for f in top))                   # 候補の夜でない
        nr = [f["night_rank"] for f in top]
        self.assertEqual(nr, sorted(nr))
        self.assertEqual(top[0]["name"], "日光白根山ロープウェイ山頂駅(日光市)")     # 見本の地点の中で、その夜の順位がいちばん上
        names = [f["name"] for f in doc["stars"]["facts"]]
        self.assertNotIn("城ヶ島（馬の背洞門）(三浦市)", names)                      # 出発地にいちばん近いが、その夜の順位は 26 位

    def test_without_night_rank_the_order_is_the_distance_as_before(self):
        doc = make(self, edit=stars_edit(drop_night_rank))
        top = [f for f in doc["stars"]["facts"] if f["selected_by"] == "top"]
        self.assertTrue(all("night_rank" not in f for f in doc["stars"]["facts"]))
        self.assertEqual(top[0]["name"], "城ヶ島（馬の背洞門）(三浦市)")
        self.assertEqual([f["distance_km"] for f in top], sorted(f["distance_km"] for f in top))

    def test_candidate_night_keeps_rank_first(self):
        doc = make(self, when="2026-12-06")
        top = [f for f in doc["stars"]["facts"] if f["selected_by"] == "top"]
        self.assertTrue(top and all(f["rank"] is not None for f in top))
        self.assertEqual([f["rank"] for f in top], sorted(f["rank"] for f in top))

    def test_rank_then_night_rank_then_distance(self):
        # 作り物の 3 地点: rank のある地点が先、rank が無い地点は night_rank、どちらも無い地点は距離
        f = lambda sid, rank, nr, km: {"group": "primary", "rank": rank, "site_id": sid, **({} if nr is None else {"night_rank": nr}), "km": km}
        xs = [f("a", None, None, 1.0), f("b", None, 3, 9.0), f("c", 7, 1, 50.0), f("d", None, 2, 99.0), f("e", 2, 9, 80.0)]
        self.assertEqual([x["site_id"] for x in sorted(xs, key=lambda x: ST.site_key(x, x["km"]))], ["e", "c", "d", "b", "a"])

    def test_night_rank_is_not_written_but_shown_as_not_to_write(self):
        from concierge import brief as B
        doc = make(self)
        f = next(f for f in doc["stars"]["facts"] if f.get("night_rank"))
        self.assertFalse(any(str(f["night_rank"]) == x for x in f["say"]))
        self.assertIn(f"その夜の中の順位 {f['night_rank']}(書かない)", B.render_md(doc))

    def test_old_output_facts_have_no_new_keys(self):
        doc = make(self, fix=DAY_FIX, now="2026-11-25T23:00:00+09:00")
        self.assertTrue(all("night_rank" not in f and "origin" not in f for f in doc["stars"]["facts"]))


class ProposalRank(unittest.TestCase):
    def natives(self, fix=FIX / "hoshibiyori_hl"):
        return {m: read_json(fix / f"{m}.json") for m in H.MODES}

    def convert(self, natives):
        now = parse_now(NOW)
        return H.convert(natives, now=now, fetched_at=now, agent_version="1.2.0", agent_commit="0" * 40)

    def test_night_rank_fills_the_rank_of_nights_without_candidates(self):
        n = self.natives()
        p = self.convert(n)
        self.assertEqual(schema_errors(p, "biyori-proposal"), [])
        x = next(x for x in p["proposals"] if x["place"]["name"] == "日光白根山ロープウェイ山頂駅(日光市)" and x["details"]["night_date"] == "2026-11-28")
        ev = {e["metric"]: e["value"] for e in x["evidence"]}
        self.assertEqual((ev["rank"], x["details"]["rank_kind"]), (2, "night"))
        self.assertIsNone(x["suitability"]["score"])                           # 山の点数と比べられる形にしない
        y = next(x for x in p["proposals"] if x["details"]["night_date"] == "2026-12-06")
        self.assertEqual(y["details"]["rank_kind"], "outlook")                 # 候補の夜は今までどおり rank

    def test_without_night_rank_the_rank_stays_null(self):
        n = self.natives()
        for m in H.MODES:
            drop_night_rank(n[m])
        p = self.convert(n)
        x = next(x for x in p["proposals"] if x["details"]["night_date"] == "2026-11-28")
        self.assertIsNone({e["metric"]: e["value"] for e in x["evidence"]}["rank"])
        self.assertIsNone(x["details"]["rank_kind"])

    def test_old_fixture_converts_as_before(self):
        old = self.natives(FIX / "hoshibiyori")
        p = self.convert(old)
        self.assertTrue(all(x["details"]["rank_kind"] in ("final", "outlook", None) for x in p["proposals"]))


if __name__ == "__main__":
    unittest.main()
