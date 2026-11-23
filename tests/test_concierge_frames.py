"""段階 2 の仕上げ(第 1・2 部): 主役の枠と見送りの枠・同点の並びと順位・比べた結果・危険信号の注記・予報の範囲の外の日。通信しない。
見本の棚は 3 座しかないので、見本の提案を写した作り物の山の日(値は本物の予報ではない)を足して確かめる。"""
import copy
import unittest
from pathlib import Path
from unittest import mock

from concierge_helpers import base_with_shelf, build, edit_json, fact

from concierge import brief as B
from concierge import fallback as F
from concierge import verify as V
from concierge.common import brief_schema_errors, config

DAY = "2026-10-17"
# 出発地(横浜)から近い順に並べた山の ID(直線距離。ID の順とは違う)
NEAR = ["m027", "m029", "m023", "m022", "m026", "m024", "m030", "m025", "m031", "m032", "m017", "m016"]


def synthetic(rows, day=DAY):
    """作り物: 見本の提案(m002・day)を写して、rows = [(山の ID, 点数, {危険信号: 段階}, 稜線の風)] の山の日に置き換える(day のほかの山は消す)。"""
    def fn(shelf_dir):
        def f(d):
            src = next(p for p in d["proposals"] if p["id"] == f"yamabiyori:explore:{day}:m002")
            d["proposals"] = [p for p in d["proposals"] if not p["time_window"]["start"].startswith(day)]
            for mid, score, hz, wind in rows:
                p = copy.deepcopy(src)
                p["id"] = f"yamabiyori:explore:{day}:{mid}"
                p["place"]["site_ref"] = f"yamabiyori:{mid}"
                p["suitability"]["score"]["value"] = score
                p["constraints"] = [{"kind": "hazard", "hazard": k, "level": lv, "text": f"{k}:{lv}", "hard": lv in ("警戒", "危険")}
                                    for k, lv in hz.items()]
                for e in p["evidence"]:
                    if e["metric"] == "ridge_wind_ms":
                        e["value"] = wind
                d["proposals"].append(p)
        edit_json(Path(shelf_dir) / "proposals" / "yamabiyori.json", f)
    return fn


def sat(doc, by=None):
    return [f for f in doc["facts"] if f["date"] == DAY and (by is None or f["selected_by"] == by)]


class Frames(unittest.TestCase):
    def doc(self, rows, **kw):
        doc = build(base_with_shelf(self, edit=synthetic(rows)), when=DAY, **kw)
        self.assertEqual(brief_schema_errors(doc), [])
        return doc

    def test_main_frame_is_filled_even_when_the_top_scores_are_all_dangerous(self):
        danger = [(m, 100.0, {"wind": "危険"}, 20.0) for m in NEAR[:10]]
        mild = [(m, 80.0, {"cold": "注意"}, 5.0) for m in ("m001", "m003", "m033", "m050", "m051", "m057", "m058", "m061", "m062", "m063")]
        doc = self.doc(danger + mild)
        c = config()["concierge"]["brief"]
        self.assertEqual((c["top_per_day"], c["skip_per_day"]), (8, 3))
        self.assertEqual(len(sat(doc, "top")), 8)
        self.assertTrue(all(f["main_ok"] for f in sat(doc, "top")))
        self.assertEqual([f["mountain_id"] for f in sat(doc, "skip")], NEAR[:3])       # 同点は近い順
        self.assertTrue(all(not f["main_ok"] and f["main_ng"] == ["hazard_hard"] for f in sat(doc, "skip")))
        x = doc["candidates"][0]
        self.assertEqual((x["counts"]["outside_top"], x["counts"]["outside_skip"], x["counts"]["score_only"]), (2, 7, 0))
        self.assertEqual((len(x["outside_top_names"]), len(x["outside_skip_names"])), (2, 7))
        r = V.check(F.draft(doc), doc)
        self.assertTrue(r["ok"], r["errors"])

    def test_no_main_mountain_still_shows_the_skip_frame(self):
        doc = self.doc([(m, 90.0, {"cold": "警戒"}, 9.0) for m in NEAR[:5]])
        self.assertEqual([f["selected_by"] for f in sat(doc)], ["skip"] * 3)
        self.assertEqual(doc["plans"], [])
        r = V.check(F.draft(doc), doc)
        self.assertTrue(r["ok"], r["errors"])
        self.assertTrue(r["final"].startswith("今回の対象の日には、条件のそろった山はありません。"))

    def test_ties_are_ordered_by_hazard_then_distance_then_id(self):
        doc = self.doc([("m001", 100.0, {}, 5.0),                                   # 遠いが、危険信号なし
                        ("m022", 100.0, {"cold": "注意", "wind": "注意"}, 4.0),      # 近いが、注意が 2 つ
                        ("m023", 100.0, {"cold": "注意"}, 4.0),
                        ("m027", 100.0, {"cold": "注意"}, 4.0),                      # m023 より近い(ID は後ろ)
                        ("m029", 99.0, {}, 4.0)])
        want = ["m001", "m027", "m023", "m022", "m029"]
        self.assertEqual([f["mountain_id"] for f in sat(doc, "top")], want)
        ids = {f["id"]: f["mountain_id"] for f in doc["facts"]}
        self.assertEqual([ids[p["main"]["fact"]] for p in doc["plans"]], want)        # 案の並びも同じ
        self.assertEqual([f["mountain_id"] for f in F.picks(doc)], want[:3])          # 控えの文も同じ

    def test_tied_ranks_are_the_same_rank_and_say_so(self):
        doc = self.doc([(m, 100.0, {}, 5.0) for m in NEAR[:4]] + [("m017", 100.0, {"wind": "危険"}, 20.0), ("m016", 95.0, {}, 5.0)])
        by = {f["mountain_id"]: f for f in sat(doc)}
        self.assertEqual([by[m]["day_rank"] for m in NEAR[:4] + ["m017", "m016"]], [1, 1, 1, 1, 1, 6])
        self.assertIn("1位(同点 5 座)", by["m027"]["say"])
        self.assertNotIn("1位", by["m027"]["say"])
        self.assertIn("6位", by["m016"]["say"])
        self.assertIn("1位(同点 5 座)", B.render_md(doc))

    def test_named_mountain_is_kept_outside_the_frames(self):
        cfg = B.config()
        cfg["concierge"]["brief"].update(top_per_day=1, skip_per_day=1)
        rows = [("m027", 100.0, {}, 5.0), ("m029", 99.0, {}, 5.0), ("m023", 98.0, {"wind": "危険"}, 20.0),
                ("m022", 97.0, {"wind": "危険"}, 20.0), ("m026", 60.0, {}, 5.0)]
        with mock.patch("concierge.brief.config", return_value=cfg):
            doc = self.doc(rows, mountains=["高尾山", "塔ノ岳", "鍋割山"])
        self.assertEqual([(f["mountain_id"], f["selected_by"], f["day_rank"]) for f in sat(doc)],
                         [("m027", "top", 1), ("m023", "skip", 3), ("m029", "named", 2), ("m022", "named", 4), ("m026", "named", None)])

    def test_main_ok_min_is_gone(self):
        self.assertNotIn("main_ok_min", config()["concierge"]["brief"])


class Comparisons(unittest.TestCase):
    def doc(self, rows):
        return build(base_with_shelf(self, edit=synthetic(rows)), when=DAY)

    def test_made_from_the_main_frame_only(self):
        doc = self.doc([("m029", 90.0, {}, 5.0), ("m023", 91.0, {}, 3.0), ("m027", 100.0, {"wind": "危険"}, 1.0)])
        self.assertEqual([(x["id"], x["kind"], x["mountain_id"]) for x in doc["comparisons"]],
                         [("C1", "ridge_wind_min", "m023"), ("C2", "nearest", "m029")])      # 見送りの枠の m027 のほうが近く、風も弱いが、比べない
        self.assertIn("主役の候補の中で稜線の風がいちばん弱い", doc["comparisons"][0]["say"])
        self.assertIn("主役の候補の中で横浜からいちばん近い", doc["comparisons"][1]["say"])

    def test_not_made_when_tied_or_alone(self):
        doc = self.doc([("m029", 90.0, {}, 3.0), ("m023", 91.0, {}, 3.0)])
        self.assertEqual([x["kind"] for x in doc["comparisons"]], ["nearest"])
        self.assertEqual(self.doc([("m029", 90.0, {}, 3.0)])["comparisons"], [])


class Lines(unittest.TestCase):
    def test_the_note_is_one_line_and_not_in_each_hazard_line(self):
        doc = build(base_with_shelf(self))
        note = doc["lines"]["hazard_note"]
        self.assertEqual(note["text"], "危険信号は、点数とは別に出る警告です。")
        self.assertTrue(doc["lines"]["hazards"])
        for h in doc["lines"]["hazards"]:
            self.assertNotIn("点数とは別", h["text"])
        self.assertEqual(F.draft(doc).count(note["text"]), 1)

    def test_no_note_when_no_mountain_has_a_hazard(self):
        doc = build(base_with_shelf(self, edit=synthetic([("m027", 90.0, {}, 5.0)])), when=DAY)
        self.assertIsNone(doc["lines"]["hazard_note"])
        self.assertTrue(V.check(F.draft(doc), doc)["ok"])

    def test_verify_wants_the_note_once_and_allows_twice(self):
        from test_concierge_answer import codes, good_draft
        doc = build(base_with_shelf(self))
        n = doc["lines"]["hazard_note"]
        line = f"{n['text']}[{n['id']}]\n"
        g = good_draft(doc)
        self.assertTrue(V.check(g, doc)["ok"])
        self.assertIn("hazard_note_missing", codes(V.check(g.replace(line, ""), doc)))
        r = V.check(g.replace(line, line + line), doc)
        self.assertTrue(r["ok"], r["errors"])

    def test_answer_name_of_cloud(self):
        doc = build(base_with_shelf(self))
        names = [v["name"] for v in fact(doc, "八ヶ岳", DAY)["values"]]
        self.assertIn("雲量", names)
        md = B.render_md(doc)
        self.assertNotIn("- 雲量(較正後)", md)
        self.assertIn("答えには「雲量」とだけ書く", md)
        self.assertNotIn("較正", F.draft(doc))

    def test_part_of_the_days_out_of_the_forecast_is_said_in_the_fallback_too(self):
        doc = build(base_with_shelf(self), when="2026-10-18..2026-10-20")              # 見本の棚は 10/19 まで
        g = [x for x in doc["gaps"] if x["kind"] == "day_not_in_forecast"]
        self.assertEqual([x["text"] for x in g], ["10月20日(火)の山の予報は、今回の予報の範囲にありません。"])
        self.assertTrue(doc["facts"])
        for compact in (False, True):
            r = V.check(F.draft(doc, compact=compact), doc)
            self.assertTrue(r["ok"], r["errors"])
            self.assertIn(g[0]["text"], r["final"])


if __name__ == "__main__":
    unittest.main()
