"""古い予報のときの答え方(案。2026-11-25): 最初の文・言い切らない・新しくする方法・Stop フック。通信しない。
境目は config.yaml の collect.stale_after_hours(仮の値 12 時間)。"""
import unittest

from concierge_helpers import base_with_shelf, build, fact

from concierge import fallback as F
from concierge import stop_hook as SH
from concierge import verify as V
from concierge.common import config, dump_json, write_text

STALE_NOW = "2026-10-16T08:00:00+09:00"        # 見本の棚の予報の 27 時間あと
FRESH_NOW = "2026-10-15T08:00:00+09:00"


class Stale(unittest.TestCase):
    def setUp(self):
        self.base = base_with_shelf(self)
        self.doc = build(self.base, now=STALE_NOW)
        self.L = self.doc["lines"]
        self.y = fact(self.doc, "八ヶ岳", "2026-10-17")["id"]

    def m(self, key):
        return f"{self.L[key]['text']}[{self.L[key]['id']}]"

    def draft(self, first=None, conclusion=None, tail=None):
        first = self.m("data_time") if first is None else first
        conclusion = f"古い予報では、土曜の八ヶ岳(赤岳)が候補です。[{self.y}]" if conclusion is None else conclusion
        tail = [self.m("refresh"), self.m("attribution")] if tail is None else tail
        hazard = next((f"{h['text']}[{h['id']}]" for h in self.L["hazards"] if h["fact"] == self.y), "")
        lead = [self.m("lead_time")] if self.L["lead_time"] else []
        rest = [self.m("coverage"), hazard] + lead
        return "\n".join([first, conclusion] + [x for x in rest if x] + tail + [f"[おすすめ] {self.y}"])

    def codes(self, draft):
        return {e["code"] for e in V.check(draft, self.doc)["errors"]}

    def test_good_answer_passes(self):
        r = V.check(self.draft(), self.doc)
        self.assertTrue(r["ok"], r["errors"])
        self.assertTrue(r["final"].startswith(self.L["data_time"]["text"]))

    def test_conclusion_first_is_stopped(self):
        d = self.draft(first=f"土曜の八ヶ岳(赤岳)が候補です。[{self.y}]", conclusion=self.m("data_time"))
        self.assertIn("stale_first", self.codes(d))

    def test_assertions_are_stopped(self):
        for bad in (f"土曜の八ヶ岳(赤岳)をおすすめします。[{self.y}]", f"いちばんのおすすめは、土曜の八ヶ岳(赤岳)です。[{self.y}]",
                    f"行くなら、土曜の八ヶ岳(赤岳)です。[{self.y}]"):
            with self.subTest(bad):
                self.assertIn("stale_assertion", self.codes(self.draft(conclusion=bad)))

    def test_weak_words_pass(self):
        for good in (f"古い予報では、土曜の八ヶ岳(赤岳)が候補です。[{self.y}]", f"行くなら、土曜の八ヶ岳(赤岳)が候補です。[{self.y}]"):
            with self.subTest(good):
                self.assertNotIn("stale_assertion", self.codes(self.draft(conclusion=good)))

    def test_refresh_line_is_required_and_last(self):
        self.assertIn("line_missing", self.codes(self.draft(tail=[self.m("attribution")])))
        self.assertIn("stale_refresh_last", self.codes(self.draft(tail=[self.m("refresh"), f"八ヶ岳は候補です。[{self.y}]", self.m("attribution")])))

    def test_fresh_brief_is_unchanged(self):
        doc = build(base_with_shelf(self), now=FRESH_NOW)
        self.assertIsNone(doc["lines"]["refresh"])
        self.assertFalse(any("古い" in r for r in doc["rules"]))
        self.assertIn("いちばんのおすすめは、", F.draft(doc))

    def test_fallback_is_weak_and_passes(self):
        d = F.draft(self.doc)
        self.assertTrue(d.startswith(self.L["data_time"]["text"]))
        self.assertIn("古い予報では、", d)
        self.assertNotIn("おすすめは、", d)
        self.assertTrue(V.check(d, self.doc)["ok"], V.check(d, self.doc)["errors"])

    def test_boundary_is_the_config_constant(self):
        import datetime as dt
        hours = config()["collect"]["stale_after_hours"]
        data_time = dt.datetime.fromisoformat(self.doc["shelf"]["data_time"])
        for h, want in ((hours - 1, False), (hours, True)):
            now = (data_time + dt.timedelta(hours=h)).isoformat()
            self.assertEqual(build(base_with_shelf(self), now=now)["shelf"]["stale"], want, h)

    def test_stop_hook_stops_an_assertion_when_stale(self):
        c = SH.cfg()
        bid = self.doc["id"]
        write_text(self.base / "briefs" / f"{bid}.json", dump_json(self.doc))
        run = {"name": "Bash", "input": {"command": "python -X utf8 -m concierge brief --question x"}, "result": f"{bid}\n"}
        done = {"name": "Bash", "input": {"command": f"python -X utf8 -m concierge verify /tmp/d.txt --brief {bid}"}, "result": "ok"}
        turn = {"prompt": "今週末どこ?", "key": "k", "calls": [run, done]}

        def why(text):
            write_text(self.base / "last_answer.json", dump_json({"brief": bid, "at": STALE_NOW, "text": text}))
            return SH.decide(text, turn, self.base, c)
        self.assertEqual(why("横岳をおすすめします。"), {"block": True, "why": "stale"})
        self.assertEqual(why("古い予報では、横岳が候補です。")["why"], "ok")
        self.assertIn("stale", c["reasons"])


if __name__ == "__main__":
    unittest.main()
