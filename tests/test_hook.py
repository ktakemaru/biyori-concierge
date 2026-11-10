"""計測フック(collect/measure/sitecustomize.py)。許可ホスト以外は送信前に止める・回数を数える・4xx/5xx(429 を含む)で即中止・
記録先が絶対パスで書けなければ通信前に止める。通信しない(子のスクリプトもソケットを禁止する)。
元は biyori-hub の tests/test_stage11_phase2.py・test_stage10_phase3.py・test_stage9b.py・test_stage5a.py の該当部分。"""
import json
import subprocess
import sys
import unittest
from unittest import mock

from helpers import NET_SCRIPT, ROOT, Stopped, load_hook, tmpdir

from collect.runner import hook_env


def run_probe(test, allow, url="https://any.example.invalid/x", times=1, max_requests=5, unset_allow=False):
    d = tmpdir(test)
    env = hook_env(d / "req.jsonl", max_requests, allow)
    if unset_allow:
        env.pop("BIYORI_ALLOW_HOSTS")
    r = subprocess.run([sys.executable, "-X", "utf8", str(NET_SCRIPT), "--url", url, "--times", str(times)], env=env,
                       capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    lines = [json.loads(x) for x in (d / "req.jsonl").read_text(encoding="utf-8").splitlines()] if (d / "req.jsonl").exists() else []
    return r, lines


class AllowList(unittest.TestCase):
    def test_resolve_allow(self):
        m, _ = load_hook()
        r = m._resolve_allow
        self.assertEqual(r(None), set())
        self.assertEqual(r("api.open-meteo.com"), {"api.open-meteo.com"})
        self.assertEqual(r(" A.example.invalid , b.example.invalid"), {"a.example.invalid", "b.example.invalid"})
        for deny in ("", "   ", ",", "none", "NONE", " None ", "none,api.open-meteo.com"):
            with self.subTest(raw=deny):
                self.assertEqual(r(deny), set())

    def test_undeclared_hosts_are_stopped_before_sending_in_a_real_child(self):
        for allow, unset in (([], False), ([], True), (["other.example.invalid"], False)):
            for url in ("https://any.example.invalid/x", "https://api.open-meteo.com/v1/forecast"):
                with self.subTest(allow=allow, unset=unset, url=url):
                    r, lines = run_probe(self, allow, url, unset_allow=unset)
                    self.assertEqual(r.returncode, 75, r.stdout + r.stderr)
                    self.assertIn("許可リスト外", r.stderr)
                    self.assertNotIn("hook_did_not_stop", r.stdout)
                    self.assertEqual(lines[-1]["count"], 0)                  # 送る前に止まった(数えていない)

    def test_declared_host_passes_and_is_counted(self):
        r, lines = run_probe(self, ["any.example.invalid"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("hook_did_not_stop", r.stdout)                         # フックは通した(先はスクリプトのソケット禁止で止まる)
        self.assertEqual([x["n"] for x in lines], [1])
        self.assertEqual(lines[0]["host"], "any.example.invalid")
        self.assertNotIn("latitude", json.dumps(lines))                     # 座標・クエリは記録しない

    def test_request_cap_stops_before_the_next_send(self):
        r, lines = run_probe(self, ["any.example.invalid"], times=3, max_requests=2)
        self.assertEqual(r.returncode, 75, r.stdout + r.stderr)
        self.assertIn("上限 2 件", r.stderr)
        self.assertEqual(len([x for x in lines if "abort" not in x]), 2)


def hook_after(m, status, body=b""):
    rows, stop = [], []

    def fake_stop(reason, extra=None, write=True):
        stop.append(reason)
        raise Stopped(reason)
    m._cur_start_wall = 0.0
    with mock.patch.object(m, "_write", rows.append), mock.patch.object(m, "_stop", fake_stop):
        try:
            m._after({"n": 1}, status, 0.0, body=body, url="https://api.open-meteo.com/v1/forecast?latitude=35.1&longitude=139.2")
        except Stopped:
            pass
    return rows[-1], (stop[0] if stop else None)


class HttpErrors(unittest.TestCase):
    def test_429_and_every_error_status_abort_at_once(self):
        for code in (429, 500, 502, 503, 404):
            m, _ = load_hook()
            row, stop = hook_after(m, code)
            self.assertEqual(stop, f"HTTP {code}", code)
            self.assertNotIn("retry_tolerated", row)

    def test_429_is_never_tolerated_even_if_opted_in(self):
        m, _ = load_hook(BIYORI_HTTP_RETRY_STATUSES="429,503", BIYORI_HTTP_RETRY_MAX_CONSEC="2", BIYORI_HTTP_RETRY_MAX_TOTAL="6")
        self.assertEqual(sorted(m._HTTP_RETRY), [503])
        self.assertEqual(hook_after(m, 429)[1], "HTTP 429")

    def test_collect_never_opts_in_to_retries(self):
        env = hook_env(ROOT / "x.jsonl", 5, ["api.open-meteo.com"], base={"BIYORI_HTTP_RETRY_STATUSES": "503", "PATH": "x"})
        self.assertFalse([k for k in env if k.startswith("BIYORI_HTTP_RETRY")])

    def test_200_is_recorded_without_body(self):
        m, _ = load_hook()
        row, stop = hook_after(m, 200, b"hello")
        self.assertIsNone(stop)
        self.assertNotIn("body_head", row)

    def test_body_head_hides_the_query(self):
        m, _ = load_hook()
        url = "https://api.open-meteo.com/v1/forecast?latitude=35.1&longitude=139.2"
        self.assertEqual(m._body_head(b"bad latitude=35.1&longitude=139.2 !", url), "bad <query> !")
        self.assertEqual(m._body_head(b"a\nb\tc\x00d"), "a b cd")


class LogFailClosed(unittest.TestCase):
    URL = "https://api.open-meteo.com/v1/forecast"

    def hook(self, log):
        m, _ = load_hook()
        m._LOG, m._COUNT = log, None
        m._ALLOW = m._resolve_allow("api.open-meteo.com")
        stops = []

        def stop(reason, extra=None, write=True):
            stops.append(reason)
            raise Stopped(reason)
        m._stop = stop
        m._pace = lambda *a, **k: None
        return m, stops

    def test_relative_log_path_stops_before_the_first_request(self):
        m, stops = self.hook("logs/relative.jsonl")
        with self.assertRaises(Stopped):
            m._before("GET", self.URL, {}, "requests")
        self.assertEqual(m._count, 0)
        self.assertIn("絶対パスでない", stops[0])

    def test_unwritable_log_stops_before_the_first_request(self):
        d = tmpdir(self)
        m, stops = self.hook(str(d / "missing" / "req.jsonl"))
        with self.assertRaises(Stopped):
            m._before("GET", self.URL, {}, "requests")
        self.assertIn("書き込めない", stops[0])

    def test_runner_refuses_a_relative_log_path(self):
        with self.assertRaises(ValueError):
            hook_env("relative.jsonl", 5, ["api.open-meteo.com"])


class Pacing(unittest.TestCase):
    def test_min_interval_waits_only_when_too_soon(self):
        m, _ = load_hook()
        self.assertEqual(m._MIN_INTERVAL, 0.6)
        t, slept = [100.0], []
        now = lambda: t[0]  # noqa: E731
        m._last_start = None
        m._pace(now, slept.append)
        t[0] += 0.2
        m._pace(now, slept.append)
        self.assertAlmostEqual(slept[-1], 0.4)
        t[0] += 2.0
        n = len(slept)
        m._pace(now, slept.append)
        self.assertEqual(len(slept), n)


if __name__ == "__main__":
    unittest.main()
