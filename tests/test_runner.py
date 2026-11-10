"""子プロセスの起動(collect/runner.py)と通信の集計。通信しない。"""
import unittest

from helpers import ROOT

from collect.common import MEASURE_DIR
from collect.runner import check_argv, estimated_calls, hook_env, summarize


class HookEnv(unittest.TestCase):
    BASE = {"PATH": "p", "PYTHONPATH": "/somewhere", "BIYORI_REQ_MAX": "99999", "BIYORI_ALLOW_HOSTS": "evil.example",
            "BIYORI_MIN_INTERVAL_S": "0", "GITHUB_TOKEN": "secret", "HOME": "h"}

    def test_hook_is_always_attached_and_parent_values_do_not_leak(self):
        e = hook_env(ROOT / "req.jsonl", 300, ["api.open-meteo.com"], base=self.BASE)
        self.assertEqual(e["PYTHONPATH"], str(MEASURE_DIR))
        self.assertEqual(e["BIYORI_REQ_MAX"], "300")
        self.assertEqual(e["BIYORI_ALLOW_HOSTS"], "api.open-meteo.com")
        self.assertEqual(e["BIYORI_REQ_LOG"], str(ROOT / "req.jsonl"))
        self.assertNotIn("BIYORI_MIN_INTERVAL_S", e)
        self.assertNotIn("GITHUB_TOKEN", e)
        self.assertEqual((e["PATH"], e["HOME"]), ("p", "h"))

    def test_no_declared_hosts_means_none(self):
        self.assertEqual(hook_env(ROOT / "r.jsonl", 1, [], base={})["BIYORI_ALLOW_HOSTS"], "none")

    def test_child_runs_in_japan_time(self):
        # ヤマビヨリは date.today() で対象の日を決める。Actions のマシンは UTC なので、朝 4:27 の実行で日付がずれないように
        self.assertEqual(hook_env(ROOT / "r.jsonl", 1, [], base={})["TZ"], "Asia/Tokyo")


class Argv(unittest.TestCase):
    def test_array_with_utf8_only(self):
        check_argv(["python", "-X", "utf8", "x.py"])
        with self.assertRaises(TypeError):
            check_argv("python -X utf8 x.py")
        with self.assertRaises(ValueError):
            check_argv(["python", "x.py"])


class Summaries(unittest.TestCase):
    def test_counts_by_host_and_status_only(self):
        recs = [{"host": "api.open-meteo.com", "path": "/v1/forecast", "status": 200, "hourly_vars": 25, "forecast_days": 15},
                {"host": "api.open-meteo.com", "path": "/v1/forecast", "status": 200, "hourly_vars": 5, "daily_vars": 0},
                {"host": "api.open-meteo.com", "path": "/data/jma_msm/static/meta.json", "status": 200},
                {"host": "api.open-meteo.com", "path": "/v1/forecast", "status": None, "error": "ConnectionError"}]
        s = summarize(recs, None)
        self.assertEqual(s["requests"], 4)
        self.assertEqual(s["by_host"], {"api.open-meteo.com": 4})
        self.assertEqual(s["by_status"], {"200": 3, "error": 1})
        self.assertEqual(s["by_error"], {"ConnectionError": 1})          # 失敗の種類(例外の名前)
        # 推定: 25 変数 × 15 日 → 2.5 × (15/14) ≈ 2.68、5 変数 → 1、meta → 0、エラー(変数の記録なし)→ 1 。合計 4.68 → 切り上げ 5
        self.assertEqual(s["estimated_calls"], 5)
        self.assertEqual(estimated_calls(recs[2]), 0.0)

    def test_empty(self):
        self.assertEqual(summarize([])["estimated_calls"], 0)
        self.assertEqual(summarize([])["by_error"], {})

    def test_error_kinds_are_counted_by_name(self):
        recs = [{"host": "h", "path": "/data/jma_msm/static/meta.json", "status": None, "error": "URLError"},
                {"host": "h", "path": "/data/jma_msm/static/meta.json", "status": None, "error": "TimeoutError"},
                {"host": "h", "path": "/data/jma_msm/static/meta.json", "status": None, "error": "URLError"},
                {"host": "h", "path": "/data/jma_msm/static/meta.json", "status": None},
                {"host": "h", "path": "/data/jma_msm/static/meta.json", "status": 200}]
        self.assertEqual(summarize(recs)["by_error"], {"TimeoutError": 1, "URLError": 2, "unknown": 1})


if __name__ == "__main__":
    unittest.main()
