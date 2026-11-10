"""collect/meta_fetch.py の読み直しと失敗の種類。通信しない(偽の opener を渡す)。"""
import io
import json
import socket
import unittest
import urllib.error

import helpers  # noqa: F401  (ソケット禁止)

from collect import meta_fetch as mf


GOOD = {"last_run_initialisation_time": 1758682800, "last_run_availability_time": 1758701394, "extra": "x"}


class Opener:
    """モデル名 → 返す内容の列(dict は成功、例外は raise)。呼ばれた URL を記録する。"""
    def __init__(self, plan):
        self.plan = {m: list(v) for m, v in plan.items()}
        self.calls = []

    def __call__(self, url, timeout=None):
        model = url.split("/data/")[1].split("/")[0]
        self.calls.append(model)
        x = self.plan[model].pop(0)
        if isinstance(x, BaseException):
            raise x
        return io.BytesIO(json.dumps(x).encode("utf-8"))


class Retry(unittest.TestCase):
    def setUp(self):
        self.slept = []

    def fetch(self, plan, models=("jma_msm", "ecmwf_ifs025")):
        op = Opener(plan)
        return mf.fetch_all(list(models), opener=op, sleep=self.slept.append, wait_s=5.0), op

    def test_all_ok_means_no_retry_and_no_wait(self):
        out, op = self.fetch({"jma_msm": [GOOD], "ecmwf_ifs025": [GOOD]})
        self.assertEqual(op.calls, ["jma_msm", "ecmwf_ifs025"])
        self.assertEqual(self.slept, [])
        self.assertEqual(out["jma_msm"]["last_run_initialisation_time"], 1758682800)
        self.assertNotIn("extra", out["jma_msm"])
        self.assertNotIn("attempts", out["jma_msm"])

    def test_only_failed_model_is_read_again_once_after_a_wait(self):
        err = urllib.error.URLError(ConnectionResetError(104, "reset"))
        out, op = self.fetch({"jma_msm": [GOOD], "ecmwf_ifs025": [err, GOOD]})
        self.assertEqual(op.calls, ["jma_msm", "ecmwf_ifs025", "ecmwf_ifs025"])
        self.assertEqual(self.slept, [5.0])
        e = out["ecmwf_ifs025"]
        self.assertEqual((e["attempts"], e["first_error"], e["first_error_reason"]), (2, "URLError", "ConnectionResetError"))
        self.assertNotIn("error", e)
        self.assertEqual(e["last_run_initialisation_time"], 1758682800)

    def test_second_failure_is_kept_and_not_retried_again(self):
        out, op = self.fetch({"jma_msm": [TimeoutError("timed out"), socket.timeout("timed out")]}, models=("jma_msm",))
        self.assertEqual(op.calls, ["jma_msm", "jma_msm"])
        self.assertEqual(self.slept, [5.0])
        self.assertEqual(out["jma_msm"]["error"], "TimeoutError")
        self.assertEqual(out["jma_msm"]["attempts"], 2)

    def test_one_wait_for_several_failed_models(self):
        out, op = self.fetch({"jma_msm": [ValueError("bad json"), GOOD], "ecmwf_ifs025": [OSError("x"), GOOD]})
        self.assertEqual(self.slept, [5.0])
        self.assertEqual(op.calls, ["jma_msm", "ecmwf_ifs025", "jma_msm", "ecmwf_ifs025"])
        self.assertEqual((out["jma_msm"]["first_error"], out["ecmwf_ifs025"]["first_error"]), ("ValueError", "OSError"))

    def test_http_error_is_not_read_again(self):
        # 4xx/5xx は読み直さない(フックの下ではフックが即中止する。フックの外でも読み直さない)
        err = urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None)
        out, op = self.fetch({"jma_msm": [err]}, models=("jma_msm",))
        self.assertEqual(op.calls, ["jma_msm"])
        self.assertEqual(self.slept, [])
        self.assertEqual((out["jma_msm"]["error"], out["jma_msm"]["status"]), ("HTTPError", 503))

    def test_failed_model_is_unknown_for_model_runs(self):
        from collect.meta import _one
        out, _ = self.fetch({"jma_msm": [OSError("x"), OSError("y")]}, models=("jma_msm",))
        self.assertEqual(_one(out["jma_msm"]), (None, None))


if __name__ == "__main__":
    unittest.main()
