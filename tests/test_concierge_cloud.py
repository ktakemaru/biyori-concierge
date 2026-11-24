"""生の雲量が 0 % の山の書き方(利用者の決定 2026-11-25): 資料の印・書いてよい表記・照合・控えの文・Stop フック。通信しない。
棚は見本(3 座)に作り物の山の日を足したもの(値は本物の予報ではない)。"""
import unittest
from pathlib import Path

from concierge_helpers import base_with_shelf, build, edit_json, fact
from test_concierge_frames import synthetic
from test_concierge_wording import both

from concierge import brief as B
from concierge import fallback as F
from concierge import stop_hook as SH
from concierge import verify as V
from concierge.common import brief_schema_errors, dump_json, write_text

DAY = "2026-10-17"
ROWS = [("m026", 95.0, {}, 5.0), ("m029", 95.0, {}, 4.0)]      # 鍋割山・高尾山
NAMES = ["鍋割山", "高尾山"]
STALE_NOW = "2026-10-16T08:00:00+09:00"


def clouds(values):
    return clouds_on(DAY, values)


def clouds_on(day, values):
    """作り物: 山ごとの (補正後の雲量, 生の雲量)。生が None なら値を消す。"""
    def fn(shelf_dir):
        def f(d):
            for p in d["proposals"]:
                mid = p["place"]["site_ref"].split(":")[1]
                if not p["time_window"]["start"].startswith(day) or mid not in values:
                    continue
                cal, raw = values[mid]
                p["evidence"] = [e for e in p["evidence"] if not (e["metric"] == "cloud_pct_raw" and raw is None)]
                for e in p["evidence"]:
                    if e["metric"] == "cloud_pct":
                        e["value"] = cal
                    elif e["metric"] == "cloud_pct_raw":
                        e["value"] = raw
        edit_json(Path(shelf_dir) / "proposals" / "yamabiyori.json", f)
    return fn


class Cloud(unittest.TestCase):
    def doc(self, nabe, takao, rows=ROWS, **kw):
        self.base = base_with_shelf(self, edit=both(synthetic(rows), clouds({"m026": nabe, "m029": takao})))
        d = build(self.base, when=DAY, mountains=NAMES, **kw)
        self.assertEqual(brief_schema_errors(d), [])
        self.a, self.b = fact(d, "鍋割山", DAY), fact(d, "高尾山", DAY)
        self.ma, self.mb = f"[{self.a['id']}]", f"[{self.b['id']}]"
        return d

    def both_clear(self, **kw):
        return self.doc((18.6, 0.0), (18.6, 0.0), **kw)

    def one_clear(self, **kw):
        return self.doc((18.6, 0.0), (36.9, 3.5), **kw)

    def errs(self, doc, sentence):
        L = doc["lines"]
        head = "\n".join(f"{L[k]['text']}[{L[k]['id']}]" for k in ("data_time", "coverage", "attribution"))
        return {e["code"] for e in V.check(f"{sentence}\n{head}\n[おすすめ] なし", doc)["errors"]}

    def ok(self, doc, sentence):
        self.assertEqual(self.errs(doc, sentence), set(), sentence)

    # -- 資料 --
    def test_mark_in_the_brief(self):
        doc = self.one_clear()
        self.assertIs(self.a["cloud_clear"], True)
        self.assertIs(self.b["cloud_clear"], False)
        self.assertNotIn("18.6 %", self.a["say"])
        self.assertNotIn("約19 %", self.a["say"])
        self.assertIn("雲はほとんど無い予報", self.a["say"])
        self.assertIn("36.9 %", self.b["say"])
        md = B.render_md(doc)
        self.assertNotIn("18.6", md)
        self.assertIn("雲量: 雲はほとんど無い予報", md)
        self.assertNotIn("予報そのまま", md)
        self.assertFalse([v for f in doc["facts"] for v in f["values"] if v["key"] == "cloud_pct_raw"])
        self.assertTrue([r for r in doc["rules"] if "雲はほとんど無い" in r])

    def test_no_mark_when_raw_is_not_zero_or_missing(self):
        for raw in (0.1, 3.5, 100, None):
            with self.subTest(raw=raw):
                doc = self.doc((18.6, raw), (18.6, raw))
                self.assertIs(self.a["cloud_clear"], False)
                self.assertIn("18.6 %", self.a["say"])
                self.assertFalse([r for r in doc["rules"] if "雲の印" in r])
                self.ok(doc, f"鍋割山の雲量は18.6 %の見込みです。{self.ma}")

    # -- 照合 --
    def test_number_is_stopped_on_a_marked_mountain(self):
        doc = self.both_clear()
        for bad in ("鍋割山の雲量は18.6 %の見込みです。", "鍋割山の雲量は約19 %です。", "鍋割山の雲量は、18.6 %です。", "鍋割山は、18.6 %の雲量です。",
                    "鍋割山の雲量は0 %です。", "鍋割山は、雲が2割ほどの見込みです。", "鍋割山は、雲が二割ほどの見込みです。"):
            with self.subTest(bad):
                self.assertIn("cloud_number", self.errs(doc, bad + self.ma))
        self.assertIn("cloud_number", self.errs(doc, f"鍋割山と高尾山の雲量は、どちらも18.6 %です。{self.ma}{self.mb}"))

    def test_words_pass_on_a_marked_mountain(self):
        doc = self.both_clear()
        for good in ("鍋割山は、雲はほとんど無い予報です。", "雲はほとんど無い予報です。", "鍋割山は稜線風速が5 m/sで、雲はほとんどない見込みです。",
                     "雲はほとんど無い予報で雨天割合は0 %の見込みです。"):
            with self.subTest(good):
                s = self.errs(doc, good + self.ma)
                self.assertFalse({x for x in s if x.startswith("cloud_")}, s)
        self.ok(doc, f"鍋割山は、雲はほとんど無い予報です。{self.ma}")

    def test_both_marked_can_be_said_to_have_no_difference(self):
        doc = self.both_clear()
        self.ok(doc, f"どちらも雲はほとんど無い予報で、差がつきません。{self.ma}{self.mb}")
        self.ok(doc, f"鍋割山と高尾山は、どちらも雲はほとんど無い予報で、差がつきません。{self.ma}{self.mb}")
        self.ok(doc, f"鍋割山も高尾山も稜線の風は弱めで、どちらも雲はほとんどない予報なので、差がつきません。{self.ma}{self.mb}")

    def test_only_one_marked(self):
        doc = self.one_clear()
        self.ok(doc, f"鍋割山は雲はほとんど無い予報で、高尾山は雲量が36.9 %の見込みです。{self.ma}{self.mb}")
        self.ok(doc, f"雲は、高尾山が36.9 %、鍋割山はほとんど無い予報です。{self.ma}{self.mb}")
        self.assertIn("cloud_mismatch", self.errs(doc, f"どちらも雲はほとんど無い予報で、差がつきません。{self.ma}{self.mb}"))
        self.assertIn("cloud_mismatch", self.errs(doc, f"高尾山は、雲はほとんど無い予報です。{self.mb}"))
        self.assertIn("cloud_number", self.errs(doc, f"鍋割山の雲量は36.9 %です。{self.ma}{self.mb}"))
        self.assertIn("cloud_number", self.errs(doc, f"雲量は18.6 %と36.9 %です。{self.ma}{self.mb}"))
        self.ok(doc, f"高尾山の雲量は36.9 %です。{self.mb}")

    def test_same_corrected_number_belongs_to_the_mountain_in_the_clause(self):
        """印の無い山が同じ 18.6 % のとき: その山の数字は書けるが、印の付いた山の数字としては書けない。"""
        doc = self.doc((18.6, 0.0), (18.6, 0.4))
        self.ok(doc, f"高尾山の雲量は18.6 %で、鍋割山は、雲はほとんど無い予報です。{self.ma}{self.mb}")
        self.assertIn("cloud_number", self.errs(doc, f"鍋割山の雲量は18.6 %です。{self.ma}{self.mb}"))
        self.assertIn("cloud_number", self.errs(doc, f"鍋割山と高尾山の雲量は18.6 %です。{self.ma}{self.mb}"))

    def test_assertions_are_stopped(self):
        doc = self.both_clear()
        for bad in ("鍋割山は快晴の予報です。", "鍋割山は快晴です。", "鍋割山は、雲ひとつない予報です。", "鍋割山は、雲一つ無い空の見込みです。", "鍋割山は、雲がまったくない予報です。"):
            with self.subTest(bad):
                self.assertIn("cloud_assertion", self.errs(doc, bad + self.ma))

    def test_almost_none_is_not_read_as_a_vague_count_of_hazards(self):
        doc = self.both_clear(rows=[("m026", 95.0, {"wind": "注意"}, 5.0), ("m029", 95.0, {}, 4.0)])
        s = self.errs(doc, f"鍋割山は強風注意が出ていますが、雲はほとんど無い予報です。{self.ma}")
        self.assertNotIn("hazard_vague", s)
        self.assertIn("hazard_vague", self.errs(doc, f"ほとんどの山に強風注意が出ています。{self.ma}"))
        self.assertIn("hazard_vague", self.errs(doc, f"雷雲はほとんど無い見込みで、強風注意です。{self.ma}"))

    def test_almost_none_is_not_read_as_a_small_wind_gap(self):
        doc = self.both_clear()
        s = self.errs(doc, f"鍋割山と高尾山は稜線の風に差があり、雲はほとんどない予報です。{self.ma}{self.mb}")
        self.assertNotIn("gap_unmarked", s)

    # -- 控えの文 --
    def test_fallback_uses_words_and_passes(self):
        for make, has in ((self.both_clear, False), (self.one_clear, True)):
            for kw in ({}, {"now": STALE_NOW}):
                with self.subTest(has=has, kw=kw):
                    doc = make(**kw)
                    d = F.draft(doc)
                    r = V.check(d, doc)
                    self.assertTrue(r["ok"], r["errors"])
                    self.assertNotIn("18.6", d)
                    self.assertIn("雲はほとんど無い予報です。", r["final"])
                    self.assertEqual("雲量は36.9 %" in r["final"], has)
        doc = self.doc((18.6, None), (36.9, 3.5))
        self.assertIn("雲量は18.6 %", F.draft(doc))
        self.assertTrue(V.check(F.draft(doc), doc)["ok"])

    def test_old_brief_without_the_mark_is_read_as_before(self):
        doc = self.doc((18.6, 0.4), (36.9, 3.5))
        for f in doc["facts"]:
            f.pop("cloud_clear")
        self.ok(doc, f"鍋割山の雲量は18.6 %です。{self.ma}")

    # -- Stop フック --
    def test_stop_hook(self):
        doc = self.one_clear()
        c, bid, base = SH.cfg(), doc["id"], self.base
        write_text(base / "briefs" / f"{bid}.json", dump_json(doc))
        run = {"name": "Bash", "input": {"command": "python -X utf8 -m concierge brief --question x"}, "result": f"{bid}\n"}
        done = {"name": "Bash", "input": {"command": f"python -X utf8 -m concierge verify /tmp/d.txt --brief {bid}"}, "result": "ok"}
        turn = {"prompt": "どっちがいい?", "key": "k", "calls": [run, done]}

        def why(text):
            write_text(base / "last_answer.json", dump_json({"brief": bid, "at": STALE_NOW, "text": text}))
            return SH.decide(text, turn, base, c)["why"]
        self.assertEqual(why("鍋割山の雲量は18.6 %の見込みです。"), "cloud")
        self.assertEqual(why("鍋割山は95点です。雲量は18.6 %の見込みです。"), "cloud")
        self.assertEqual(why("鍋割山は快晴の予報です。"), "cloud")
        self.assertEqual(why("鍋割山は95点です。雲はほとんど無い予報です。"), "ok")
        self.assertEqual(why("高尾山の雲量は36.9 %の見込みです。"), "ok")
        self.assertEqual(why("鍋割山は雲はほとんど無い予報で、高尾山は雲量が36.9 %の見込みです。"), "ok")
        self.assertEqual(why("雲量は18.6 %の見込みです。"), "ok")                # どの山のことか分からない(迷う場合は通す。verify が先に止める)
        self.assertIn("cloud", c["reasons"])
        self.assertEqual(why(V.check(F.draft(doc), doc)["final"]), "ok")        # 控えの文は止めない


    def test_stop_hook_does_not_read_the_other_days_brief(self):
        """1 回に資料が 2 つ(印のある日と無い日): もう一方の日の数字を止めない。"""
        base = base_with_shelf(self, edit=both(synthetic(ROWS), clouds({"m026": (18.6, 0.0), "m029": (18.6, 0.0)}),
                                              synthetic(ROWS, day="2026-10-18"), clouds_on("2026-10-18", {"m026": (36.9, 3.5), "m029": (36.9, 3.5)})))
        a = build(base, when=DAY, mountains=NAMES)
        b = build(base, when="2026-10-18", mountains=NAMES)
        self.assertTrue(fact(a, "高尾山", DAY)["cloud_clear"])
        self.assertFalse(fact(b, "高尾山", "2026-10-18")["cloud_clear"])
        c = SH.cfg()

        def run(doc):
            calls = [{"name": "Bash", "input": {"command": "python -X utf8 -m concierge brief --question x"}, "result": d["id"]} for d in (a, b)]
            calls.append({"name": "Bash", "input": {"command": f"python -X utf8 -m concierge verify /tmp/d.txt --brief {doc['id']}"}, "result": "ok"})
            return {"prompt": "どっち?", "key": "k", "calls": calls}
        text = "10月18日(日)の高尾山は95点です。雲量は36.9 %の見込みです。"
        self.assertFalse(SH._cloud_violation(text, run(b), base, c))
        self.assertFalse(SH._cloud_violation("高尾山の雲量は36.9 %です。", run(b), base, c))
        self.assertTrue(SH._cloud_violation("10月17日(土)の高尾山の雲量は18.6 %です。", run(a), base, c))
        self.assertFalse(SH._cloud_violation("10月19日(月)の高尾山の雲量は40 %です。", run(a), base, c))


if __name__ == "__main__":
    unittest.main()
