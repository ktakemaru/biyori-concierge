"""429 を決まった回数まで通す(指示書 5.2・D11。2026-11-22)。計測フック(BIYORI_HTTP_429_MAX_TOTAL)と、取得の側の判定。通信しない。
取得の側は偽のヤマビヨリ(tests/fixtures/yamabiyori/mountain_weather_mvp.py の rl<k>ok / rl<k>partial)を計測フックつきで起動する。"""
import os
import sys
import unittest
from unittest import mock

from helpers import FAKE_YAMA, FIX, ROOT, load_hook, tmpdir

from collect import shelf
from collect.common import config, read_json, schema_errors
from collect.run import collect, run_yamabiyori
from collect.runner import hook_env, run_hooked
from test_hook import hook_after

CFG = {"max_requests": 450, "timeout_s": 3600, "max_runs": 3, "total_timeout_s": 4500, "http_429_max_total": 5}
META = read_json(FIX / "meta" / "before.json")


class Hook(unittest.TestCase):
    def test_without_the_variable_429_still_aborts_at_once(self):
        m, err = load_hook()
        self.assertEqual(m._429_MAX, 0)
        self.assertEqual(err, "")
        row, stop = hook_after(m, 429)
        self.assertEqual(stop, "HTTP 429")
        self.assertNotIn("rate_limit_tolerated", row)

    def test_two_are_tolerated_and_the_third_aborts(self):
        m, err = load_hook(BIYORI_HTTP_429_MAX_TOTAL="2")
        self.assertIn("2 回まで", err)
        for _ in range(2):
            row, stop = hook_after(m, 429)
            self.assertIsNone(stop)
            self.assertTrue(row["rate_limit_tolerated"])
            self.assertNotIn("retry_tolerated", row)
        row, stop = hook_after(m, 200)                    # 間に 200 があっても、数えるのは実行全体
        self.assertIsNone(stop)
        row, stop = hook_after(m, 429)
        self.assertIn("429 を通す回数の上限 2 回を超えた", stop)
        self.assertNotIn("rate_limit_tolerated", row)

    def test_invalid_or_too_large_values_are_ignored(self):
        for raw in ("x", "", "0", "-1", "2.5", "11", "100"):
            with self.subTest(raw=raw):
                m, err = load_hook(BIYORI_HTTP_429_MAX_TOTAL=raw)
                self.assertEqual(m._429_MAX, 0)
                self.assertIn("無効", err)
                self.assertEqual(hook_after(m, 429)[1], "HTTP 429")
        m, _ = load_hook(BIYORI_HTTP_429_MAX_TOTAL="10")          # 上の限り(仮置き 10)ちょうどは有効
        self.assertEqual(m._429_MAX, 10)

    def test_other_statuses_are_unchanged(self):
        m, _ = load_hook(BIYORI_HTTP_429_MAX_TOTAL="5")
        for code in (500, 502, 503, 404, 403):
            with self.subTest(code=code):
                self.assertEqual(hook_after(m, code)[1], f"HTTP {code}")
        m, _ = load_hook(BIYORI_HTTP_429_MAX_TOTAL="5", BIYORI_HTTP_RETRY_STATUSES="503",
                         BIYORI_HTTP_RETRY_MAX_CONSEC="2", BIYORI_HTTP_RETRY_MAX_TOTAL="6")
        self.assertEqual(sorted(m._HTTP_RETRY), [503])                  # 429 は再試行の仕組みに入らない
        row, stop = hook_after(m, 503)
        self.assertIsNone(stop)
        self.assertTrue(row["retry_tolerated"])
        self.assertNotIn("rate_limit_tolerated", row)

    def test_runner_passes_the_value_and_drops_the_parents(self):
        env = hook_env(ROOT / "x.jsonl", 5, ["api.open-meteo.com"], base={"BIYORI_HTTP_429_MAX_TOTAL": "9", "PATH": "x"})
        self.assertNotIn("BIYORI_HTTP_429_MAX_TOTAL", env)
        d = tmpdir(self)
        probe = d / "env_probe.py"
        probe.write_text("import os; print('max=' + str(os.environ.get('BIYORI_HTTP_429_MAX_TOTAL')))\n", encoding="utf-8")
        for max_429, want in ((5, "max=5"), (None, "max=None"), (0, "max=None")):
            with self.subTest(max_429=max_429):
                with mock.patch.dict(os.environ, {"BIYORI_HTTP_429_MAX_TOTAL": "9"}):
                    r = run_hooked([sys.executable, "-X", "utf8", str(probe)], cwd=d, req_log=d / "r.jsonl", max_requests=5,
                                   allow=[], timeout_s=60, max_429=max_429)
                self.assertIn(want, r.stdout_tail)

    def test_config_value_comes_from_yamabiyori(self):
        self.assertEqual(config()["collect"]["agents"]["yamabiyori"]["http_429_max_total"], 5)   # MINUTELY_RETRY_MAX = 5


def go(test, mode, **cfg):
    d = tmpdir(test)
    env = {"FAKE_YAMA": mode, "FAKE_YAMA_PLAN": f"{mode}:2", "FAKE_YAMA_STATE": str(d / "state.txt")}
    with mock.patch.dict(os.environ, env):
        r = run_yamabiyori(checkout=FAKE_YAMA, python=sys.executable, out_dir=d / "art", limit=3,
                           cfg={k: v for k, v in dict(CFG, **cfg).items() if v is not None})
    started = int((d / "state.txt").read_text())
    return r, d / "art", started


class Collect(unittest.TestCase):
    def test_429_then_every_mountain_is_ok_and_counted(self):
        r, out, started = go(self, "rl1ok")
        self.assertEqual((r["status"], r["reason"], started), ("ok", None, 1))
        self.assertEqual((r["http_429"], r["http_429_tolerated"]), (1, 1))
        self.assertEqual(r["attempts"][0]["http_429"], 1)
        self.assertEqual(r["coverage"]["missing"], 0)
        self.assertTrue((out / "proposals/yamabiyori.json").is_file())

    def test_429_and_missing_mountains_is_rate_limited_without_another_run(self):
        r, out, started = go(self, "rl1partial")
        self.assertEqual((r["status"], r["reason"]), ("rate_limited", "rate_limited"))
        self.assertEqual(started, 1)                                  # 取り直しの回を始めない(子プロセスの起動は 1 回だけ)
        self.assertEqual(len(r["attempts"]), 1)
        self.assertEqual(r["http_429"], 1)
        self.assertFalse((out / "proposals/yamabiyori.json").exists())

    def test_more_than_allowed_is_stopped_by_the_hook(self):
        r, _, started = go(self, "rl6ok")
        self.assertEqual((r["status"], r["reason"], started), ("rate_limited", "rate_limited", 1))
        self.assertIn("上限 5 回を超えた", r["fetch"]["aborted"])
        self.assertEqual((r["http_429"], r["http_429_tolerated"]), (6, 5))

    def test_without_the_setting_it_behaves_as_before(self):
        for cfg in ({"http_429_max_total": None}, {"http_429_max_total": 0}):
            with self.subTest(cfg=cfg):
                r, _, started = go(self, "rl1ok", **cfg)
                self.assertEqual((r["status"], r["reason"], started), ("rate_limited", "rate_limited", 1))
                self.assertEqual(r["fetch"]["aborted"], "HTTP 429")

    def test_429_in_a_retry_that_completes_is_ok(self):
        d = tmpdir(self)
        env = {"FAKE_YAMA_PLAN": "partial:9,rl2ok:1", "FAKE_YAMA_STATE": str(d / "state.txt")}
        with mock.patch.dict(os.environ, env):
            r = run_yamabiyori(checkout=FAKE_YAMA, python=sys.executable, out_dir=d / "art", limit=3, cfg=CFG)
        self.assertEqual([(a["n"], a["status"], a["http_429"]) for a in r["attempts"]], [(1, "ok", 0), (2, "ok", 2)])
        self.assertEqual((r["status"], r["used_run"], r["http_429"]), ("ok", 2, 2))


class Shelf(unittest.TestCase):
    def artifact(self, mode):
        out = tmpdir(self) / "art"
        with mock.patch.dict(os.environ, {"FAKE_YAMA": mode}):
            run = collect(agents=["yamabiyori"], out_dir=out, checkouts={"yamabiyori": FAKE_YAMA},
                          pythons={"yamabiyori": sys.executable}, yama_limit=3, meta_fetch=lambda ph: META)   # config.yaml の値(5)
        return run, out

    def publish(self, art, existing=None):
        base = tmpdir(self)
        ex = existing or base / "empty"
        ex.mkdir(exist_ok=True)
        shelf.prepare(art, ex, base / "pub")
        return base / "pub", read_json(base / "pub/manifest.json")

    def test_ok_run_with_429_keeps_the_count_everywhere(self):
        run, art = self.artifact("rl2ok")
        y = run["agents"]["yamabiyori"]
        self.assertEqual((y["status"], y["http_429"], y["http_429_tolerated"]), ("ok", 2, 2))
        self.assertEqual(schema_errors(read_json(art / "run.json"), "biyori-collect-run"), [])
        logs = read_json(art / "logs/requests.json")
        self.assertEqual(schema_errors(logs, "biyori-request-log"), [])
        self.assertEqual((logs["agents"]["yamabiyori"]["http_429"], logs["agents"]["yamabiyori"]["by_status"]["429"]), (2, 2))
        _, m = self.publish(art)
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])
        self.assertEqual((m["agents"]["yamabiyori"]["status"], m["agents"]["yamabiyori"]["http_429"]), ("ok", 2))
        self.assertEqual(m["agents"]["yamabiyori"]["attempts"][0]["http_429"], 2)
        self.assertIn("- 429: yamabiyori 2 回(待って取り直し、全座そろった)", shelf.render_summary(art))

    def test_rate_limited_run_keeps_the_previous_files(self):
        _, first = self.artifact("ok")
        prev, pm = self.publish(first)
        self.assertIn("- 429: なし", shelf.render_summary(first))
        run, art = self.artifact("rl1partial")
        _, m = self.publish(art, existing=prev)
        y = m["agents"]["yamabiyori"]
        self.assertEqual((y["status"], y["reason"], y["http_429"]), ("kept_previous", "rate_limited", 1))
        self.assertEqual(y["kept_from"], pm["finished_at"])
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])
        self.assertIn("- 429: yamabiyori 1 回(rate_limited。取り直しの回は始めず、棚は前回のまま)", shelf.render_summary(art))


if __name__ == "__main__":
    unittest.main()
