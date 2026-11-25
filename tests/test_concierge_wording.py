"""言い回しの直し(2026-11-25): 内部の言葉「主役の候補」・名指しで比べるときの座数の文・番号・差がわずかなときの文。通信しない。
棚は見本(3 座)に作り物の山の日を足したもの(値は本物の予報ではない)。"""
import copy
import unittest
from pathlib import Path

from concierge_helpers import base_with_shelf, build, edit_json, fact
from test_concierge_frames import synthetic

from concierge import fallback as F
from concierge import verify as V
from concierge.common import brief_schema_errors

DAY = "2026-10-17"


def peaks(values):
    """作り物: 山ごとの日中ピークの風速を入れる(synthetic のあとに使う)。"""
    def fn(shelf_dir):
        def f(d):
            for p in d["proposals"]:
                mid = p["place"]["site_ref"].split(":")[1]
                if p["time_window"]["start"].startswith(DAY) and mid in values:
                    e = next((x for x in p["evidence"] if x["metric"] == "day_peak_wind_ms"), None)
                    if e is None:
                        e = copy.deepcopy(p["evidence"][0])
                        e.update(metric="day_peak_wind_ms", unit="m/s")
                        p["evidence"].append(e)
                    e["value"] = values[mid]
        edit_json(Path(shelf_dir) / "proposals" / "yamabiyori.json", f)
    return fn


def full_coverage(shelf_dir):
    edit_json(Path(shelf_dir) / "manifest.json",
              lambda m: m["agents"]["yamabiyori"]["coverage"].update(pool_size=76, fetched=76, missing=0, total_mountains=76))


def both(*fns):
    def fn(d):
        for f in fns:
            f(d)
    return fn


ROWS = [("m026", 95.0, {"wind": "注意"}, 5.0), ("m029", 95.0, {}, 4.0)]
NAMES = ["鍋割山", "高尾山"]


class Wording(unittest.TestCase):
    def doc(self, peak, extra=None, **kw):
        fns = [synthetic(ROWS), peaks(peak)] + ([extra] if extra else [])
        d = build(base_with_shelf(self, edit=both(*fns)), when=DAY, mountains=kw.pop("mountains", NAMES), **kw)
        self.assertEqual(brief_schema_errors(d), [])
        return d

    def marks(self, doc):
        return fact(doc, "鍋割山", DAY)["id"], fact(doc, "高尾山", DAY)["id"], doc["named_gaps"][0]["id"]

    def check(self, doc, sentence, picks="なし"):
        L = doc["lines"]
        head = "\n".join(f"{L[k]['text']}[{L[k]['id']}]" for k in ("data_time", "coverage", "attribution"))
        return V.check(f"{sentence}\n{head}\n[おすすめ] {picks}", doc)

    def codes(self, r):
        return {e["code"] for e in r["errors"]}

    def test_internal_name_is_stopped(self):
        doc = self.doc({"m026": 8.1, "m029": 7.9})
        y = self.marks(doc)[1]
        self.assertIn("internal_word", self.codes(self.check(doc, f"高尾山は主役の候補の中で候補です。[{y}]")))
        self.assertNotIn("主役の候補", " ".join(" ".join(x["say"]) for x in doc["comparisons"]))

    def test_small_difference_is_in_the_brief(self):
        doc = self.doc({"m026": 8.1, "m029": 7.9})
        x = doc["named_gaps"][0]
        self.assertEqual((x["diff"], x["small"], x["hazard_differs"]), (0.2, True, True))
        self.assertIn("差はわずか", x["say"])
        a, b, c = self.marks(doc)
        self.assertNotIn("gap_unmarked", self.codes(self.check(doc, f"鍋割山と高尾山は、風速の差は 0.2 m/s で、差はわずかです。[{a}][{b}][{c}]")))

    def test_small_difference_without_mark_is_stopped(self):
        doc = self.doc({"m026": 8.1, "m029": 7.9})
        a, b, _ = self.marks(doc)
        self.assertIn("gap_unmarked", self.codes(self.check(doc, f"鍋割山と高尾山は、風の差はわずかです。[{a}][{b}]")))

    def test_big_difference_cannot_be_called_small(self):
        doc = self.doc({"m026": 12.0, "m029": 7.9})
        x = doc["named_gaps"][0]
        self.assertFalse(x["small"])
        self.assertNotIn("差はわずか", x["say"])
        a, b, c = self.marks(doc)
        self.assertIn("gap_mismatch", self.codes(self.check(doc, f"鍋割山と高尾山は、風の差はわずかです。[{a}][{b}][{c}]")))

    def test_limit_is_included(self):
        self.assertTrue(self.doc({"m026": 8.4, "m029": 7.9})["named_gaps"][0]["small"])
        self.assertFalse(self.doc({"m026": 8.5, "m029": 7.9})["named_gaps"][0]["small"])

    def test_no_gap_without_two_named_mountains(self):
        self.assertEqual(self.doc({"m026": 8.1, "m029": 7.9}, mountains=["鍋割山"])["named_gaps"], [])

    def test_coverage_is_short_only_when_complete_and_named(self):
        doc = self.doc({"m026": 8.1, "m029": 7.9}, extra=full_coverage)
        self.assertEqual(doc["lines"]["coverage"]["text"], "ヤマビヨリの 76 座すべての予報がそろっています。")
        one = self.doc({"m026": 8.1, "m029": 7.9}, extra=full_coverage, mountains=["鍋割山"])
        self.assertEqual(one["lines"]["coverage"]["text"], "山は、ヤマビヨリの 76 座のうち 76 座を調べた予報です。")
        partial = self.doc({"m026": 8.1, "m029": 7.9})                        # 見本の棚は 3 座だけ: 今までどおり伝える
        self.assertIn("76 座のうち 3 座", partial["lines"]["coverage"]["text"])

    def test_number_on_one_mountain_only_is_stopped(self):
        doc = self.doc({"m026": 8.1, "m029": 7.9})
        a, b, _ = self.marks(doc)
        one = f"1. 鍋割山は95点です。[{a}]\n高尾山は95点です。[{b}]"
        self.assertIn("number_lone", self.codes(self.check(doc, one)))
        two = f"1. 鍋割山は95点です。[{a}]\n2. 高尾山は95点です。[{b}]"
        self.assertNotIn("number_lone", self.codes(self.check(doc, two)))
        none = f"鍋割山は95点です。[{a}]\n高尾山は95点です。[{b}]"
        self.assertNotIn("number_lone", self.codes(self.check(doc, none)))

    def test_fallback_numbers_only_when_two_or_more(self):
        one = F.draft(build(base_with_shelf(self, edit=synthetic([("m029", 95.0, {}, 4.0)])), when=DAY))
        self.assertNotIn("1. ", one)
        self.assertIn("1. ", F.draft(self.doc({"m026": 8.1, "m029": 7.9})))

    def test_recommended_candidates_is_not_a_recommendation(self):
        """「おすすめの候補の中で」は、すすめた山の宣言を求めない。"""
        doc = self.doc({"m026": 8.1, "m029": 7.9})
        y = fact(doc, "高尾山", DAY)["id"]
        c = next(x["id"] for x in doc["comparisons"] if x["kind"] == "ridge_wind_min")
        r = self.check(doc, f"高尾山は、おすすめの候補の中で稜線の風がいちばん弱い見込みです。[{y}][{c}]")
        self.assertNotIn("pick_undeclared", self.codes(r))


if __name__ == "__main__":
    unittest.main()
