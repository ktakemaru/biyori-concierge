"""ホシビヨリの新しい項目(夜の中の順位 night_rank・見どころ highlights・地点の出どころ origin)への対応(段階 3 見どころ)。通信しない。

見本の棚は tests/fixtures/shelf_hl/(作り方は tests/make_highlights_fixture.py)。星はホシビヨリ main の実物(2026-11-27 09:06、主軸 146 地点)を
16 地点に減らしたもの、山は段階 3 の見本(2026-11-23 の実物)。古い形(1.2.0。新しい項目が無い)の確かめは段階 3 の見本 tests/fixtures/shelf_day/。
実物に無い種類(見どころが null の夜・流星群の夜・origin が viewpoint の地点・MSM の候補の夜)は、テストの中で作り物を足す(作り物と書く)。"""
import copy
import shutil
import unittest
from unittest import mock

from concierge_helpers import build, edit_json
from helpers import FIX, tmpdir

from collect import hoshibiyori as H
from collect.common import read_json, schema_errors
from concierge import fallback as F
from concierge import stars as ST
from concierge import verify as V
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


def hl_edit(fn):
    """作り物: 両方のモードの highlights を書き換える(実物に無い種類を確かめるため)。"""
    return stars_edit(fn, modes=("stars", "milkyway"))


def codes(r):
    return {e["code"] for e in r["errors"]}


class Highlights(unittest.TestCase):
    """第 3 部: 夜に見られる星(見どころ)。"""

    def test_facts_only_from_verified_members_and_linked_to_the_night_frame(self):
        doc = make(self)
        self.assertEqual(brief_schema_errors(doc), [])
        h = doc["stars"]["highlights"]
        native = read_json(HL_FIX / "hoshibiyori" / "stars.json")["highlights"]["by_night"]["2026-11-28"]
        ok = {m["name"] for s in native["slots"] for it in s["items"] for m in it["members"] if not m["coordinates_unverified"]}
        bad = {m["name"] for s in native["slots"] for it in s["items"] for m in it["members"] if m["coordinates_unverified"]}
        seen = {f["name"] for f in h["facts"] if f["kind"] == "star_highlight"}
        self.assertEqual(seen, ok)                                            # 書いてよい名前は members[] の、座標を照らした対象だけ
        self.assertFalse(seen & bad)
        self.assertTrue(set(h["unverified"]) >= bad - ok)
        self.assertEqual(h["unverified_count"], sum(1 for s in native["slots"] for it in s["items"] for m in it["members"] if m["coordinates_unverified"])
                         + sum(1 for x in native["not_visible"] if x["coordinates_unverified"]))
        self.assertIn("みなみのうお座", h["objects"])                          # 組の名前は一覧にあるが、事実にはしない
        self.assertNotIn("みなみのうお座", {f["name"] for f in h["facts"]})
        self.assertEqual([f["name"] for f in h["facts"] if f["kind"] == "star_hidden"], ["天の川銀河中心"])      # さそり座は未照合
        self.assertTrue(all(f["id"].startswith("H") for f in h["facts"]))
        frames = [fr for p in doc["plans"] for fr in p["frames"] if fr["kind"] == "stars" and fr["fact"]]
        self.assertTrue(frames and all(fr["highlights"] == [f["id"] for f in h["facts"]] for fr in frames))
        self.assertNotIn("no_star_objects", {g["kind"] for g in doc["gaps"]})
        self.assertEqual(doc["lines"]["star_basis"]["text"], "見られる星や惑星と時刻は、基準の地点・平らな地平線の目安(地形・雲は見ていない)です。")
        self.assertIn(ST.HL_RULES[0], doc["rules"])
        self.assertNotIn(ST.OBJECT_RULE_OLD, doc["rules"])

    def test_times_are_per_slot_and_after_midnight_has_the_next_day_mark(self):
        doc = make(self)
        sat = next(f for f in doc["stars"]["highlights"]["facts"] if f["name"] == "土星")
        self.assertEqual([sl["label"] for sl in sat["slots"]], ["宵", "夜半"])
        self.assertIn("18:03〜22:00", sat["say"])                             # 宵(時間帯で切られた時刻。出・入りの時刻ではない)
        self.assertIn("22:00〜翌0:30", sat["say"])                            # 夜半(0 時を過ぎたら「翌」)
        self.assertIn("高度約56度", sat["say"])

    def test_no_highlights_in_the_output_is_the_same_as_before(self):
        for name, fn in (("key_absent", lambda d: d.pop("highlights")), ("null", lambda d: d.update(highlights=None))):
            with self.subTest(name):
                doc = make(self, edit=hl_edit(fn))
                self.assertNotIn("highlights", doc["stars"])
                self.assertIn("no_star_objects", {g["kind"] for g in doc["gaps"]})
                self.assertNotIn("star_basis", doc["lines"])
                self.assertEqual(doc["rules"][-len(ST.RULES):], ST.RULES)
                self.assertTrue(all("highlights" not in fr for p in doc["plans"] for fr in p["frames"]))

    def test_null_or_missing_night_keeps_the_old_sentence(self):
        for name, fn in (("null_night", lambda d: d["highlights"]["by_night"].update({"2026-11-28": None})),      # 作り物(実物に null の夜は無い)
                         ("missing_night", lambda d: d["highlights"]["by_night"].pop("2026-11-28"))):
            with self.subTest(name):
                doc = make(self, edit=hl_edit(fn))
                h = doc["stars"]["highlights"]
                self.assertEqual((h["facts"], h["null_nights"]), ([], ["11月28日(土)の夜"]))
                g = next(g for g in doc["gaps"] if g["kind"] == "no_star_objects")
                self.assertEqual(g["text"], "どの星や惑星が見えるかは、この予報に含まれていません。")
                self.assertNotIn("star_basis", doc["lines"])

    def test_weekend_with_one_null_night_says_which_night(self):
        doc = make(self, when="今週末", interest=BOTH, edit=hl_edit(lambda d: d["highlights"]["by_night"].update({"2026-11-28": None})))
        r = V.check(F.draft(doc), doc)
        self.assertTrue(r["ok"], r["errors"])
        g = next(g for g in doc["gaps"] if g["kind"] == "no_star_objects")
        self.assertEqual(g["text"], "11月28日(土)の夜は、どの星や惑星が見えるかが、この予報に含まれていません。")
        self.assertTrue(doc["stars"]["highlights"]["facts"])
        self.assertEqual({f["date"] for f in doc["stars"]["highlights"]["facts"]}, {"2026-11-29"})

    def test_night_without_a_star_site_has_no_highlights(self):
        doc = make(self, when="2026-12-04")                                  # 条件を通った地点が 0 の夜(実物)
        self.assertEqual(doc["stars"]["highlights"]["facts"], [])
        self.assertIn("no_star_objects", {g["kind"] for g in doc["gaps"]})

    def test_shower_only_on_its_peak_night(self):
        # 作り物: ふたご座流星群の極大の夜を 11/28 に書き換える(実物の極大の夜は 12/14 で、聞かれた夜の外)
        def fn(d):
            sh = d["highlights"]["showers"][0]
            sh.update(night_date="2026-11-28", peak_time="2026-11-28T22:49:22+09:00", radiant_start="2026-11-28T20:05:02+09:00",
                      radiant_end="2026-11-29T05:13:39+09:00")
        doc = make(self, edit=hl_edit(fn))
        m = doc["stars"]["highlights"]["showers"]
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["id"], "M1")
        self.assertIn("1時間あたり150", m[0]["say"])
        x = doc["lines"]["star_showers"][0]
        self.assertEqual(x["text"], "ふたご座流星群の出現数は、例年の目安(理想の条件での1時間あたりの出現数。その年の予報ではない)です。"
                                    "理想の条件での目安で、実際に見える数はこれより少ない。突発的な増減は予測できない。")
        self.assertEqual(make(self, when="2026-11-29", edit=hl_edit(fn))["stars"]["highlights"]["showers"], [])
        self.assertEqual(make(self)["stars"]["highlights"]["showers"], [])     # 実物のまま(極大は聞かれた夜の外)


class HighlightVerify(unittest.TestCase):
    def setUp(self):
        self.doc = make(self)
        self.good = F.draft(self.doc)
        r = V.check(self.good, self.doc)
        self.assertTrue(r["ok"], r["errors"])

    def h(self, name):
        return next(f for f in self.doc["stars"]["highlights"]["facts"] if f["name"] == name)

    def check_body(self, add, drop_basis=False):
        L = self.doc["lines"]
        t = self.good
        if drop_basis:
            t = t.replace(f"{L['star_basis']['text']}[{L['star_basis']['id']}]\n", "")
        t = t.replace("\n\n", f"\n{add}\n\n", 1) if add else t
        return V.check(t, self.doc)

    def test_fallback_has_names_basis_and_passes(self):
        self.assertIn(self.doc["lines"]["star_basis"]["text"], self.good)
        self.assertIn("土星", self.good)

    def test_written_highlight_with_time(self):
        f = self.h("土星")
        r = self.check_body(f"28日(土)の夜は、宵の18:03〜22:00に土星が見られる目安です。[{f['id']}]")
        self.assertTrue(r["ok"], r["errors"])

    def test_wrong_time_is_stopped(self):
        f = self.h("土星")
        self.assertIn("time_mismatch", codes(self.check_body(f"28日(土)の夜は、宵の18:10〜22:00に土星が見られる目安です。[{f['id']}]")))

    def test_names_not_in_the_facts_are_stopped(self):
        f = self.h("土星")
        for w in ("ベガ", "みなみのうお座", "さそり座", "オリオン大星雲", "しし座流星群", "北極星"):
            with self.subTest(w):
                self.assertIn("star_object", codes(self.check_body(f"28日(土)の夜は、宵に土星と{w}が見られます。[{f['id']}]")))

    def test_name_without_its_mark_is_stopped(self):
        sat, jup = self.h("土星"), self.h("木星")
        self.assertIn("star_object", codes(self.check_body(f"28日(土)の夜は、夜半に土星と木星が見られます。[{sat['id']}]")))
        self.assertTrue(self.check_body(f"28日(土)の夜は、夜半に土星と木星が見られます。[{sat['id']}][{jup['id']}]")["ok"])

    def test_basis_line_is_required(self):
        f = self.h("土星")
        r = self.check_body(f"28日(土)の夜は、宵に土星が見られます。[{f['id']}]", drop_basis=True)
        self.assertIn("line_missing", codes(r))

    def test_not_visible_only_for_the_hidden_fact(self):
        sat, mw = self.h("土星"), self.h("天の川銀河中心")
        self.assertIn("highlight_not_visible", codes(self.check_body(f"28日(土)の夜の明け方は、土星は見えません。[{sat['id']}]")))
        self.assertTrue(self.check_body(f"28日(土)の夜は、天の川銀河中心は今の時期は見えません。[{mw['id']}]")["ok"])
        self.assertIn("highlight_hidden", codes(self.check_body(f"28日(土)の夜は、天の川銀河中心が見られます。[{mw['id']}]")))

    def test_moon_and_clouds_are_not_mixed(self):
        f = self.h("土星")
        self.assertIn("highlight_mixed", codes(self.check_body(f"28日(土)の夜は、晴れていれば宵に土星が見られます。[{f['id']}]")))
        self.assertIn("highlight_mixed", codes(self.check_body(f"28日(土)の夜は、月の無い時間帯に土星が見られます。[{f['id']}]")))

    def test_slot_must_be_a_slot_of_the_marked_object(self):
        sat, sub = self.h("土星"), self.h("すばる")
        self.assertIn("highlight_slot", codes(self.check_body(f"28日(土)の夜の明け方に土星が見られます。[{sat['id']}]")))      # 土星は宵・夜半だけ
        self.assertIn("highlight_slot", codes(self.check_body(f"28日(土)の夜は、宵に土星とすばるが見られます。[{sat['id']}][{sub['id']}]")))
        self.assertTrue(self.check_body(f"28日(土)の夜は、宵に土星、夜半にすばるが見られます。[{sat['id']}][{sub['id']}]")["ok"])

    def test_slot_written_as_date_and_midnight_is_stopped(self):
        f = self.h("木星")
        self.assertIn("night_label", codes(self.check_body(f"28日(土)の夜半に木星が見られます。[{f['id']}]")))

    def test_highlight_of_a_night_without_a_site_is_stopped(self):
        doc = make(self, when="2026-12-04")
        good = F.draft(doc)
        self.assertTrue(V.check(good, doc)["ok"])
        bad = good.replace("\n\n", "\n12月4日(金)の夜は、宵に土星が見られます。[S001]\n\n", 1)
        self.assertTrue({"star_object", "unknown_mark"} & codes(V.check(bad, doc)))

    def test_old_brief_still_stops_star_names(self):
        old = make(self, fix=DAY_FIX, now="2026-11-25T23:00:00+09:00")
        good = F.draft(old)
        self.assertTrue(V.check(good, old)["ok"])
        s = old["stars"]["facts"][0]
        bad = good.replace("\n\n", f"\n{s['label']}は、土星が見られます。[{s['id']}]\n\n", 1)
        self.assertIn("star_object", codes(V.check(bad, old)))

    def test_shower_needs_its_line(self):
        def fn(d):
            d["highlights"]["showers"][0].update(night_date="2026-11-28", radiant_start="2026-11-28T20:05:02+09:00",
                                                 radiant_end="2026-11-29T05:13:39+09:00")      # 作り物(実物の極大の夜は 12/14)
        doc = make(self, edit=hl_edit(fn))
        good = F.draft(doc)
        r = V.check(good, doc)
        self.assertTrue(r["ok"], r["errors"])
        x = doc["lines"]["star_showers"][0]
        self.assertIn(x["text"], good)
        m = doc["stars"]["highlights"]["showers"][0]
        add = f"28日(土)の夜は、ふたご座流星群が1時間あたり150見られます。[{m['id']}]"
        no_line = good.replace(f"{x['text']}[{x['id']}]", "").replace("\n\n", f"\n{add}\n\n", 1)
        self.assertIn("line_missing", codes(V.check(no_line, doc)))
        unmarked = good.replace("\n\n", "\n28日(土)の夜は、ふたご座流星群が1時間あたり150見られます。\n\n", 1)
        self.assertTrue(codes(V.check(unmarked, doc)) & {"star_object", "number_unmarked"})

    def test_fallback_for_many_cases_passes_and_fits(self):
        base = base_of(self)
        for when in ("今週末", "2026-11-28", "2026-11-27..2026-12-01", "2026-12-06", "来週末"):
            for it in (STARS, BOTH):
                with self.subTest(when=when, it=it):
                    d = build(base, question=Q, when=when, interest=it, now=NOW)
                    r = V.check(F.draft(d), d)
                    if codes(r) == {"too_long"}:
                        r = V.check(F.draft(d, compact=True), d)
                    self.assertTrue(r["ok"], r["errors"])
                    self.assertLessEqual(len(r["final"]), 2000)



def odbl_on(test):
    """config.yaml の concierge.stars.odbl_by_origin を、このテストのあいだだけ true にする(既定は false。決めてほしいこと 5)。"""
    from concierge import brief as B
    from concierge.common import config
    c = copy.deepcopy(config())
    c["concierge"]["stars"]["odbl_by_origin"] = True
    p = mock.patch.object(B, "config", return_value=c)
    p.start()
    test.addCleanup(p.stop)


class OdblDefault(unittest.TestCase):
    def test_default_keeps_odbl_always(self):
        from concierge.common import config
        self.assertIs(config()["concierge"]["stars"]["odbl_by_origin"], False)
        doc = make(self)
        self.assertNotIn("star_attribution_plain", doc["lines"])
        self.assertNotIn(ST.ODBL_RULE, doc["rules"])
        good = F.draft(doc)
        self.assertIn(doc["lines"]["star_attribution"]["text"], good)
        self.assertTrue(V.check(good, doc)["ok"])


class Odbl(unittest.TestCase):
    """第 4 部: ODbL の表示は、OSM 由来の地点を答えに使ったときだけ(odbl_by_origin を true にしたとき)。"""

    def setUp(self):
        odbl_on(self)

    def test_plain_line_only_with_origin(self):
        new = make(self)
        self.assertNotIn("OpenStreetMap", new["lines"]["star_attribution_plain"]["text"])
        self.assertIn("OpenStreetMap", new["lines"]["star_attribution"]["text"])
        old = make(self, fix=DAY_FIX, now="2026-11-25T23:00:00+09:00")
        self.assertNotIn("star_attribution_plain", old["lines"])

    def test_answer_without_osm_sites_may_drop_odbl(self):
        doc = make(self)
        L = doc["lines"]
        good = F.draft(doc)
        shown = {f["id"] for f in doc["stars"]["facts"] if f"[{f['id']}]" in good}
        osm = {f["id"] for f in doc["stars"]["facts"] if ST.is_osm(f)}
        self.assertTrue(V.check(good, doc)["ok"])
        self.assertEqual(L["star_attribution_plain"]["text"] in good, not (shown & osm))
        if not shown & osm:                                                   # ODbL のある文でもよい(付けすぎは止めない)
            r = V.check(good.replace(L["star_attribution_plain"]["text"] + f"[{L['star_attribution_plain']['id']}]",
                                     L["star_attribution"]["text"] + f"[{L['star_attribution']['id']}]"), doc)
            self.assertTrue(r["ok"], r["errors"])

    def test_osm_site_needs_odbl(self):
        doc = make(self)
        L = doc["lines"]
        s = next(f for f in doc["stars"]["facts"] if f.get("origin") == "curated+viewpoint")
        self.assertTrue(ST.is_osm(s))
        good = F.draft(doc)
        t = good.replace(L["star_attribution"]["text"] + f"[{L['star_attribution']['id']}]",
                         L["star_attribution_plain"]["text"] + f"[{L['star_attribution_plain']['id']}]")
        t = t.replace("\n\n", f"\n{s['label']}は、{s['name']}も星の候補です。[{s['id']}]\n\n", 1)
        self.assertIn("line_missing", codes(V.check(t, doc)))

    def test_viewpoint_and_missing_origin_are_osm(self):
        # 作り物: 実物(主軸 146 地点)に viewpoint の地点は無い
        self.assertTrue(ST.is_osm({"origin": "viewpoint"}))
        self.assertTrue(ST.is_osm({}))
        self.assertFalse(ST.is_osm({"origin": "curated"}))
        self.assertFalse(ST.is_osm({"origin": "curated_external"}))


class VoiceExamples(unittest.TestCase):
    """docs/answer-voice.md 7 章の見どころの手本が、見本の資料で照合に通る(山の時点だけを書き換えた作り物)。"""

    def test_highlight_examples_pass(self):
        from helpers import ROOT
        text = (ROOT / "docs" / "answer-voice.md").read_text(encoding="utf-8")

        def fresh(fn=None):
            def edit(shelf_dir):
                edit_json(shelf_dir / "manifest.json", lambda m: m["agents"]["yamabiyori"].update(data_time="2026-11-27T04:53:19+09:00"))
                if fn:
                    for m in ("stars", "milkyway"):
                        edit_json(shelf_dir / "hoshibiyori" / f"{m}.json", fn)
            return edit
        null28 = lambda d: d["highlights"]["by_night"].update({"2026-11-28": None})      # 作り物(実物に null の夜は無い)
        for head, interest, edit in (("### 山と星と見どころがそろった日の手本", BOTH, fresh()), ("### 見どころが無い夜の手本", STARS, fresh(null28))):
            with self.subTest(head):
                d = make(self, interest=interest, edit=edit)
                r = V.check(text.split(head, 1)[1].split("```", 2)[1].strip("\n") + "\n", d)
                self.assertTrue(r["ok"], r["errors"])


if __name__ == "__main__":
    unittest.main()
