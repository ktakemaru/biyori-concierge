"""段階 3 の前の準備(docs/stage3-prep-instructions.md)3.1・3.3・3.4・3.5・3.7 の照合と控えの文。通信しない。
見本の棚は 3 座しかないので、作り物の山の日(値は本物の予報ではない)でも確かめる(test_concierge_frames.synthetic)。"""
import unittest

from concierge_helpers import base_with_shelf, build, fact, line_for, make_hazard
from helpers import ROOT
from test_concierge_answer import codes, good_draft
from test_concierge_counts import SUN, Base, sat_rows
from test_concierge_frames import DAY, NEAR

from concierge import brief as B
from concierge import fallback as F
from concierge import verify as V
from concierge.common import brief_schema_errors

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


class SkipLine(Base):
    """3.7: 見送りの山の危険信号を、日ごとに 1 つのまとめの文で書く。"""

    def rows(self):
        return [(NEAR[0], 90.0, {"wind": "危険", "cold": "危険"}, 20.0), (NEAR[1], 89.0, {"cold": "注意", "wind": "危険"}, 20.0), (NEAR[2], 88.0, {"wind": "危険", "cold": "危険"}, 20.0),
                (NEAR[3], 87.0, {"wind": "警戒"}, 12.0), (NEAR[4], 86.0, {"cold": "注意"}, 4.0)]

    def draft(self, middle, picks="なし"):
        L = self.doc["lines"]
        head = "\n".join(f"{L[k]['text']}[{L[k]['id']}]" for k in ("data_time", "coverage"))
        return f"今回は見送るのがよさそうです。\n{head}\n\n{middle}\n\n{L['attribution']['text']}[{L['attribution']['id']}]\n[おすすめ] {picks}\n"

    def test_text_groups_by_the_same_hazards_in_the_order_of_the_frame(self):
        doc = self.build(self.rows())
        x, = doc["lines"]["skips"]
        names = [f["name"] for f in doc["facts"] if f["selected_by"] == "skip"]
        self.assertEqual([f["mountain_id"] for f in doc["facts"] if f["selected_by"] == "skip"], [NEAR[0], NEAR[2], NEAR[1]])
        self.assertEqual(x["text"], f"10月17日(土)は、{names[0]}・{names[1]}に強風危険・低体温症危険、{names[2]}に強風危険・低体温症注意の危険信号が出ています。")
        self.assertEqual(x["facts"], [f["id"] for f in doc["facts"] if f["selected_by"] == "skip"])
        self.assertGreater(int(x["id"][1:]), max(int(h["id"][1:]) for h in doc["lines"]["hazards"]))      # 山ごとの文の番号は変えない
        self.assertNotRegex(x["text"].replace("10月17日", ""), r"\d")                                    # 数字は入れない
        self.assertIn(f"- [{x['id']}](見送りのまとめ・{'・'.join(x['facts'])}。", B.render_md(doc))

    def test_one_line_a_day_and_none_without_a_skip_frame(self):
        doc = self.build(self.rows(), when="今週末", sun=[(NEAR[0], 90.0, {"cold": "注意"}, 4.0)])
        self.assertEqual([x["date"] for x in doc["lines"]["skips"]], [DAY])
        doc = self.build(self.rows(), when="今週末", sun=[(NEAR[0], 90.0, {"wind": "警戒"}, 12.0)])
        self.assertEqual([x["date"] for x in doc["lines"]["skips"]], [DAY, SUN])

    def test_the_line_stands_for_the_lines_of_the_mountains(self):
        doc = self.build(self.rows())
        x, n = doc["lines"]["skips"][0], doc["hazard_counts"][0]
        r = V.check(self.draft(f"{x['text']}[{x['id']}]危険信号が警戒以上の山は 4 座で、このうち危険は 3 座です。[{n['id']}]\n危険信号は、点数とは別に出る警告です。[{doc['lines']['hazard_note']['id']}]"), doc)
        self.assertTrue(r["ok"], r["errors"])
        self.assertIn(x["text"] + "危険信号が警戒以上の山は 4 座で、このうち危険は 3 座です。", r["final"])
        self.assertFalse(any(h["text"] in r["final"] for h in doc["lines"]["hazards"]))

    def test_altered_line_is_stopped(self):
        doc = self.build(self.rows())
        x = doc["lines"]["skips"][0]
        self.assertIn("line_altered", codes(V.check(self.draft(f"{x['text'].replace('低体温症注意', '低体温症危険')}[{x['id']}]"), doc)))

    def test_a_recommended_mountain_still_needs_its_own_line(self):
        doc = self.build(self.rows())
        x, note = doc["lines"]["skips"][0], doc["lines"]["hazard_note"]
        y = next(f for f in doc["facts"] if f["selected_by"] == "top")
        self.assertEqual(y["hazard_level"], "注意")
        mid = f"行くなら{y['name']}です。[{y['id']}]\n{x['text']}[{x['id']}]\n{note['text']}[{note['id']}]"
        self.assertEqual(codes(V.check(self.draft(mid, y["id"]), doc)), ["hazard_line_missing"])
        h = next(h for h in doc["lines"]["hazards"] if h["fact"] == y["id"])
        r = V.check(self.draft(mid.replace("\n", f"\n{h['text']}[{h['id']}]\n", 1), y["id"]), doc)
        self.assertTrue(r["ok"], r["errors"])

    def test_the_fallback_uses_the_line(self):
        doc = self.build(self.rows())
        x = doc["lines"]["skips"][0]
        for compact in (False, True):
            r = V.check(F.draft(doc, compact=compact), doc)
            self.assertTrue(r["ok"], r["errors"])
            self.assertIn(x["text"], r["final"])
            self.assertEqual([h["fact"] for h in doc["lines"]["hazards"] if h["text"] in r["final"]], [next(f["id"] for f in doc["facts"] if f["main_ok"])])
        self.assertIn(x["text"] + "この日は、危険信号が警戒以上の山は 4 座で、このうち危険は 3 座です。\n", V.check(F.draft(doc), doc)["final"])

    def test_the_fallback_with_named_mountains(self):
        doc = self.build(self.rows(), mountains=[NEAR[0], NEAR[3]])                     # 枠の中の山と、枠の外の山(警戒)
        for compact in (False, True):
            r = V.check(F.draft(doc, compact=compact), doc)
            self.assertTrue(r["ok"], r["errors"])
        t = V.check(F.draft(doc), doc)["final"]
        h = {f["mountain_id"]: line_for(doc, f["id"])["text"] for f in doc["facts"] if f["named"]}
        self.assertNotIn(h[NEAR[0]], t)                                                  # まとめの文で言っている
        self.assertIn(h[NEAR[3]], t)                                                     # まとめの文にいない名指しの山は、山ごとの文

    def test_a_brief_without_the_line_still_works(self):
        doc = self.build(self.rows())
        del doc["lines"]["skips"]
        self.assertTrue(B.is_current(doc))
        self.assertEqual(brief_schema_errors(doc), [])
        self.assertTrue(V.check(F.draft(doc), doc)["ok"])


class VoiceExample(unittest.TestCase):
    def test_the_example_for_skip_questions_passes(self):
        """docs/answer-voice.md の、見送りを聞かれたときの手本(作り物の強風危険)。"""
        def edit(d):
            for mid in ("m002", "m003"):
                make_hazard(mid, DAY, "危険")(d)
        doc = build(base_with_shelf(self, edit=edit), question="今週末は見送ったほうがいい山はある?")
        text = (ROOT / "docs" / "answer-voice.md").read_text(encoding="utf-8")
        example = text.split("### 見送りを聞かれたときの手本", 1)[1].split("```", 2)[1].strip("\n") + "\n"
        r = V.check(example, doc)
        self.assertTrue(r["ok"], r["errors"])
        self.assertLess(r["final"].index("危険信号が出ています"), r["final"].index("行くなら"))
        self.assertIn(doc["lines"]["skips"][0]["text"], r["final"])
        self.assertFalse(any(h["text"] in r["final"] for h in doc["lines"]["hazards"]))


if __name__ == "__main__":
    unittest.main()
