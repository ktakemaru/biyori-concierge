"""段階 3 の前の準備(docs/stage3-prep-instructions.md)3.1・3.3・3.4・3.5・3.7 の照合と控えの文。通信しない。
見本の棚は 3 座しかないので、作り物の山の日(値は本物の予報ではない)でも確かめる(test_concierge_frames.synthetic)。"""
import unittest

from concierge_helpers import base_with_shelf, build, fact
from test_concierge_answer import codes, good_draft
from test_concierge_counts import SUN, Base, sat_rows
from test_concierge_frames import DAY, NEAR

from concierge import verify as V

REP = "横岳という名前の由来には、いくつかの説があるといわれます。"


class CannotJudge(unittest.TestCase):
    """3.4: 「判断できない」で始まる言い方を通す。"""

    def setUp(self):
        self.doc = build(base_with_shelf(self))

    def codes(self, sentence):
        return codes(V.check(good_draft(self.doc).replace(REP, sentence), self.doc))

    def test_passes(self):
        y = fact(self.doc, "横岳", "2026-10-17")["id"]
        for s in ("岩場や急坂があるかは判断できないので、予報の数字だけで選びました。", "装備は判断できないため、予報の数字だけを書きます。",
                  f"難しさは判断できず、土曜の横岳は90.4点です。[{y}]", "凍結や積雪は判断できないものの、数字は書けます。"):
            with self.subTest(s):
                self.assertEqual(self.codes(s), [])

    def test_stopped(self):
        for s in ("岩場が少ないので、歩きやすい山です。", "難しさは判断できないわけではありません。", "凍結は判断できないとは言えません。"):
            with self.subTest(s):
                self.assertIn("safety_without_basis", self.codes(s))


class Vague(Base):
    """3.5: 割合・ぼかした言い方を、危険信号の語と同じ文では止める。"""

    def test_stopped_with_or_without_marks(self):
        self.build(sat_rows())
        for s in ("ほとんどの山が強風危険です。[Y003]", "土曜は、半分以上の山に警戒以上の危険信号が出ています。[N1]", "大半の山は警戒以上です。[N1]",
                  "多くの山に危険信号が出ています。[N1]", "ほかの山も強風危険です。[Y003]", "高い山ほど強風危険が多い見込みです。[Y003]",
                  "ほとんどの山が警戒以上です。", "他の山にも危険信号が出ています。"):
            with self.subTest(s):
                self.ng(s, "hazard_vague")

    def test_the_fix_shows_the_count_sentence(self):
        self.build(sat_rows())
        r = V.check("ほとんどの山が強風危険です。[Y003]\n[おすすめ] なし", self.doc)
        e = next(e for e in r["errors"] if e["code"] == "hazard_vague")
        self.assertIn("件数の文を写す(例: 10月17日(土)は、危険信号が警戒以上の山は 6 座です。[N1])", e["fix"])

    def test_passes(self):
        self.build(sat_rows())
        for s in ("10月17日(土)は、危険信号が警戒以上の山は 6 座です。[N1]", "ほとんどの山には、名前の由来にいくつかの説があるといわれます。",
                  "土曜の高尾山は強風危険なので、ほかの山にするのがよさそうです。[%s]" % fact(self.doc, "高尾山", "2026-10-17")["id"]):
            with self.subTest(s):
                self.ok(s)


class ListedUniversal(Base):
    """3.3: 山の名前を並べた「どれも」は、並べた山の全部の事実と合えば、件数の印がなくても通す。"""

    def setUp(self):
        rows = [(NEAR[0], 90.0, {"wind": "危険"}, 20.0), (NEAR[1], 89.0, {"wind": "危険", "cold": "危険"}, 20.0), (NEAR[2], 88.0, {"wind": "危険", "cold": "危険"}, 20.0),
                (NEAR[3], 87.0, {"wind": "警戒"}, 12.0), (NEAR[4], 86.0, {"cold": "注意"}, 4.0)]
        sun = [(NEAR[0], 90.0, {"wind": "危険"}, 20.0), (NEAR[1], 89.0, {"wind": "警戒"}, 12.0)]
        self.build(rows, when="今週末", sun=sun, mountains=NEAR[:5], question="見送る山は?")
        self.y = {(f["mountain_id"], f["date"]): f["id"] for f in self.doc["facts"]}
        self.n = {f["mountain_id"]: f["name"] for f in self.doc["facts"]}

    def s(self, idx, tail, day=DAY, marks=None, head="土曜の"):
        ids = marks or [self.y[(NEAR[i], day)] for i in idx]
        return head + "・".join(self.n[NEAR[i]] for i in idx) + tail + "".join(f"[{x}]" for x in ids)

    def test_true_lists_pass(self):
        for s in (self.s([0, 1, 2], "は、どれも強風危険です。"), self.s([1, 2], "は、いずれも強風危険・低体温症危険です。"),
                  self.s([1, 2], "は、どれも強風・低体温症危険の見込みです。"), self.s([0, 1, 2], "は、すべて危険信号が危険です。"),
                  self.s([0, 1, 2, 3], "には、どれも警戒以上の危険信号が出ています。"), self.s([0, 1, 2, 3, 4], "は、どれも危険信号が出ています。"),
                  self.s([0, 1, 2], "は、どれも強風危険なので、今回は行かないほうがよさそうです。"), self.s([0, 1, 2], "の3つは、どれも強風危険です。"),
                  self.s([0, 1, 2], "は、どれも強風の危険信号が出ています。"), self.s([0, 1, 2], "は、どれも強風危険なので、注意して見ます。")):
            with self.subTest(s):
                self.ok(s)

    def test_one_wrong_mountain_is_stopped(self):
        for s in (self.s([0, 1, 2, 3], "は、どれも強風危険です。"), self.s([0, 1], "は、どれも低体温症危険です。"), self.s([0, 1, 2], "は、どれも強風・低体温症危険です。"),
                  self.s([3, 4], "は、どれも強風の危険信号が出ています。"), self.s([0, 1, 2, 3], "は、すべて危険信号が危険です。"),
                  self.s([0, 1, 2], "は、どれも強風危険の危険信号は出ていません。"), self.s([0, 1, 2], "は、強風が、どれも危険です。"),
                  self.s([0, 1, 2], "は、強風が、どれも注意です。")):
            with self.subTest(s):
                self.ng(s, "hazard_universal_unmarked")

    def test_every_listed_mountain_needs_its_mark(self):
        marks = [self.y[(NEAR[i], DAY)] for i in (0, 1)]
        self.ng(self.s([0, 1, 2], "は、どれも強風危険です。", marks=marks), "hazard_universal_unmarked")
        self.doc["question"] = "土曜の" + "・".join(self.n.values())                        # 質問に書かれた山でも、印は要る
        self.ng(self.s([0, 1, 2], "は、どれも強風危険です。", marks=marks), "hazard_universal_unmarked")

    def test_days(self):
        self.ok(self.s([0, 1], "は、どれも強風危険です。"))
        self.ng(self.s([0, 1], "は、どれも強風危険です。", day=SUN, head="日曜の"), "hazard_universal_unmarked")      # 日曜の 2 座目は警戒
        sat_marks = [self.y[(NEAR[i], DAY)] for i in (0, 1)]
        self.ng(self.s([0, 1], "は、どれも強風危険です。", head="今週末の", marks=sat_marks), "hazard_universal_unmarked")   # 日曜を見ていない
        mixed = [self.y[(NEAR[0], DAY)], self.y[(NEAR[1], SUN)]]
        self.ng(self.s([0, 1], "は、どれも危険信号が出ています。", marks=mixed), "hazard_universal_unmarked")                  # 2 座目の土曜の印がない

    def test_not_a_list_still_needs_the_count(self):
        names = "・".join(self.n[NEAR[i]] for i in (0, 1, 2))
        marks = "".join(f"[{self.y[(NEAR[i], DAY)]}]" for i in (0, 1, 2))
        for s in (f"土曜の{names}など、どの山も強風危険です。", f"土曜は{names}が高い点ですが、どれも強風危険です。", f"土曜の基準の70点以上の山は、{names}と、どれも強風危険です。",
                  f"土曜の{names}のほか、どの山も強風危険です。", f"土曜の{names}は、どれも強風危険で、どの山も危険信号が出ています。"):
            with self.subTest(s):
                self.ng(s + marks, "hazard_universal_unmarked")
        self.ng(f"土曜の{names}は、どれも強風危険です。{marks}[N1]", "hazard_universal_mismatch")


if __name__ == "__main__":
    unittest.main()
