"""段階 2 の仕上げ(第 3 部): 足りないものの印の抜け道・比べる文(いちばん・最も)の照合。通信しない。
見本の棚(2026-10-17・18 の 3 座)の比べた結果: 10/17 は横岳の風がいちばん弱く、八ヶ岳(赤岳)がいちばん近い。10/17 の 1 位は同点 2 座、
10/18 の 1 位は谷川岳だけ。"""
import unittest

from concierge_helpers import base_with_shelf, build, fact
from test_concierge_answer import codes, good_draft
from test_concierge_frames import synthetic

from concierge import verify as V

REP = "横岳という名前の由来には、いくつかの説があるといわれます。"


class Base(unittest.TestCase):
    def setUp(self):
        self.doc = build(base_with_shelf(self))
        self.g = good_draft(self.doc)
        self.assertTrue(V.check(self.g, self.doc)["ok"])

    def run_with(self, sentence, doc=None, g=None):
        doc = doc or self.doc
        return V.check((g or self.g).replace(REP, sentence), doc)

    def ok(self, sentence):
        r = self.run_with(sentence)
        self.assertTrue(r["ok"], (sentence, r["errors"]))

    def ng(self, sentence, code):
        self.assertIn(code, codes(self.run_with(sentence)), sentence)

    def y(self, name, day):
        return fact(self.doc, name, day)["id"]

    def c(self, kind, day):
        return next(x["id"] for x in self.doc["comparisons"] if x["kind"] == kind and x["date"] == day)


class GapMark(Base):
    def test_gap_mark_alone_does_not_pass_safety_words(self):
        for bad in ("この時期はアイゼンが必要です。[G1]", "凍結に注意してください。[G1]", "横岳は初級者向けです。[G1]"):
            with self.subTest(bad):
                self.ng(bad, "safety_without_basis")

    def test_gap_mark_with_cannot_judge_passes(self):
        self.ok("アイゼンが必要かどうかは、この予報からは判断できません。[G1]")
        self.ok("凍結や積雪があるかは分かりません。[G1]")

    def test_the_fix_message_says_the_mark_is_not_enough(self):
        r = self.run_with("この時期はアイゼンが必要です。[G1]")
        self.assertIn("[G…] の印だけでは通らない", " ".join(e["fix"] for e in r["errors"]))


class Superlatives(Base):
    def test_weakest_wind(self):
        y, c = self.y("横岳", "2026-10-17"), self.c("ridge_wind_min", "2026-10-17")
        self.ok(f"土曜の横岳は、おすすめの候補の中で稜線の風がいちばん弱い見込みです。[{y}][{c}]")
        self.ok(f"土曜の横岳の稜線風速は5.2 m/sで、おすすめの候補の中で最も弱い見込みです。[{y}][{c}]")
        self.ng(f"土曜の横岳は、候補の中で稜線の風がいちばん弱い見込みです。[{y}]", "comparison_unmarked")

    def test_nearest(self):
        y, c = self.y("八ヶ岳", "2026-10-17"), self.c("nearest", "2026-10-17")
        self.ok(f"八ヶ岳(赤岳)は、おすすめの候補の中で横浜からいちばん近い山です。[{y}][{c}]")
        self.ng(f"八ヶ岳(赤岳)は、候補の中で横浜から一番近い山です。[{y}]", "comparison_unmarked")

    def test_wrong_mountain_topic_or_day(self):
        y1, y2 = self.y("八ヶ岳", "2026-10-17"), self.y("横岳", "2026-10-17")
        cw, cn, cn2 = (self.c("ridge_wind_min", "2026-10-17"), self.c("nearest", "2026-10-17"), self.c("nearest", "2026-10-18"))
        self.ng(f"八ヶ岳(赤岳)は、おすすめの候補の中で稜線の風がいちばん弱い見込みです。[{y1}][{cw}]", "comparison_mismatch")
        self.ng(f"横岳は、おすすめの候補の中で稜線の風がいちばん弱い見込みです。[{y2}][{cn}]", "comparison_unmarked")     # 対象が違う
        self.ng(f"八ヶ岳(赤岳)は、おすすめの候補の中で横浜からいちばん近い山です。[{y1}][{cn2}]", "comparison_mismatch")   # 日が違う
        self.ng(f"横岳と八ヶ岳(赤岳)は、おすすめの候補の中で稜線の風がいちばん弱い見込みです。[{y1}][{y2}][{cw}]", "comparison_mismatch")
        self.ok(f"八ヶ岳(赤岳)と比べると、横岳はおすすめの候補の中で稜線の風がいちばん弱い見込みです。[{y1}][{y2}][{cw}]")

    def test_directions_and_topics_without_a_fact_fail(self):
        y = self.y("八ヶ岳", "2026-10-17")
        for bad in ("稜線の風がいちばん強い", "横浜からいちばん遠い", "体感温度(稜線)がいちばん低い", "標高がいちばん高い", "雲量がいちばん少ない",
                    "体感温度(稜線)がいちばん暖かい"):
            with self.subTest(bad):
                self.ng(f"八ヶ岳(赤岳)は、候補の中で{bad}山です。[{y}]", "comparison_unmarked")

    def test_scope_is_needed(self):
        y, c = self.y("横岳", "2026-10-17"), self.c("ridge_wind_min", "2026-10-17")
        self.ng(f"土曜の横岳は、関東で稜線の風がいちばん弱い見込みです。[{y}][{c}]", "comparison_scope")

    def test_two_comparisons_in_one_sentence_need_both(self):
        doc = build(base_with_shelf(self, edit=synthetic([("m029", 90.0, {}, 3.0), ("m023", 89.0, {}, 5.0)])), when="2026-10-17")
        y = fact(doc, "高尾山", "2026-10-17")["id"]
        c = {x["kind"]: x["id"] for x in doc["comparisons"]}
        L = doc["lines"]
        head = "\n".join(f"{L[k]['text']}[{L[k]['id']}]" for k in ("data_time", "coverage", "attribution"))
        s = "高尾山は、おすすめの候補の中で稜線の風がいちばん弱く、横浜からもいちばん近い山です。"
        for marks, ok in ((f"[{c['ridge_wind_min']}][{c['nearest']}]", True), (f"[{c['ridge_wind_min']}]", False)):
            r = V.check(f"{s}[{y}]{marks}\n{head}\n[おすすめ] なし", doc)
            self.assertEqual(r["ok"], ok, r["errors"])

    def test_skipping_sentences_are_checked_too(self):
        y = self.y("八ヶ岳", "2026-10-17")
        self.ng(f"稜線の風がいちばん強い八ヶ岳(赤岳)は、今回は見送るのがよさそうです。[{y}]", "comparison_unmarked")

    def test_recommendation_wording_is_not_a_comparison(self):
        y = self.y("八ヶ岳", "2026-10-17")
        self.ok(f"稜線風速は5.4 m/sの見込みで、土曜の八ヶ岳(赤岳)がいちばんのおすすめです。[{y}]")

    def test_looks_best_is_not_a_comparison(self):                 # 通しの試しの探りで止めすぎた形
        y = self.y("八ヶ岳", "2026-10-17")
        self.ok(f"今週末は、土曜がいちばんよさそうで、八ヶ岳(赤岳)の稜線風速は5.4 m/sの見込みです。[{y}]")

    def test_idioms_with_the_superlative_characters_pass(self):   # 「最高の一日」「最低でも」は比べる文ではない
        self.ok("横岳は、最高の一日を過ごせる山だといわれます。")
        y = self.y("谷川岳", "2026-10-17")
        self.ng(f"土曜は、点数が最高の谷川岳です。[{y}]", "comparison_mismatch")      # 比べる文の「最高の」は見る

    def test_names_do_not_count_as_topics(self):
        self.ok("横岳は、地元でいちばん親しまれている山だといわれます。")


class LevelOnly(unittest.TestCase):
    """種類を書かずに段階だけを言う文(3.5。利用者の決定 2026-11-23): 印の事実のいちばん重い段階と合っていれば通す。"""

    def setUp(self):
        rows = [("m029", 90.0, {"wind": "注意", "cold": "警戒"}, 9.0), ("m023", 89.0, {"wind": "危険"}, 20.0), ("m022", 88.0, {}, 4.0),
                ("m027", 87.0, {"cold": "注意"}, 4.0)]
        self.doc = build(base_with_shelf(self, edit=synthetic(rows)), when="2026-10-17")      # 4 座とも枠に入る
        self.y = {f["mountain_id"]: f["id"] for f in self.doc["facts"]}

    def codes(self, sentence, *mids):
        L = self.doc["lines"]
        head = "\n".join(f"{L[k]['text']}[{L[k]['id']}]" for k in ("data_time", "coverage", "attribution"))
        return codes(V.check(sentence + "".join(f"[{self.y[m]}]" for m in mids) + f"\n{head}\n[おすすめ] なし", self.doc))

    def test_matching_level_passes(self):
        for s, m in (("高尾山は、危険信号が警戒まで出ています。", "m029"), ("高尾山は危険信号が警戒以上です。", "m029"), ("高尾山には警戒の危険信号が出ています。", "m029"),
                     ("丹沢山は危険信号が警戒以上です。", "m023"), ("丹沢山には危険の危険信号が出ています。", "m023"), ("丹沢山は危険信号が「危険」まで出ています。", "m023"),
                     ("大山は危険信号が注意まで出ています。", "m027"), ("高尾山は低体温症警戒の危険信号が出ています。", "m029"),
                     ("塔ノ岳には警戒以上の危険信号は出ていません。", "m022"), ("大山には警戒以上の危険信号は出ていません。", "m027")):
            with self.subTest(s):
                self.assertEqual(self.codes(s, m), [])

    def test_wrong_level_fails(self):
        for s, m in (("高尾山は、危険信号が危険まで出ています。", "m029"), ("高尾山は、危険信号が注意まで出ています。", "m029"), ("丹沢山は危険信号が警戒まで出ています。", "m023"),
                     ("丹沢山には警戒の危険信号が出ています。", "m023"), ("塔ノ岳は危険信号が警戒以上です。", "m022"), ("大山は危険信号が警戒以上です。", "m027"),
                     ("高尾山には警戒以上の危険信号は出ていません。", "m029"), ("丹沢山には危険の危険信号は出ていません。", "m023"),
                     ("高尾山は強風警戒の危険信号が出ています。", "m029")):
            with self.subTest(s):
                self.assertEqual(self.codes(s, m), ["hazard_mismatch"])

    def test_each_clause_is_checked_against_its_own_mountain(self):
        self.assertEqual(self.codes("高尾山は危険信号が警戒まで、丹沢山は危険信号が危険まで出ています。", "m029", "m023"), [])
        self.assertEqual(self.codes("高尾山は危険信号が危険まで、丹沢山は危険信号が警戒まで出ています。", "m029", "m023"), ["hazard_mismatch"])
        self.assertEqual(self.codes("高尾山と丹沢山は、危険信号が警戒まで出ています。", "m029", "m023"), ["hazard_mismatch"])      # どちらかが違えば止める

    def test_simple_rows_have_an_open_level(self):
        """70 点未満の山(簡易行)の「警戒以上」は、上の段階が分からないので「まで」とは言えない。"""
        doc = build(base_with_shelf(self), when="2026-10-19", mountains=["谷川岳"])
        y = fact(doc, "谷川岳", "2026-10-19")
        self.assertEqual(y["hazards"][0]["level"], "警戒以上")
        L = doc["lines"]
        head = "\n".join(f"{L[k]['text']}[{L[k]['id']}]" for k in ("data_time", "coverage", "attribution"))
        for s, want in (("谷川岳は危険信号が警戒以上です。", []), ("谷川岳は危険信号が警戒まで出ています。", ["hazard_mismatch"])):
            self.assertEqual(codes(V.check(f"{s}[{y['id']}]\n{head}\n[おすすめ] なし", doc)), want, s)


class Scores(Base):
    def test_first_without_tie_passes(self):
        y = self.y("谷川岳", "2026-10-18")
        self.ok(f"日曜は谷川岳の点数がいちばん高い見込みです。[{y}]")

    def test_one_of_the_tied_mountains_fails_but_the_rank_wording_passes(self):
        y1, y2 = self.y("八ヶ岳", "2026-10-17"), self.y("横岳", "2026-10-17")
        self.ng(f"土曜は八ヶ岳(赤岳)の点数がいちばん高い見込みです。[{y1}]", "comparison_tied")
        self.ok(f"土曜は八ヶ岳(赤岳)と横岳の点数がいちばん高い見込みです。[{y1}][{y2}]")
        self.ok(f"土曜の八ヶ岳(赤岳)は90.4点で1位(同点 2 座)です。[{y1}]")
        self.ng(f"土曜の八ヶ岳(赤岳)は90.4点で1位です。[{y1}]", "rank_tie_hidden")

    def test_not_first_fails(self):
        y = self.y("谷川岳", "2026-10-17")
        self.ng(f"土曜は谷川岳の点数がいちばん高い見込みです。[{y}]", "comparison_mismatch")


if __name__ == "__main__":
    unittest.main()
