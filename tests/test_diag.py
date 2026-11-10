"""診断(collect/diag_probe.py・collect/diag.py・diagnose.yml)。通信しない(ソケットは偽物に差し替える)。"""
import io
import json
import socket
import unittest
from unittest import mock

from helpers import tmpdir

from collect import diag, diag_probe as dp
from collect.common import write_json


class FakeSock:
    """http.client が使う分だけの偽のソケット。応答の bytes を返す。readline で止まる形も作れる。"""

    def __init__(self, response=b"", hang=False):
        self.response, self.hang, self.sent = response, hang, b""

    def sendall(self, data):
        self.sent += data

    def makefile(self, mode):
        if self.hang:
            class Hang(io.BytesIO):
                def readline(self, *a):
                    raise TimeoutError("timed out")
            return Hang()
        return io.BytesIO(self.response)

    def close(self):
        pass


class FakeContext:
    def __init__(self, sock=None, error=None):
        self.sock, self.error, self.names = sock, error, []

    def wrap_socket(self, sock, server_hostname=None):
        self.names.append(server_hostname)
        if self.error:
            raise self.error
        return self.sock


def http_200(body):
    return b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(body) + body


class Probe(unittest.TestCase):
    def once(self, ctx, connect=None):
        connect = connect or (lambda addr, timeout=None: FakeSock())
        with mock.patch.object(socket, "create_connection", side_effect=connect) as cc:
            r = dp.probe_once("192.0.2.10", 10, context=ctx)
        return r, cc

    def test_success_records_stage_times_and_uses_the_pinned_ip_with_the_real_name(self):
        body = json.dumps({"last_run_initialisation_time": 1}).encode()
        sock = FakeSock(http_200(body))
        ctx = FakeContext(sock=sock)
        r, cc = self.once(ctx)
        self.assertTrue(r["ok"], r)
        self.assertIsNone(r["failed_stage"])
        self.assertEqual((r["status"], r["bytes"]), (200, len(body)))
        for k in ("tcp_s", "tls_s", "wait_s", "total_s"):
            self.assertIn(k, r)
        self.assertEqual(cc.call_args.args[0], ("192.0.2.10", 443))            # 接続先は固定した IP
        self.assertEqual(ctx.names, ["api.open-meteo.com"])                    # TLS の名前(SNI・証明書)は本物の名前
        self.assertIn(b"GET /data/jma_msm/static/meta.json ", sock.sent)          # meta.json だけ
        self.assertIn(b"Host: api.open-meteo.com", sock.sent)

    def test_tcp_failure(self):
        def refuse(addr, timeout=None):
            raise TimeoutError("timed out")
        r, _ = self.once(FakeContext(), connect=refuse)
        self.assertEqual((r["ok"], r["failed_stage"], r["error"], r["error_reason"]), (False, "tcp", "URLError", "TimeoutError"))

    def test_tls_failure(self):
        r, _ = self.once(FakeContext(error=TimeoutError("_ssl.c:1018: The handshake operation timed out")))
        self.assertEqual((r["failed_stage"], r["error_reason"]), ("tls", "TimeoutError"))
        self.assertIn("tcp_s", r)
        self.assertNotIn("tls_s", r)

    def test_waiting_for_the_response(self):
        r, _ = self.once(FakeContext(sock=FakeSock(hang=True)))
        self.assertEqual((r["ok"], r["failed_stage"], r["error"]), (False, "response", "TimeoutError"))
        self.assertIn("tls_s", r)

    def test_body_that_is_not_json(self):
        r, _ = self.once(FakeContext(sock=FakeSock(http_200(b"<html>"))))
        self.assertEqual((r["ok"], r["failed_stage"]), (False, "check"))


class Plan(unittest.TestCase):
    def test_resolve_dedupes_and_names_the_family(self):
        rows = [(socket.AF_INET, 1, 6, "", ("192.0.2.1", 443)), (socket.AF_INET, 1, 6, "", ("192.0.2.1", 443)),
                (socket.AF_INET6, 1, 6, "", ("2001:db8::1", 443, 0, 0))]
        self.assertEqual(dp.resolve(getaddrinfo=lambda *a, **k: rows),
                         [{"ip": "192.0.2.1", "family": "IPv4"}, {"ip": "2001:db8::1", "family": "IPv6"}])

    def test_round_robin_and_cap(self):
        ips = [{"ip": "a"}, {"ip": "b"}]
        self.assertEqual(dp.plan(ips, 3, 100), [("a", 1), ("b", 1), ("a", 2), ("b", 2), ("a", 3), ("b", 3)])
        self.assertEqual(len(dp.plan(ips, 10, 7)), 7)

    def test_interval_between_starts_and_time_budget(self):
        now = [0.0]
        slept = []

        def sleep(s):
            slept.append(round(s, 3))
            now[0] += s

        def probe(ip):
            now[0] += 0.25                           # 1 回 0.25 秒で終わる
            return {"ip": ip, "ok": True}
        res, stop = dp.run_plan([("a", 1), ("b", 1), ("a", 2)], interval_s=1.0, total_timeout_s=100, probe=probe,
                                sleep=sleep, clock=lambda: now[0])
        self.assertEqual((len(res), stop), (3, None))
        self.assertEqual(slept, [0.75, 0.75])              # 始まりから次の始まりまで 1 秒
        self.assertEqual([r["t_s"] for r in res], [0.0, 1.0, 2.0])
        now[0] = 0.0
        res, stop = dp.run_plan([("a", 1)] * 5, interval_s=1.0, total_timeout_s=2.5, probe=probe,
                                sleep=sleep, clock=lambda: now[0])
        self.assertEqual((len(res), stop), (3, "time_budget"))

    def test_summary_per_ip(self):
        results = [{"ip": "a", "ok": True, "tls_s": 0.1, "wait_s": 0.2, "total_s": 0.4, "failed_stage": None},
                   {"ip": "a", "ok": False, "failed_stage": "response", "error": "TimeoutError", "total_s": 10.4},
                   {"ip": "b", "ok": False, "failed_stage": "tls", "error": "URLError", "error_reason": "TimeoutError", "total_s": 10.1}]
        s = dp.summarize([{"ip": "a", "family": "IPv4"}, {"ip": "b", "family": "IPv4"}], results)
        self.assertEqual((s[0]["tries"], s[0]["ok"], s[0]["failed"], s[0]["failed_stage"]), (2, 1, 1, {"response": 1}))
        self.assertEqual(s[1]["errors"], {"URLError(TimeoutError)": 1})
        self.assertEqual(s[0]["total_s_ok"], {"min": 0.4, "median": 0.4, "max": 0.4})


class ThroughTheHook(unittest.TestCase):
    def test_undeclared_host_is_stopped_before_sending(self):
        # 子プロセスは計測フックつき。許可ホストがなければ、送る前に止まる(名前解決もしない: テスト用の IP を渡す)
        d = tmpdir(self)
        cfg = {"per_ip": 1, "interval_s": 1.0, "timeout_s": 1, "max_ips": 1, "max_requests": 2, "total_timeout_s": 30}
        with mock.patch.object(diag, "allow_hosts", lambda kind: []):
            out = diag.diagnose(d, cfg=cfg, test_ips=["192.0.2.1"])
        self.assertEqual(out["returncode"], 75)
        self.assertEqual(out["hook"]["blocked_host"], "api.open-meteo.com")
        self.assertEqual(out["hook"]["requests"], 0)
        self.assertIsNone(out["probe"])
        self.assertIn("調べの結果がありません", diag.render_summary(d))

    def test_diag_hosts_are_only_open_meteo(self):
        from collect.common import allow_hosts
        self.assertEqual(allow_hosts("diag"), ["api.open-meteo.com"])


class Summary(unittest.TestCase):
    def test_table(self):
        d = tmpdir(self)
        probe = {"path": "/data/jma_msm/static/meta.json", "settings": {"per_ip": 10, "interval_s": 1.0, "timeout_s": 10},
                 "resolved": [{"ip": "192.0.2.1", "family": "IPv4"}], "stop": None,
                 "summary": [{"ip": "192.0.2.1", "family": "IPv4", "tries": 10, "ok": 7, "failed": 3,
                              "failed_stage": {"tls": 1, "response": 2}, "errors": {"TimeoutError": 2, "URLError(TimeoutError)": 1},
                              "tls_s": {"min": 0.1, "median": 0.12, "max": 0.2}, "wait_s": None,
                              "total_s_ok": {"min": 0.3, "median": 0.4, "max": 0.9}, "total_s_failed": None}]}
        write_json(d / "diag.json", {"probe": probe, "hook": {"requests": 10, "by_status": {"200": 7, "error": 3}, "by_error": {},
                                                              "aborted": None, "rate_limited": False}})
        text = diag.render_summary(d)
        self.assertIn("| 192.0.2.1 | IPv4 | 10 | 7 | 3 | TLS の途中 1, 応答待ち 2 | TimeoutError 2, URLError(TimeoutError) 1 | 0.12(0.1〜0.2) | — | 0.4(0.3〜0.9) | — |", text)
        self.assertIn("429 なし", text)


class Workflow(unittest.TestCase):
    def test_manual_only_read_only_no_yamabiyori(self):
        from test_workflows import WF, code_lines, load, runs
        wf = load("diagnose.yml")
        self.assertEqual(list(wf["on"]), ["workflow_dispatch"])                 # 定期実行なし
        self.assertEqual(wf["permissions"], {"contents": "read"})
        self.assertEqual(list(wf["jobs"]), ["diagnose"])
        job = wf["jobs"]["diagnose"]
        self.assertEqual(job["permissions"], {"contents": "read"})
        self.assertEqual(job["steps"][0]["name"], "Check confirmation")
        self.assertIn('"$CONFIRM" != "yes-run-live"', job["steps"][0]["run"])
        self.assertIn("python -X utf8 -m collect diagnose --out _diag", runs(job))
        self.assertIn("-m collect diagnose-summary", runs(job))
        text = "\n".join(code_lines(WF / "diagnose.yml")).lower()
        for word in ("yamabiyori", "collect run", "push", "contents: write"):
            self.assertNotIn(word, text)
        self.assertEqual(wf["concurrency"]["group"], load("collect.yml")["concurrency"]["group"])   # collect と同時に走らない
        for s in job["steps"]:
            if "actions/checkout" in s.get("uses", ""):
                self.assertIs(s["with"]["persist-credentials"], False)


if __name__ == "__main__":
    unittest.main()
