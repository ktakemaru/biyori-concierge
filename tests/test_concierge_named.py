"""山を名指しした質問の答え方(利用者の決定 2026-11-25): 名指しの山が主役・名指しでない山は並べない・値の無い山・76 座に無い山・古い予報。通信しない。
棚は見本(3 座)に作り物の山の日を足したもの(値は本物の予報ではない)。"""
import unittest
from unittest import mock

from concierge_helpers import base_with_shelf, build, edit_json, fact, line_for
from test_concierge_frames import synthetic
from test_concierge_wording import DAY, both, peaks

from concierge import brief as B
from concierge import fallback as F
from concierge import named as N
from concierge import stop_hook as SH
from concierge import verify as V
from concierge.common import brief_schema_errors, dump_json, write_text

STALE_NOW = "2026-10-16T08:00:00+09:00"
LOW = "m027"                                  # 点数だけの行にする山(大山)
# 鍋割山と塔ノ岳は同じ点・同じ段階、高尾山は危険信号なし、丹沢山は危険
ROWS = [("m026", 95.0, {"wind": "注意"}, 5.0), ("m022", 95.0, {"cold": "注意"}, 5.0), ("m029", 95.0, {}, 4.0),
        ("m023", 95.0, {"wind": "危険"}, 20.0), (LOW, 40.0, {}, 4.0)]
PEAKS = {"m026": 8.1, "m022": 7.9, "m029": 5.0, "m023": 20.0}


def score_only(mid, level=None):
    """作り物: 山 mid を、点数だけの行(値が無い)にする。"""
    def fn(shelf_dir):
        def f(d):
            for p in d["proposals"]:
                if p["place"]["site_ref"].endswith(mid) and p["time_window"]["start"].startswith(DAY):
                    p["evidence"] = []
                    p["constraints"] = [{"kind": "hazard", "hazard": None, "level": level, "text": level, "hard": True}] if level else []
        edit_json(shelf_dir / "proposals" / "yamabiyori.json", f)
    return fn


class Base(unittest.TestCase):
    def doc(self, names, rows=ROWS, level=None, **kw):
        self.base = base_with_shelf(self, edit=both(synthetic(rows), peaks(PEAKS), score_only(LOW, level)))
        kw.setdefault("when", DAY)
        d = build(self.base, mountains=names, **kw)
        self.assertEqual(brief_schema_errors(d), [])
        return d

    def final(self, doc, compact=False):
        r = V.check(F.draft(doc, compact=compact), doc)
        self.assertTrue(r["ok"], r["errors"])
        return r["final"]

    def check(self, doc, text, picks="なし"):
        L = doc["lines"]
        head = "\n".join(f"{L[k]['text']}[{L[k]['id']}]" for k in ("data_time", "coverage"))
        return {e["code"] for e in V.check(f"{head}\n{text}\n{L['attribution']['text']}[{L['attribution']['id']}]\n[おすすめ] {picks}", doc)["errors"]}

    def y(self, doc, name, day=DAY):
        return f"[{fact(doc, name, day)['id']}]"


class Fallback(Base):
    def test_two_mountains_without_a_difference(self):
        doc = self.doc(["鍋割山", "塔ノ岳"])
        t = self.final(doc)
        first = t.split("\n")[0]
        self.assertIn("点数と危険信号の段階では差がつきません", first)
        self.assertIn("鍋割山", first)
        self.assertIn("塔ノ岳", first)
        self.assertIn("日中ピークの風速の差は 0.2 m/s で、差はわずかです。", t)
        self.assertIn("\n1. ", t)
        self.assertIn("\n2. ", t)
        for other in ("丹沢山", "谷川岳", "八ヶ岳"):
            self.assertNotIn(other, t)
        self.assertIn("高尾山には、危険信号が出ていません。", t)                   # 名指しの全部に危険信号が出ているので、最後に 1 文だけ
        self.assertEqual(t.count("高尾山"), 1)
        for name in ("鍋割山", "塔ノ岳"):
            f = fact(doc, name, DAY)
            self.assertIn(line_for(doc, f["id"])["text"], t)
            for word in ("稜線風速は", "日中ピークの風速は", "体感温度(稜線)は"):
                self.assertIn(word, t)

    def test_three_mountains_have_one_winner(self):
        doc = self.doc(["高尾山", "鍋割山", "塔ノ岳"])
        t = self.final(doc)
        self.assertTrue(t.startswith("お尋ねの山の中では、10月17日(土)の高尾山がおすすめです。"), t)
        self.assertIn("日中ピークの風速の差は 3.1 m/s です。", t)                  # 差のいちばん大きい組(鍋割山と高尾山)
        self.assertNotIn("なお、", t)                                              # 危険信号の無い名指しの山があるので、ほかの山には触れない
        self.assertIn("危険信号は出ていません。", t)

    def test_a_mountain_with_a_hard_hazard_does_not_win(self):
        t = self.final(self.doc(["丹沢山", "鍋割山"]))
        self.assertTrue(t.startswith("お尋ねの山の中では、10月17日(土)の鍋割山がおすすめです。"), t)
        self.assertIn("危険信号が出ているため、今回は見送りとしています。", t)

    def test_nothing_to_recommend(self):
        doc = self.doc(["丹沢山", "大山"])
        t = self.final(doc)
        self.assertTrue(t.startswith("10月17日(土)は、お尋ねの山の中に、条件のそろった山がありません。"), t)
        self.assertTrue(F.draft(doc).rstrip().endswith("[おすすめ] なし"))

    def test_score_only_mountain_is_told_honestly(self):
        t = self.final(self.doc(["高尾山", "大山"], level="警戒以上"))
        self.assertIn("40点で、基準の70点に届いていません。点数が低く、くわしい値はありません。", t)
        self.assertIn("くわしい値がないため、風や体感は比べられません。", t)
        self.assertIn("危険信号(警戒以上。種類は今回の予報に含まれていません)が出ています。", t)

    def test_mountain_not_in_the_list_is_told_first_and_the_rest_is_a_description(self):
        for missing in ("開聞岳", "蔵王山"):                                       # 76 座に無い山・250km より遠い山
            with self.subTest(missing):
                t = self.final(self.doc(["高尾山", missing]))
                self.assertIn(missing, t.split("\n")[0])
                self.assertIn("高尾山は、おすすめの候補です。", t.split("\n")[1])
                self.assertNotIn("\n1. ", t)                                       # 1 座だけなので、比べない
                self.assertNotIn("差", t)

    def test_no_forecast_for_any_named_mountain(self):
        doc = self.doc(["開聞岳", "大山(鳥取)"])
        t = self.final(doc)
        self.assertTrue(t.startswith("「開聞岳」は"), t)
        self.assertNotIn("高尾山", t)

    def test_four_or_more_are_all_written(self):
        names = ["高尾山", "鍋割山", "塔ノ岳", "丹沢山", "大山", "谷川岳"]
        t = self.final(self.doc(names))
        for n in names:
            self.assertIn(n, t)

    def test_old_forecast(self):
        t = self.final(self.doc(["高尾山", "鍋割山"], now=STALE_NOW))
        self.assertIn("古い予報です", t.split("\n")[0])
        self.assertEqual(t.split("\n")[1], "古い予報では、お尋ねの山の中では、10月17日(土)の高尾山が候補です。")
        self.assertNotIn("おすすめ", t)
        t = self.final(self.doc(["高尾山", "開聞岳"], now=STALE_NOW))
        self.assertIn("開聞岳", t.split("\n")[1])                                  # 時点 → 予報の無い山 → 結論
        self.assertEqual(t.split("\n")[2], "古い予報では、10月17日(土)の高尾山が候補です。")

    def test_every_shape_passes_the_checks(self):
        """座数 × 日 × 新旧 × 短い形: 控えの文は必ず照合に合格する。"""
        for names in (["高尾山"], ["鍋割山", "塔ノ岳"], ["高尾山", "鍋割山", "大山"], ["高尾山", "鍋割山", "塔ノ岳", "丹沢山", "大山", "谷川岳"],
                      ["大山"], ["丹沢山"], ["高尾山", "開聞岳", "蔵王山"], ["開聞岳"], ["m029", "高尾山"]):
            for when in (DAY, "今週末", "2026-10-12..2026-10-19", "2026-10-19", "来週末"):
                for now in ("2026-10-15T08:00:00+09:00", STALE_NOW):
                    doc = self.doc(names, when=when, now=now)
                    for compact in (False, True):
                        with self.subTest(names=names, when=when, now=now, compact=compact):
                            r = V.check(F.draft(doc, compact=compact), doc)
                            self.assertEqual({e["code"] for e in r["errors"]} - ({"too_long"} if not compact else set()), set(), r["errors"][:3])

    def test_without_a_shelf_it_is_as_before(self):
        base = base_with_shelf(self, shelf=False)
        doc = build(base, mountains=["高尾山", "鍋割山"])
        self.assertFalse(N.is_named(doc))
        self.assertTrue(V.check(F.draft(doc), doc)["ok"])

    def test_the_same_mountain_twice_is_one(self):
        doc = self.doc(["m029", "高尾山"])
        self.assertEqual(len(N.facts(doc)), 1)


class Verify(Base):
    def setUp(self):
        self.d = self.doc(["鍋割山", "塔ノ岳"])
        self.a, self.b = self.y(self.d, "鍋割山"), self.y(self.d, "塔ノ岳")
        self.t = self.y(self.d, "高尾山")
        self.good = f"鍋割山と塔ノ岳は、どちらも95点で、差がつきません。{self.a}{self.b}"
        self.assertEqual(self.check(self.d, self.good), set())

    def test_missing_named_mountain_is_stopped(self):
        self.assertIn("named_missing", self.check(self.d, f"鍋割山は95点です。{self.a}"))

    def test_other_mountains_are_stopped(self):
        for s in (f"高尾山も95点です。{self.t}", "高尾山という名前の由来には、説があるといわれます。"):
            with self.subTest(s):
                self.assertIn("named_other", self.check(self.d, self.good + "\n" + s))

    def test_fixed_lines_with_other_mountains_are_stopped(self):
        x = self.d["lines"]["skips"][0]
        self.assertIn("named_other", self.check(self.d, f"{self.good}\n{x['text']}[{x['id']}]"))
        h = line_for(self.d, fact(self.d, "丹沢山", DAY)["id"])
        self.assertIn("named_other", self.check(self.d, f"{self.good}\n{h['text']}[{h['id']}]"))

    def test_the_exception_is_one_last_sentence(self):
        calm = f"なお、この日は高尾山には危険信号が出ていません。{self.t}"
        self.assertEqual(self.check(self.d, f"{self.good}\n{calm}"), set())
        self.assertIn("named_other", self.check(self.d, f"{calm}\n{self.good}"))                         # 最後でない
        self.assertIn("named_other", self.check(self.d, f"{self.good}\n{calm}\n{calm}"))                 # 2 文
        for bad in (f"なお、高尾山は95点で、危険信号が出ていません。{self.t}", f"高尾山をおすすめします。{self.t}",
                    f"なお、丹沢山には危険信号が出ていません。{self.y(self.d, '丹沢山')}"):              # 点数を足す・すすめる・事実と合わない
            with self.subTest(bad):
                self.assertIn("named_other", self.check(self.d, f"{self.good}\n{bad}"))

    def test_the_exception_needs_hazards_on_every_named_mountain(self):
        d = self.doc(["高尾山", "塔ノ岳"], rows=ROWS + [("m028", 94.0, {}, 4.0)])
        calm = next(f for f in d["facts"] if f["mountain_id"] == "m028")
        text = f"高尾山と塔ノ岳は、どちらも95点です。{self.y(d, '高尾山')}{self.y(d, '塔ノ岳')}"
        self.assertEqual(self.check(d, text), set())
        self.assertIn("named_other", self.check(d, f"{text}\nなお、この日は{calm['name']}には危険信号が出ていません。[{calm['id']}]"))

    def test_a_mountain_without_a_forecast_must_be_told(self):
        d = self.doc(["高尾山", "開聞岳"])
        g = N.gaps(d)[0]
        text = f"高尾山は95点です。{self.y(d, '高尾山')}"
        self.assertIn("named_missing", self.check(d, text))
        self.assertEqual(self.check(d, f"{g['text']}[{g['id']}]\n{text}"), set())

    def test_questions_without_named_mountains_are_unchanged(self):
        d = self.doc(None)
        self.assertEqual(d["rules"][:len(B.RULES)], B.RULES)
        self.assertEqual(self.check(d, f"高尾山と鍋割山は、どちらも95点です。{self.y(d, '高尾山')}{self.y(d, '鍋割山')}"), set())
        self.assertIn("いちばんのおすすめは、", F.draft(d))

    def test_rules_of_the_brief_are_replaced(self):
        rules = self.d["rules"]
        self.assertTrue(rules[0].startswith("答えの形(山を名指しした質問)"))
        self.assertFalse(any(r.startswith(("答えの形:", "見送る山の危険信号は、")) for r in rules))
        self.assertEqual(len([r for r in B.RULES if r.startswith(("答えの形:", "見送る山の危険信号は、"))]), 2)      # 替える 2 つが、もとの決まりにある


class Hook(Base):
    def turn(self, *docs, last=None):
        calls = [{"name": "Bash", "input": {"command": "python -X utf8 -m concierge brief --question x"}, "result": d["id"]} for d in docs]
        calls.append({"name": "Bash", "input": {"command": f"python -X utf8 -m concierge verify /tmp/d.txt --brief {(last or docs[-1])['id']}"}, "result": "ok"})
        return {"prompt": "どっち?", "key": "k", "calls": calls}

    def why(self, doc, text, *others):
        write_text(self.base / "last_answer.json", dump_json({"brief": doc["id"], "at": STALE_NOW, "text": text}))
        return SH.decide(text, self.turn(*others, doc), self.base, SH.cfg())["why"]

    def test_stops_and_passes(self):
        doc = self.doc(["鍋割山", "塔ノ岳"])
        self.assertEqual(self.why(doc, "鍋割山は95点です。"), "named")
        self.assertEqual(self.why(doc, "鍋割山と塔ノ岳は95点です。高尾山も95点です。"), "named")
        self.assertEqual(self.why(doc, "鍋割山と塔ノ岳は95点です。なお、この日は高尾山には危険信号が出ていません。"), "ok")
        for compact in (False, True):
            self.assertEqual(self.why(doc, self.final(doc, compact)), "ok")
        self.assertIn("named", SH.cfg()["reasons"])

    def test_the_other_brief_of_the_turn_is_not_applied(self):
        """1 回に資料が 2 つ(名指しあり・なし): 名指しの決まりを、もう一方の答えに当てない。"""
        named = self.doc(["鍋割山", "塔ノ岳"])
        plain = build(self.base, when=DAY)
        self.assertEqual(self.why(plain, "高尾山は95点です。", named), "ok")
        self.assertEqual(self.why(named, "鍋割山と塔ノ岳は95点です。高尾山は95点です。", plain), "named")


class Run(Base):
    def test_run_gives_the_named_fallback(self):
        doc = self.doc(["鍋割山", "塔ノ岳"])
        bad = f"鍋割山は95点です。{self.y(doc, '鍋割山')}\n[おすすめ] なし"
        import datetime as dt
        now = dt.datetime.fromisoformat("2026-10-15T08:00:00+09:00")
        with mock.patch("concierge.verify.max_rewrites", return_value=0):
            r = V.run(bad, doc["id"], self.base, now)
        self.assertEqual(r["status"], "FALLBACK")
        self.assertIn("差がつきません", r["text"])
        self.assertEqual(SH.decide(r["text"], Hook.turn(self, doc), self.base, SH.cfg())["why"], "ok")


if __name__ == "__main__":
    unittest.main()
