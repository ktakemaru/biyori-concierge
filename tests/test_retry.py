"""ヤマビヨリの取り直し(collect/run.py の run_yamabiyori)。偽のヤマビヨリを計測フックつきで起動する(通信しない)。
FAKE_YAMA_PLAN で回ごとの形と通信の記録の件数を決める(tests/fixtures/yamabiyori/mountain_weather_mvp.py)。"""
import os
import sys
import unittest
from unittest import mock

from helpers import FAKE_YAMA, FIX, tmpdir

from collect.common import read_json, schema_errors
from collect.run import collect, run_yamabiyori

CFG = {"max_requests": 450, "timeout_s": 3600, "max_runs": 3, "total_timeout_s": 4500}


def go(test, plan, clock=None, **cfg):
    d = tmpdir(test)
    env = {"FAKE_YAMA_PLAN": plan, "FAKE_YAMA_STATE": str(d / "state.txt")}
    kw = {"clock": clock} if clock else {}
    with mock.patch.dict(os.environ, env):
        r = run_yamabiyori(checkout=FAKE_YAMA, python=sys.executable, out_dir=d / "art", limit=3, cfg=dict(CFG, **cfg), **kw)
    return r, d / "art"


def counts(r):
    return [(a["n"], a["status"], a["requests"], a["fetched"]) for a in r["attempts"]]


class Retry(unittest.TestCase):
    def test_second_run_recovers_and_counts_each_run(self):
        r, out = go(self, "partial:9,ok:3")
        self.assertEqual(counts(r), [(1, "ok", 9, 2), (2, "ok", 3, 3)])
        self.assertEqual((r["status"], r["used_run"], r["retry_stop"], r["requests"]), ("ok", 2, None, 12))
        self.assertEqual(r["coverage"]["missing"], 0)
        self.assertFalse(r["attempts"][1]["cache_suspect"])           # 3 件 ≤ 欠けた 1 座 × 3 × 3
        self.assertEqual(r["fetch"]["requests"], 12)                  # 通信の上限・集計は全部の回の合計
        self.assertTrue((out / "yamabiyori/explore.json").is_file())
        self.assertEqual(read_json(out / "yamabiyori/explore.json")["fetched"], 3)   # 最も多く取れた回の出力

    def test_complete_first_run_is_not_repeated(self):
        r, _ = go(self, "ok:9")
        self.assertEqual(counts(r), [(1, "ok", 9, 3)])
        self.assertEqual((r["status"], r["retry_stop"]), ("ok", None))
        self.assertNotIn("cache_suspect", r["attempts"][0])

    def test_at_most_max_runs_then_incomplete(self):
        r, _ = go(self, "partial:9,partial:3")
        self.assertEqual(counts(r), [(1, "ok", 9, 2), (2, "ok", 3, 2), (3, "ok", 3, 2)])
        self.assertEqual((r["status"], r["reason"], r["retry_stop"], r["used_run"]), ("incomplete", "partial_fetch", "max_runs", 3))
        r1, _ = go(self, "partial:9", max_runs=1)
        self.assertEqual(len(r1["attempts"]), 1)

    def test_cache_suspect_when_a_retry_sends_too_many(self):
        r, _ = go(self, "partial:9,partial:10", max_runs=2)
        self.assertTrue(r["attempts"][1]["cache_suspect"])           # 10 件 > 欠けた 1 座 × 3 × 3 = 9

    def test_request_budget_is_for_all_runs(self):
        r, _ = go(self, "partial:9", max_requests=9)
        self.assertEqual(len(r["attempts"]), 1)
        self.assertEqual((r["status"], r["retry_stop"]), ("incomplete", "request_budget"))

    def test_time_budget_stops_before_the_next_run(self):
        ticks = iter(range(0, 100000, 1000))               # 呼ばれるたびに 1000 秒進む時計
        r, _ = go(self, "partial:9", clock=lambda: next(ticks), total_timeout_s=1500)
        self.assertEqual(len(r["attempts"]), 1)
        self.assertEqual((r["status"], r["retry_stop"]), ("incomplete", "time_budget"))

    def test_failed_retry_keeps_the_best_earlier_output(self):
        r, out = go(self, "partial:9,exit2:0")
        self.assertEqual(counts(r), [(1, "ok", 9, 2), (2, "failed", 0, None)])
        self.assertEqual((r["status"], r["used_run"], r["retry_stop"]), ("incomplete", 1, "run_2_exit_2"))
        self.assertEqual(read_json(out / "yamabiyori/explore.json")["fetched"], 2)

    def test_429_in_a_retry_makes_the_agent_rate_limited(self):
        # 指示書 5.2: 429 は即中止。取り直しの回でも同じ(それまでの出力も使わない)
        r, out = go(self, "partial:9,429:0")
        self.assertEqual((r["status"], r["reason"]), ("rate_limited", "rate_limited"))
        self.assertEqual(len(r["attempts"]), 2)
        self.assertFalse((out / "proposals/yamabiyori.json").exists())

    def test_first_run_failure_is_not_retried(self):
        r, _ = go(self, "exit2:0")
        self.assertEqual(counts(r), [(1, "failed", 0, None)])
        self.assertEqual((r["status"], r["reason"]), ("failed", "exit_2"))


class ThroughCollect(unittest.TestCase):
    def test_run_json_logs_and_manifest_carry_each_run(self):
        from collect import shelf
        d = tmpdir(self)
        meta = read_json(FIX / "meta" / "before.json")
        env = {"FAKE_YAMA_PLAN": "partial:9,ok:3", "FAKE_YAMA_STATE": str(d / "state.txt")}
        with mock.patch.dict(os.environ, env):
            run = collect(agents=["yamabiyori"], out_dir=d / "art", checkouts={"yamabiyori": FAKE_YAMA},
                          pythons={"yamabiyori": sys.executable}, yama_limit=3, meta_fetch=lambda ph: meta)
        self.assertEqual(schema_errors(read_json(d / "art/run.json"), "biyori-collect-run"), [])
        self.assertEqual([a["requests"] for a in run["agents"]["yamabiyori"]["attempts"]], [9, 3])
        logs = read_json(d / "art/logs/requests.json")
        self.assertEqual((logs["total"]["requests"], logs["agents"]["yamabiyori"]["requests"]), (12, 12))
        (d / "ex").mkdir()
        shelf.prepare(d / "art", d / "ex", d / "pub")
        m = read_json(d / "pub/manifest.json")
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])
        y = m["agents"]["yamabiyori"]
        self.assertEqual(([a["fetched"] for a in y["attempts"]], y["used_run"], y["status"]), ([2, 3], 2, "ok"))
        text = shelf.render_summary(d / "art")
        self.assertIn("| 1 | ok | 9 | 3座のうち2座 |", text)
        self.assertIn("| 2 | ok | 3 | 3座のうち3座 |", text)
        self.assertIn("← 使った回", text)


if __name__ == "__main__":
    unittest.main()
