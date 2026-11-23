"""段階 3 の前の準備(docs/stage3-prep-instructions.md)3.1・3.3・3.4・3.5・3.7 の照合と控えの文。通信しない。
見本の棚は 3 座しかないので、作り物の山の日(値は本物の予報ではない)でも確かめる(test_concierge_frames.synthetic)。"""
import unittest

from concierge_helpers import base_with_shelf, build, fact
from test_concierge_answer import codes, good_draft
from test_concierge_counts import Base, sat_rows

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


if __name__ == "__main__":
    unittest.main()
