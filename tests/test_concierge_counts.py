"""段階 2 の小さな直し 3.3・3.8: 危険信号の件数の事実 [N…]・「どれも・全部」の文の照合・危険信号の注記の位置。通信しない。
見本の棚は 3 座しかないので、作り物の山の日(値は本物の予報ではない)で確かめる(test_concierge_frames.synthetic)。"""
import unittest

from concierge_helpers import base_with_shelf, build
from test_concierge_answer import codes
from test_concierge_frames import DAY, NEAR, synthetic

from concierge import brief as B
from concierge import fallback as F
from concierge import verify as V
from concierge.common import brief_schema_errors

SUN = "2026-10-18"


def sat_rows():
    """基準点以上 8 座: 警戒以上 6 座(強風危険 3 座 + 低体温症危険 1 座 + 強風警戒 2 座)・注意 1 座・なし 1 座。ほかに基準点未満 1 座。"""
    return [(NEAR[0], 90.0, {"wind": "危険"}, 20.0), (NEAR[1], 89.0, {"wind": "危険", "cold": "警戒"}, 20.0), (NEAR[2], 88.0, {"wind": "危険"}, 20.0),
            (NEAR[3], 87.0, {"cold": "危険"}, 9.0), (NEAR[4], 86.0, {"wind": "警戒"}, 12.0), (NEAR[5], 85.0, {"wind": "警戒"}, 12.0),
            (NEAR[6], 84.0, {"cold": "注意"}, 4.0), (NEAR[7], 83.0, {}, 4.0), (NEAR[8], 60.0, {"wind": "危険"}, 20.0)]


class Base(unittest.TestCase):
    def build(self, rows, when=DAY, sun=None, **kw):
        def edit(d):
            synthetic(rows)(d)
            if sun:
                synthetic(sun, day=SUN)(d)
        self.doc = build(base_with_shelf(self, edit=edit), when=when, **kw)
        self.assertEqual(brief_schema_errors(self.doc), [])
        return self.doc

    def codes(self, sentence):
        L = self.doc["lines"]
        head = "\n".join(f"{L[k]['text']}[{L[k]['id']}]" for k in ("data_time", "coverage", "attribution"))
        return codes(V.check(f"{sentence}\n{head}\n[おすすめ] なし", self.doc))

    def ok(self, sentence):
        self.assertEqual(self.codes(sentence), [], sentence)

    def ng(self, sentence, code):
        self.assertIn(code, self.codes(sentence), sentence)


class Counts(Base):
    def test_counts_all_and_outside_of_the_frame_by_the_worst_level(self):
        doc = self.build(sat_rows())
        n, = doc["hazard_counts"]
        self.assertEqual((n["id"], n["date"], n["above"]), ("N1", DAY, 8))
        self.assertEqual(n["all"], {"total": 6, "warning": 2, "danger": 4})          # 危険と警戒が両方ある山は、危険で数える
        self.assertEqual(n["outside"], {"total": 3, "warning": 2, "danger": 1})
        self.assertEqual(n["outside"]["total"], doc["candidates"][0]["counts"]["outside_skip"])
        for s in ("危険信号が警戒以上の山は 6 座", "このうち危険は 4 座"):
            self.assertIn(s, n["say"])
        md = B.render_md(doc)
        self.assertIn("[N1] 10月17日(土): 基準点以上 8 座のうち、警戒以上 6 座(警戒 2・危険 4)。見送りの枠の外 3 座(警戒 2・危険 1。", md)

    def test_named_mountains_do_not_change_the_counts(self):
        a = self.build(sat_rows())["hazard_counts"][0]
        b = self.build(sat_rows(), mountains=[NEAR[8], NEAR[5]])["hazard_counts"][0]
        self.assertEqual(a, b)

    def test_zero_and_no_mountain_above(self):
        doc = self.build([(NEAR[0], 90.0, {"cold": "注意"}, 4.0)], when="今週末", sun=[(NEAR[0], 60.0, {}, 4.0)])
        self.assertEqual([(n["date"], n["all"]["total"]) for n in doc["hazard_counts"]], [(DAY, 0)])      # 基準点以上の山がない日は作らない
        self.ok("土曜は、危険信号が警戒以上の山はありません。[N1]")
        self.ng("土曜は、危険信号が警戒以上の山があります。[N1]", "hazard_count_mismatch")

    def test_count_sentences(self):
        self.build(sat_rows())
        for s in ("土曜は、危険信号が警戒以上の山は 6 座です。[N1]", "土曜は、危険信号が警戒以上の山は6座で、このうち危険は4座、警戒は2座です。[N1]",
                  "10月17日(土)は、基準の70点以上の山は 8 座で、このうち危険信号が警戒以上の山は 6 座です。[N1]",
                  "土曜は、基準の70点以上の8座のうち6座が、警戒以上です。[N1]", "このうち危険は 4 座です。[N1]",
                  "危険信号が警戒以上の山があります。[N1]"):
            with self.subTest(s):
                self.ok(s)
        for s in ("土曜は、危険信号が警戒以上の山は 4 座です。[N1]", "土曜は、危険信号が危険の山は 6 座です。[N1]", "土曜は、強風危険の山は 4 座です。[N1]",
                  "土曜は、危険信号が警戒以上でない山は 6 座です。[N1]", "土曜は、危険信号が警戒以上の山は約6座です。[N1]", "土曜は、山が 6 座あります。[N1]",
                  "強風の山があります。[N1]", "土曜は、危険信号が警戒まで出ている山があります。[N1]"):
            with self.subTest(s):
                self.ng(s, "hazard_count_mismatch")
        self.ng("土曜は、危険信号が警戒以上の山は 2 座です。[Y001]", "hazard_count_unmarked")       # 「2日先」の 2 で通さない
        self.ng("土曜は、危険信号が警戒以上の山は 5 座です。[N1]", "number_mismatch")

    def test_frame_numbers_are_not_allowed_as_the_whole(self):
        self.build(sat_rows())
        self.ng("土曜は、危険信号が警戒以上の山は 3 座です。[N1]", "number_mismatch")               # 枠に載った 3 座・枠の外の 3 座

    def test_tied_rank_is_not_a_count(self):
        doc = self.build([(m, 90.0, {"wind": "危険"}, 20.0) for m in NEAR[:3]])
        y = doc["facts"][0]
        self.ok(f"土曜の{y['name']}は90点で1位(同点 3 座)ですが、強風危険の危険信号が出ています。[{y['id']}]")

    def test_days(self):
        self.build(sat_rows(), when="今週末", sun=[(NEAR[0], 90.0, {"wind": "危険"}, 20.0), (NEAR[1], 90.0, {"wind": "危険"}, 20.0)])
        self.ok("日曜は、危険信号が警戒以上の山は 2 座です。[N2]")
        self.ng("日曜は、危険信号が警戒以上の山は 6 座です。[N1]", "date_mismatch")
        self.ng("今週末は、危険信号が警戒以上の山は 6 座です。[N1]", "hazard_count_mismatch")
        self.ng("日曜は、危険信号が警戒以上の山は 6 座です。[N1][N2]", "hazard_count_mismatch")


class Universal(Base):
    def test_the_mistake_of_question_8_is_stopped(self):
        """枠の 3 座だけを見て「どれも強風危険」と書いた誤り(仕上げの通しの試しの問い 8)。"""
        self.build(sat_rows())
        s = "基準の70点を超えた山はありますが、どれも強風危険の危険信号が出ています。"
        self.ng(s + "[Y003][Y004][Y005]", "hazard_universal_unmarked")
        self.ng(s + "[N1]", "hazard_universal_mismatch")
        self.ng(s + "[Y003][N1]", "hazard_universal_mismatch")
        r = V.check(s + "[N1]\n[おすすめ] なし", self.doc)
        self.assertTrue(any("件数を書く" in e["fix"] for e in r["errors"] if e["code"] == "hazard_universal_mismatch"))

    def test_kinds_are_never_decidable(self):
        self.build([(m, 90.0, {"wind": "危険"}, 20.0) for m in NEAR[:5]])
        self.ng("基準の70点以上の山は、どれも強風危険です。[N1]", "hazard_universal_mismatch")       # 件数は種類を持たない

    def test_true_universal_passes(self):
        self.build([(m, 90.0, {"wind": "危険"}, 20.0) for m in NEAR[:5]])
        for s in ("基準の70点以上の山は、どれも危険信号が警戒以上です。[N1]", "土曜は、基準の70点以上の山の全部に、危険信号が出ています。[N1]",
                  "基準の70点以上の山は5座で、どの山も危険信号が危険です。[N1]", "基準の70点以上の山は、すべて危険信号が警戒以上です。[N1]"):
            with self.subTest(s):
                self.ok(s)
        self.ng("基準の70点以上の山は、どれも危険信号が警戒です。[N1]", "hazard_universal_mismatch")
        self.ng("どれも危険信号が警戒以上です。[N1]", "hazard_universal_mismatch")                   # どの山の全部かが書いていない
        self.ng("基準の70点以上の山は、どれも危険信号が警戒以上とは限りません。[N1]", "hazard_universal_mismatch")

    def test_false_universal_fails(self):
        self.build(sat_rows())
        for s in ("基準の70点以上の山は、どれも危険信号が警戒以上です。[N1]", "基準の70点以上の山は、全部危険信号が出ています。[N1]",
                  "基準の70点以上の山は、どの山も危険です。[N1]", "基準の70点以上の山は、いずれも警戒以上の危険信号が出ています。[N1]",
                  "基準の70点以上の山は、どれも警戒以上の危険信号は出ていません。[N1]"):
            with self.subTest(s):
                self.ng(s, "hazard_universal_mismatch")
        self.ng("基準の70点以上の山は、どれも警戒です。[Y001]", "hazard_universal_unmarked")

    def test_negation(self):
        self.build([(m, 90.0, {"cold": "注意"}, 4.0) for m in NEAR[:3]])
        self.ok("基準の70点以上の山には、どの山も警戒以上の危険信号は出ていません。[N1]")
        self.ng("基準の70点以上の山には、どの山も危険信号は出ていません。[N1]", "hazard_universal_mismatch")      # 注意は数えていない

    def test_all_days_are_needed(self):
        bad = [(m, 90.0, {"wind": "危険"}, 20.0) for m in NEAR[:3]]
        self.build(bad, when="今週末", sun=sat_rows())
        s = "基準の70点以上の山は、どれも危険信号が警戒以上です。"
        self.ok("土曜は、" + s + "[N1]")
        self.ng(s + "[N1]", "hazard_universal_mismatch")                  # 日を書かなければ、対象の日の全部
        self.ng("土日とも、" + s + "[N1][N2]", "hazard_universal_mismatch")
        self.ng("日曜は、" + s + "[N2]", "hazard_universal_mismatch")

    def test_counting_all_together_is_not_universal(self):
        self.build(sat_rows())
        self.ok("土曜は、危険信号が警戒以上の山は全部で 6 座です。[N1]")

    def test_universal_without_hazard_words_is_not_checked(self):
        self.build(sat_rows())
        self.ok("どの山も、名前の由来にはいくつかの説があるといわれます。")


class NotePosition(Base):
    def check_position(self):
        """控えの文の注記は、最後の危険信号の文より後ろで、足りないものの文のすぐ前(山ごとの説明の段落の中ではない)。"""
        for compact in (False, True):
            r = V.check(F.draft(self.doc, compact=compact), self.doc)
            self.assertTrue(r["ok"], r["errors"])
            lines = r["final"].split("\n")
            note = self.doc["lines"]["hazard_note"]["text"]
            self.assertEqual(lines.count(note), 1)
            i = lines.index(note)
            self.assertEqual((lines[i - 1], lines[i + 1]), ("", ""))            # 前後が空行(段落 1 つ。段階 3 の前の準備 3.1)
            self.assertIn(lines[i + 2], [g["text"] for g in self.doc["gaps"]])
            self.assertTrue(all(lines.index(h["text"]) < i for h in self.doc["lines"]["hazards"] if h["text"] in lines))

    def test_last_pick_has_no_hazard_and_no_skip(self):              # 利用者の試しの形(高尾山の下に注記が付いた)
        self.build([(NEAR[0], 90.0, {"cold": "注意"}, 4.0), (NEAR[1], 89.0, {}, 4.0)])
        self.check_position()

    def test_last_skip_is_below_the_threshold(self):
        self.build([(NEAR[0], 90.0, {"wind": "危険"}, 20.0), (NEAR[1], 60.0, {}, 4.0)], mountains=[NEAR[0], NEAR[1]])
        self.check_position()

    def test_only_skip(self):
        self.build(sat_rows()[:6])
        self.check_position()


if __name__ == "__main__":
    unittest.main()
