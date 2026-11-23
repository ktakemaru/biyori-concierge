"""429 の種類(1 日・1 時間・1 分のどの上限か)を記録に残す(段階 2 の仕上げ 第 5 部)。通信しない。
偽のヤマビヨリ(tests/fixtures/yamabiyori)が、計測フックと同じ形の記録(body_head つき)を書く。本文は作り物の見本。"""
import os
import sys
import unittest
from unittest import mock

from helpers import FAKE_YAMA, FIX, tmpdir

from collect import shelf
from collect.common import read_json, schema_errors
from collect.run import collect
from collect.runner import rate_limit_kind, rate_limit_kinds, summarize

META = read_json(FIX / "meta" / "before.json")
HOURLY = '{"error":true,"reason":"Hourly API request limit exceeded. Please try again in the next hour."}'
MINUTELY = '{"reason":"Minutely API request limit exceeded. Please try again in one minute.","error":true}'
DAILY = '{"reason":"DAILY API request limit exceeded. Please try again tomorrow.","error":true}'


class Kind(unittest.TestCase):
    def test_kind_from_the_body(self):
        for body, want in ((HOURLY, "hourly"), (MINUTELY, "minutely"), (DAILY, "daily"),
                           ("hourly and daily and minutely", "daily"),          # 重い順
                           ("minutely hourly", "hourly"), ("Too many concurrent requests", "unknown"),
                           ("", "unknown"), (None, "unknown"), (429, "unknown")):
            with self.subTest(body=body):
                self.assertEqual(rate_limit_kind(body), want)

    def test_only_429_records_are_counted_and_the_body_is_not_kept(self):
        recs = [{"status": 200}, {"status": 429, "body_head": HOURLY}, {"status": 429}, {"status": 503, "body_head": "hourly"},
                {"status": 429, "body_head": HOURLY}]
        self.assertEqual(rate_limit_kinds(recs), {"hourly": 2, "unknown": 1})
        s = summarize(recs)
        self.assertEqual(s["http_429_kinds"], {"hourly": 2, "unknown": 1})
        self.assertNotIn("exceeded", str(s))
        self.assertEqual(summarize([{"status": 200}])["http_429_kinds"], {})


class Records(unittest.TestCase):
    def artifact(self, mode, bodies=""):
        out = tmpdir(self) / "art"
        with mock.patch.dict(os.environ, {"FAKE_YAMA": mode, "FAKE_YAMA_429_BODY": bodies}):
            run = collect(agents=["yamabiyori"], out_dir=out, checkouts={"yamabiyori": FAKE_YAMA},
                          pythons={"yamabiyori": sys.executable}, yama_limit=3, meta_fetch=lambda ph: META)
        return run, out

    def publish(self, art, existing=None):
        base = tmpdir(self)
        ex = existing or base / "empty"
        ex.mkdir(exist_ok=True)
        shelf.prepare(art, ex, base / "pub")
        return base / "pub", read_json(base / "pub/manifest.json")

    def test_rate_limited_run_like_20261123_records_the_kind_everywhere_but_not_the_body(self):
        _, first = self.artifact("ok")
        prev, _ = self.publish(first)
        run, art = self.artifact("rl1partial", HOURLY)
        y = run["agents"]["yamabiyori"]
        self.assertEqual((y["status"], y["http_429_kinds"], y["attempts"][0]["http_429_kinds"]), ("rate_limited", {"hourly": 1}, {"hourly": 1}))
        self.assertEqual(schema_errors(read_json(art / "run.json"), "biyori-collect-run"), [])
        logs = read_json(art / "logs/requests.json")
        self.assertEqual(schema_errors(logs, "biyori-request-log"), [])
        self.assertEqual((logs["agents"]["yamabiyori"]["http_429_kinds"], logs["total"]["http_429_kinds"], logs["metadata"]["http_429_kinds"]),
                         ({"hourly": 1}, {"hourly": 1}, {}))
        pub, m = self.publish(art, existing=prev)
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])
        e = m["agents"]["yamabiyori"]
        self.assertEqual((e["status"], e["http_429_kinds"]), ("kept_previous", {"hourly": 1}))
        self.assertIn("- 429: yamabiyori 1 回(1 時間の上限。rate_limited。取り直しの回は始めず、棚は前回のまま)", shelf.render_summary(art))
        for p in pub.rglob("*"):                                       # 本文は棚に載せない
            if p.is_file():
                text = p.read_text(encoding="utf-8")
                self.assertNotIn("request limit exceeded", text, p.name)
                self.assertNotIn("body_head", text, p.name)
        self.assertNotIn("request limit exceeded", (art / "run.json").read_text(encoding="utf-8"))

    def test_ok_run_after_minutely_limits(self):
        run, art = self.artifact("rl2ok", MINUTELY)
        self.assertEqual(run["agents"]["yamabiyori"]["status"], "ok")
        _, m = self.publish(art)
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])
        self.assertEqual(m["agents"]["yamabiyori"]["http_429_kinds"], {"minutely": 2})
        self.assertEqual(m["agents"]["yamabiyori"]["attempts"][0]["http_429_kinds"], {"minutely": 2})
        self.assertIn("- 429: yamabiyori 2 回(1 分の上限。待って取り直し、全座そろった)", shelf.render_summary(art))

    def test_mixed_kinds_and_unknown(self):
        _, art = self.artifact("rl2partial", f"{MINUTELY}|{HOURLY}")
        self.assertIn("- 429: yamabiyori 2 回(1 時間の上限 1 回・1 分の上限 1 回。rate_limited。", shelf.render_summary(art))
        run, art = self.artifact("rl1partial")                          # 本文の記録がない
        self.assertEqual(run["agents"]["yamabiyori"]["http_429_kinds"], {"unknown": 1})
        self.assertIn("(rate_limited。取り直しの回は始めず、棚は前回のまま) 種類は不明", shelf.render_summary(art))

    def test_no_429_has_no_kinds(self):
        run, art = self.artifact("ok")
        self.assertEqual(run["agents"]["yamabiyori"]["http_429_kinds"], {})
        _, m = self.publish(art)
        self.assertNotIn("http_429_kinds", m["agents"]["yamabiyori"])
        self.assertIn("- 429: なし", shelf.render_summary(art))

    def test_429_at_the_metadata(self):
        from collect import meta as meta_mod
        from collect.runner import ChildResult
        res = ChildResult(returncode=75, started_at=None, finished_at=None, runtime_s=0.1, records=[{"status": 429, "body_head": DAILY}],
                          abort="HTTP 429")
        out = tmpdir(self) / "art"
        with mock.patch.object(meta_mod, "fetch_meta", return_value=(None, res)), mock.patch.object(meta_mod, "python_for_meta", return_value="x"):
            run = collect(agents=["yamabiyori"], out_dir=out, checkouts={"yamabiyori": FAKE_YAMA}, pythons={"yamabiyori": sys.executable})
        y = run["agents"]["yamabiyori"]
        self.assertEqual((y["reason"], y["http_429_kinds"]), ("rate_limited_at_metadata", {"daily": 1}))
        self.assertEqual(schema_errors(read_json(out / "run.json"), "biyori-collect-run"), [])
        self.assertEqual(read_json(out / "logs/requests.json")["metadata"]["http_429_kinds"], {"daily": 1})
        self.assertIn("- 429: yamabiyori(1 日の上限。rate_limited_at_metadata。棚は前回のまま)", shelf.render_summary(out))


if __name__ == "__main__":
    unittest.main()
