"""答える側の資料(brief)・照合(verify)・控えの文。段階 2 の受け入れ条件(開発指示書 8 章)を 1 つずつ。通信しない。
見本の棚は tests/fixtures/shelf/(ヤマビヨリの記録済みの入力から今の collect/ で作ったもの。値は本物の今の予報ではない)。"""
import json
import unittest
from unittest import mock

from concierge_helpers import NOW, QUESTION, base_with_shelf, build, edit_json, fact, line_for, make_hazard

from collect.common import schema_errors
from helpers import tmpdir
from concierge import brief as B
from concierge import fallback as F
from concierge import verify as V
from concierge.common import parse_now


def good_draft(doc):
    """見本の棚の値で手で書いた、正しい下書き(今週末・土曜の八ヶ岳と日曜の谷川岳)。"""
    L = doc["lines"]
    y1, y4 = fact(doc, "八ヶ岳", "2026-10-17"), fact(doc, "谷川岳", "2026-10-18")
    return "\n".join([
        f"今週末なら、土曜の八ヶ岳(赤岳)がいちばんのおすすめです。[{y1['id']}]",
        f"{L['data_time']['text']}[{L['data_time']['id']}]",
        f"{L['coverage']['text']}[{L['coverage']['id']}]",
        "",
        f"土曜の八ヶ岳(赤岳)は90.4点で、稜線風速は5.4 m/s、雲量(較正後)は約32 %の見込みです。[{y1['id']}]",
        f"{line_for(doc, y1['id'])['text']}[{line_for(doc, y1['id'])['id']}]",
        f"日曜なら谷川岳が84.9点で、危険信号は出ていません。[{y4['id']}]",
        "横岳という名前の由来には、いくつかの説があるといわれます。",
        f"{doc['gaps'][0]['text']}[{doc['gaps'][0]['id']}]",
        "",
        f"{L['attribution']['text']}[{L['attribution']['id']}]",
        "",
        f"[おすすめ] {y1['id']}, {y4['id']}",
    ]) + "\n"


def codes(res):
    return sorted({e["code"] for e in res["errors"]})


class Brief(unittest.TestCase):
    def setUp(self):
        self.base = base_with_shelf(self)

    def test_schema_and_candidates(self):
        doc = build(self.base)
        self.assertEqual(schema_errors(doc, "biyori-brief"), [])
        self.assertEqual([d["date"] for d in doc["when"]["days"]], ["2026-10-17", "2026-10-18"])
        self.assertEqual([(f["id"], f["name"], f["rank"]) for f in doc["facts"]],
                         [("Y001", "八ヶ岳(赤岳)", 1), ("Y002", "横岳", 2), ("Y003", "谷川岳", 3),
                          ("Y004", "谷川岳", 1), ("Y005", "八ヶ岳(赤岳)", 2), ("Y006", "横岳", 3)])
        y = fact(doc, "八ヶ岳", "2026-10-17")
        self.assertIn("5.4 m/s", y["say"])
        self.assertIn("約5 m/s", y["say"])
        self.assertIn("直線で約125km", y["say"])
        self.assertEqual(y["lead_days"], 2)
        self.assertTrue(y["main_ok"])
        self.assertEqual(doc["candidates"][0]["counts"]["no_forecast"], 73)
        self.assertEqual(len(doc["plans"]), 6)
        self.assertIn("76 座のうち 3 座", doc["lines"]["coverage"]["text"])
        self.assertIn("10月15日(木) 5:00 時点", doc["lines"]["data_time"]["text"])
        self.assertIsNone(doc["lines"]["lead_time"])
        self.assertEqual(doc["cards"], [])
        self.assertIn("no_safety_info", [g["kind"] for g in doc["gaps"]])
        self.assertIn("no_stars_creatures", [g["kind"] for g in doc["gaps"]])

    def test_same_input_same_bytes(self):
        a = B.save(build(self.base), self.base)[0].read_bytes()
        b = B.save(build(self.base), self.base)[0].read_bytes()
        self.assertEqual(a, b)
        doc = json.loads(a)
        self.assertNotIn(str(self.base), a.decode("utf-8"))
        self.assertTrue(doc["id"].startswith("b20261015-080000-"))
        c = build(self.base, now="2026-10-15T08:01:00+09:00")
        self.assertNotEqual(c["id"], doc["id"])

    def test_named_mountains_out_of_list_and_range(self):
        doc = build(self.base, question="週末の登山は横岳と見本山、どっちがいい?", mountains=["横岳", "見本山", "蔵王山"])
        kinds = {g["kind"]: g["text"] for g in doc["gaps"]}
        self.assertIn("見本山", kinds["named_not_in_list"])
        self.assertIn("蔵王山", kinds["named_out_of_range"])
        self.assertTrue(all(f["named"] for f in doc["facts"] if f["name"] == "横岳"))

    def test_named_mountain_outside_the_top_is_kept(self):
        cfg = B.config()
        cfg["concierge"]["brief"].update(top_per_day=1, main_ok_min=0)
        with mock.patch("concierge.brief.config", return_value=cfg):
            doc = build(self.base, mountains=["横岳"])
        names = [(f["name"], f["date"], f["selected_by"]) for f in doc["facts"]]
        self.assertIn(("横岳", "2026-10-17", "named"), names)
        self.assertEqual(doc["candidates"][0]["counts"]["outside_top"], 2)
        self.assertEqual(doc["candidates"][0]["outside_top_names"], ["谷川岳"])      # 名指しの横岳は外した一覧に入れない

    def test_main_ok_mountains_are_filled_from_outside_the_top(self):
        base = base_with_shelf(self, edit=make_hazard("m002", "2026-10-17", "危険"))
        cfg = B.config()
        cfg["concierge"]["brief"].update(top_per_day=1, main_ok_min=2)
        with mock.patch("concierge.brief.config", return_value=cfg):
            doc = build(base)
        sat = [(f["name"], f["selected_by"], f["main_ok"]) for f in doc["facts"] if f["date"] == "2026-10-17"]
        self.assertEqual(sat, [("八ヶ岳(赤岳)", "top", False), ("横岳", "main_fill", True), ("谷川岳", "main_fill", True)])
        self.assertEqual(doc["candidates"][0]["counts"]["outside_top"], 0)
        sun = [f["selected_by"] for f in doc["facts"] if f["date"] == "2026-10-18"]
        self.assertEqual(sun, ["top", "main_fill"])            # 1 座目が主役にできるので、足すのは 1 座

    def test_region_interest_origin(self):
        doc = build(self.base, region=["北陸信越", "九州"], interest=["stars", "hiking"], origin="どこか")
        self.assertEqual(doc["facts"], [])
        kinds = [g["kind"] for g in doc["gaps"]]
        for k in ("unknown_region", "interest_not_mountain", "unknown_origin", "no_mountain_above"):
            self.assertIn(k, kinds)
        self.assertEqual(doc["candidates"][0]["counts"]["region"], 3)

    def test_hazard_marks_main_ng_but_keeps_the_mountain(self):
        base = base_with_shelf(self, edit=make_hazard("m002", "2026-10-17", "危険"))
        doc = build(base)
        y = fact(doc, "八ヶ岳", "2026-10-17")
        self.assertFalse(y["main_ok"])
        self.assertIn("hazard_hard", y["main_ng"])
        self.assertNotIn(y["id"], [p["main"]["fact"] for p in doc["plans"]])
        self.assertIn("強風危険", line_for(doc, y["id"])["text"])

    def test_stale_shelf_says_so(self):
        doc = build(self.base, now="2026-10-16T08:00:00+09:00")
        self.assertTrue(doc["shelf"]["stale"])
        self.assertIn("27 時間前の古い予報", doc["lines"]["data_time"]["text"])

    def test_far_day_needs_lead_time_line(self):
        def older(d):
            edit_json(d / "manifest.json", lambda m: m["agents"]["yamabiyori"].update(data_time="2026-10-13T05:00:00+09:00"))
        base = base_with_shelf(self, edit=older)
        doc = build(base, now="2026-10-13T08:00:00+09:00")
        self.assertIn("4 日先", doc["lines"]["lead_time"]["text"])
        self.assertFalse(fact(doc, "八ヶ岳", "2026-10-17")["reliable"])

    def test_day_outside_the_forecast(self):
        doc = build(self.base, when="来週末")
        self.assertEqual(doc["facts"], [])
        self.assertIn("day_not_in_forecast", [g["kind"] for g in doc["gaps"]])

    def test_no_shelf_and_broken_shelf(self):
        for label, base in (("none", base_with_shelf(self, shelf=False)),
                            ("broken", base_with_shelf(self, edit=lambda d: (d / "manifest.json").write_text("{", encoding="utf-8"))),
                            ("bad_proposals", base_with_shelf(self, edit=lambda d: edit_json(d / "proposals" / "yamabiyori.json",
                                                                                              lambda p: p.update(schema="x"))))):
            with self.subTest(label):
                doc = build(base)
                self.assertFalse(doc["shelf"]["available"])
                self.assertEqual(doc["facts"], [])
                self.assertEqual(doc["gaps"][0]["text"], "山の予報は今回使えませんでした。")
                self.assertIsNone(doc["lines"]["data_time"])
                r = V.check(F.draft(doc), doc)
                self.assertTrue(r["ok"], r["errors"])
                self.assertTrue(r["final"].startswith("山の予報は今回使えませんでした。"))

    def test_cards_mechanism_with_a_fictitious_card(self):
        d = tmpdir(self, "biyori-cards-")
        (d / "k1.yaml").write_text("id: test-card-1\ntargets: {mountains: [m003]}\ntext: これはテスト用の作り物のカードです。\n"
                                   "source: {name: テストの出典, url: 'https://example.invalid/'}\nchecked: '2026-10-01'\n", encoding="utf-8")
        (d / "broken.yaml").write_text("id: x\n", encoding="utf-8")
        base = base_with_shelf(self)
        with mock.patch.dict("os.environ", {"BIYORI_CONCIERGE_CARDS_DIR": str(d)}):
            doc = build(base)
        self.assertEqual([(k["id"], k["card_id"]) for k in doc["cards"]], [("K001", "test-card-1")])

    def test_real_cards_are_zero(self):
        from concierge.common import DATA
        self.assertEqual(list((DATA / "cards").glob("*.yaml")), [])


class Verify(unittest.TestCase):
    def setUp(self):
        self.base = base_with_shelf(self)
        self.doc = build(self.base)

    def check(self, text):
        return V.check(text, self.doc)

    def test_good_draft_passes_and_marks_are_removed(self):
        r = self.check(good_draft(self.doc))
        self.assertTrue(r["ok"], r["errors"])
        self.assertNotRegex(r["final"], r"\[[YLKG]\d+\]")
        self.assertNotIn("[おすすめ]", r["final"])
        self.assertIn("横岳という名前の由来", r["final"])
        r = self.check(good_draft(self.doc).replace("約32 %の見込みです。[Y001]", "約32 %の見込みです。[Y001] 横浜から直線で約125kmです。[Y001]"))
        self.assertTrue(r["ok"], r["errors"])
        self.assertIn("約32 %の見込みです。横浜から直線で約125kmです。\n", r["final"])     # 印の後ろの空白は残さない
        self.assertTrue(r["final"].startswith("今週末なら、土曜の八ヶ岳(赤岳)がいちばんのおすすめです。\n"))

    def test_added_number_date_and_mountain_fail(self):
        g = good_draft(self.doc)
        cases = {
            "number_mismatch": g.replace("稜線風速は5.4 m/s", "稜線風速は13 m/s"),
            "date_mismatch": g.replace("土曜の八ヶ岳(赤岳)は90.4点", "10月20日の八ヶ岳(赤岳)は90.4点"),
            "number_unmarked": g.replace("横岳という名前の由来には", "標高3000mの横岳という名前の由来には"),
            "mountain_not_in_brief": g.replace("横岳という名前の由来には", "丹沢山という名前の由来には"),
            "unknown_mountain": g.replace("横岳という名前の由来には", "見本岳という名前の由来には"),
            "mountain_unmarked": g.replace("日曜なら谷川岳が84.9点", "日曜なら谷川岳が八ヶ岳より上の84.9点"),
        }
        for code, text in cases.items():
            with self.subTest(code):
                r = self.check(text)
                self.assertFalse(r["ok"])
                self.assertIn(code, codes(r))

    def test_hazard_line_removed_fails(self):
        y1 = fact(self.doc, "八ヶ岳", "2026-10-17")
        h = line_for(self.doc, y1["id"])
        r = self.check(good_draft(self.doc).replace(f"{h['text']}[{h['id']}]\n", ""))
        self.assertIn("hazard_line_missing", codes(r))

    def test_altered_fixed_line_fails(self):
        L = self.doc["lines"]["data_time"]
        r = self.check(good_draft(self.doc).replace(L["text"], L["text"].replace("時点のもの", "時点の最新")))
        self.assertIn("line_altered", codes(r))
        self.assertIn("line_missing", codes(r))

    def test_safety_without_basis_fails_but_cannot_judge_passes(self):
        g = good_draft(self.doc)
        for bad in ("アイゼンを持っていけば安心して歩けます。", "初心者でも登りやすい山です。", "この時期は凍結に気をつけましょう。"):
            with self.subTest(bad):
                r = self.check(g.replace("横岳という名前の由来には、いくつかの説があるといわれます。", bad))
                self.assertIn("safety_without_basis", codes(r))
        y1 = fact(self.doc, "八ヶ岳", "2026-10-17")["id"]                    # 危険信号(注意)つきの事実
        r = self.check(g.replace("横岳という名前の由来には、いくつかの説があるといわれます。", f"八ヶ岳(赤岳)は90.4点なので安全に登れます。[{y1}]"))
        self.assertIn("safety_assertion", codes(r))                         # 安全の言い切りは危険信号の印では通さない
        r = self.check(g.replace("横岳という名前の由来には、いくつかの説があるといわれます。", f"八ヶ岳(赤岳)は低体温症注意なので防寒に気をつけます。[{y1}]"))
        self.assertTrue(r["ok"], r["errors"])                               # 危険信号の事実の印があれば、注意の文は通す(作業指示書 6.2)
        ok = "凍結や積雪があるかどうかは、この予報からは判断できません。"
        r = self.check(g.replace("横岳という名前の由来には、いくつかの説があるといわれます。", ok))
        self.assertTrue(r["ok"], r["errors"])

    def test_weather_word_without_mark_fails(self):
        r = self.check(good_draft(self.doc).replace("横岳という名前の由来には、いくつかの説があるといわれます。", "週末は晴れて気持ちのよい山歩きになりそうです。"))
        self.assertIn("weather_unmarked", codes(r))

    def test_general_knowledge_passes(self):
        r = self.check(good_draft(self.doc))
        self.assertTrue(r["ok"], r["errors"])

    def test_pick_rules(self):
        y2 = fact(self.doc, "横岳", "2026-10-17")
        g = good_draft(self.doc)
        r = self.check(g.replace("[おすすめ] ", "[おすすめ] Y999, "))
        self.assertIn("pick_unknown", codes(r))
        r = self.check(g.rsplit("[おすすめ]", 1)[0])
        self.assertIn("picks_missing", codes(r))
        r = self.check(g.replace("横岳という名前の由来には、いくつかの説があるといわれます。", f"土曜の横岳もおすすめです。[{y2['id']}]"))
        self.assertIn("pick_undeclared", codes(r))
        # 見送りの文は、おすすめの語(「いちばん」など)があっても止めない(通しの試しで止めすぎた形)
        r = self.check(g.replace("横岳という名前の由来には、いくつかの説があるといわれます。",
                                 f"点数がいちばん高い横岳は、今回は見送るのがよさそうです。[{y2['id']}]"))
        self.assertTrue(r["ok"], r["errors"])

    def test_cannot_recommend_a_mountain_marked_not_main(self):
        base = base_with_shelf(self, edit=make_hazard("m002", "2026-10-17", "危険"))
        doc = build(base)
        r = V.check(good_draft(doc), doc)
        self.assertIn("pick_not_allowed", codes(r))

    def test_far_day_without_lead_time_fails(self):
        def older(d):
            edit_json(d / "manifest.json", lambda m: m["agents"]["yamabiyori"].update(data_time="2026-10-13T05:00:00+09:00"))
        base = base_with_shelf(self, edit=older)
        doc = build(base, now="2026-10-13T08:00:00+09:00")
        g = good_draft(doc).replace("90.4点で、稜線風速", "90.4点(4日先の予報)で、稜線風速")
        r = V.check(g, doc)
        self.assertIn("lead_time_missing", codes(r))
        L = doc["lines"]["lead_time"]
        r = V.check(g.replace("\n\n気象データ", f"\n{L['text']}[{L['id']}]\n\n気象データ"), doc)
        self.assertTrue(r["ok"], r["errors"])

    def test_whole_answer_checks(self):
        g = good_draft(self.doc)
        rep = "横岳という名前の由来には、いくつかの説があるといわれます。"
        y1 = fact(self.doc, "八ヶ岳", "2026-10-17")["id"]
        cases = {
            "internal_word": "棚の予報をもとにまとめました。",
            "question_in_answer": "どちらに行きますか?",
            "offer_in_answer": "ほかの日も調べましょうか。",
            "english_note": "Note: this is a draft answer.",
            "lodging_name": "見本山荘に泊まるのも一案です。",
            "score_across_biyori": f"八ヶ岳(赤岳)は90.4点で、星空の点よりも高いです。[{y1}]",
            "url_unmarked": "くわしくは https://example.invalid/ を見ます。",
        }
        for code, text in cases.items():
            with self.subTest(code):
                r = self.check(g.replace(rep, text))
                self.assertIn(code, codes(r))
        with mock.patch.dict(self.doc["limits"], {"max_chars": 100}):
            self.assertIn("too_long", codes(self.check(g)))

    def test_the_example_in_answer_voice_passes(self):
        from helpers import ROOT
        text = (ROOT / "docs" / "answer-voice.md").read_text(encoding="utf-8")
        example = text.split("## 6.", 1)[1].split("```", 2)[1].strip("\n") + "\n"
        r = self.check(example)
        self.assertTrue(r["ok"], r["errors"])

    def test_no_pick_answer_passes(self):
        L = self.doc["lines"]
        text = "\n".join(["今週末は、見送るのがよさそうです。", f"{L['data_time']['text']}[{L['data_time']['id']}]",
                          f"{L['coverage']['text']}[{L['coverage']['id']}]", f"{L['attribution']['text']}[{L['attribution']['id']}]",
                          "[おすすめ] なし"])
        r = self.check(text)
        self.assertTrue(r["ok"], r["errors"])


class Rewrites(unittest.TestCase):
    def test_third_failure_gives_the_fallback_which_passes(self):
        base = base_with_shelf(self)
        doc = build(base)
        bad = good_draft(doc).replace("稜線風速は5.4 m/s", "稜線風速は13 m/s")
        now = parse_now(NOW)
        r1, r2 = V.run(bad, doc["id"], base, now), V.run(bad, doc["id"], base, now)
        self.assertEqual((r1["status"], r2["status"]), ("FAIL", "FAIL"))
        self.assertEqual((r1["left"], r2["left"]), (2, 1))
        r3 = V.run(bad, doc["id"], base, now)
        self.assertEqual(r3["status"], "FALLBACK")
        self.assertTrue(V.check(F.draft(doc), doc)["ok"])
        self.assertEqual(r3["text"], V.check(F.draft(doc), doc)["final"])
        rows = [json.loads(x) for x in (base / "logs" / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["result"] for x in rows], ["不合格", "不合格", "控え"])
        self.assertEqual(rows[-1]["rewrites"], 2)
        self.assertIn("number_mismatch", rows[-1]["failed"])
        self.assertNotIn("稜線風速", json.dumps(rows, ensure_ascii=False))       # 答えの本文は記録しない
        build(base)                                                              # 同じ資料を作り直すと数え直す
        self.assertEqual(V.run(good_draft(doc), doc["id"], base, now)["status"], "PASS")

    def test_fallback_passes_on_every_fixture(self):
        variants = {
            "fresh": (None, {}),
            "stale": (None, {"now": "2026-10-16T08:00:00+09:00"}),
            "hazard": (make_hazard("m002", "2026-10-17", "危険"), {}),
            "caution_only": (make_hazard("m001", "2026-10-18", "注意", "thunder"), {}),
            "no_eligible": (None, {"when": "2026-10-19"}),
            "named_only": (None, {"mountains": ["谷川岳", "見本山"], "region": ["北陸信越"]}),
            "far": (lambda d: edit_json(d / "manifest.json", lambda m: m["agents"]["yamabiyori"].update(data_time="2026-10-13T05:00:00+09:00")),
                    {"now": "2026-10-13T08:00:00+09:00"}),
            "next_weekend": (None, {"when": "来週末"}),
        }
        for label, (edit, kw) in variants.items():
            with self.subTest(label):
                base = base_with_shelf(self, edit=edit)
                doc = build(base, **kw)
                r = V.check(F.draft(doc), doc)
                self.assertTrue(r["ok"], (label, r["errors"]))
                self.assertIn(doc["lines"]["attribution"]["text"], r["final"])


if __name__ == "__main__":
    unittest.main()
