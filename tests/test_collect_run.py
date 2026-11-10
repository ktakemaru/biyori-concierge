"""1回の取得(collect/run.py)を、偽のヤマビヨリ(tests/fixtures/yamabiyori。通信しない)と偽のメタデータで通す。
本物の子プロセスを計測フックつきで起動する(フックの許可・記録・中止の扱いまで確かめる)。"""
import os
import sys
import unittest
from unittest import mock

from helpers import FAKE_YAMA, FIX, tmpdir

from collect.common import read_json, schema_errors
from collect.run import collect, slot_of

META = read_json(FIX / "meta" / "before.json")


def run(test, mode="ok", meta_after=META, limit=3, agents=("yamabiyori",)):
    out = tmpdir(test) / "art"
    with mock.patch.dict(os.environ, {"FAKE_YAMA": mode}):
        r = collect(agents=list(agents), out_dir=out, checkouts={"yamabiyori": FAKE_YAMA}, pythons={"yamabiyori": sys.executable},
                    yama_limit=limit, concierge_commit="0" * 40, meta_fetch=lambda ph: META if ph == "before" else meta_after)
    return r, out


class Success(unittest.TestCase):
    def test_artifact_has_the_files_and_a_valid_run_json(self):
        r, out = run(self)
        y = r["agents"]["yamabiyori"]
        self.assertEqual((y["status"], y["version"], y["limit"], y["proposals"]), ("ok", "1.9.0", 3, 24))
        for rel in ("run.json", "yamabiyori/explore.json", "yamabiyori/mountains.json", "proposals/yamabiyori.json", "logs/requests.json"):
            self.assertTrue((out / rel).is_file(), rel)
        self.assertEqual(schema_errors(read_json(out / "run.json"), "biyori-collect-run"), [])
        self.assertEqual(schema_errors(read_json(out / "proposals/yamabiyori.json"), "biyori-proposal"), [])
        self.assertEqual(schema_errors(read_json(out / "logs/requests.json"), "biyori-request-log"), [])
        self.assertEqual(read_json(out / "yamabiyori/explore.json"), read_json(FAKE_YAMA / "explore.json"))     # そのまま
        self.assertEqual(r["model_runs"]["jma_msm"], {"init": "2026-09-24T03:00:00Z", "available": "2026-09-24T08:09:54Z",
                                                      "same_before_after": True})
        self.assertEqual(r["concierge_commit"], "0" * 40)
        self.assertEqual(y["coverage"], {"pool_size": 3, "fetched": 3, "missing": 0, "total_mountains": 76})

    def test_not_every_mountain_is_incomplete_not_ok(self):
        # ヤマビヨリが対象の山を全部は取れなかった回(collect #4: 76 座のうち 60 座)は ok と表示しない
        r, out = run(self, mode="partial")
        y = r["agents"]["yamabiyori"]
        self.assertEqual((y["status"], y["reason"]), ("incomplete", "partial_fetch"))
        self.assertEqual(y["coverage"], {"pool_size": 3, "fetched": 2, "missing": 1, "total_mountains": 76})
        self.assertIn("3座のうち2座(1座取得できず)", y["detail"])
        self.assertEqual(schema_errors(read_json(out / "run.json"), "biyori-collect-run"), [])
        for rel in ("yamabiyori/explore.json", "proposals/yamabiyori.json"):     # ファイルは作る(載せるかは publish の決まり)
            self.assertTrue((out / rel).is_file(), rel)
        self.assertEqual(read_json(out / "proposals/yamabiyori.json")["status"], "partial")

    def test_verdict_is_red_for_incomplete(self):
        import io
        from contextlib import redirect_stdout
        from collect.__main__ import main
        def out_buf():                       # main() は sys.stdout.reconfigure を呼ぶので、TextIOWrapper にする
            return io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        _, out = run(self, mode="partial")
        with redirect_stdout(out_buf()) as buf:
            self.assertEqual(main(["verdict", "--artifact", str(out)]), 1)
            buf.flush()
            text = buf.buffer.getvalue().decode("utf-8")
        self.assertIn("yamabiyori(incomplete: 3座のうち2座(1座取得できず)", text)
        _, ok = run(self)
        with redirect_stdout(out_buf()):
            self.assertEqual(main(["verdict", "--artifact", str(ok)]), 0)

    def test_child_sees_japan_time(self):
        r, out = run(self, mode="tz")
        self.assertEqual(read_json(out / "yamabiyori/explore.json")["generated"], "Asia/Tokyo")

    def test_run_changed_between_before_and_after(self):
        after = {"models": dict(META["models"], jma_msm=dict(META["models"]["jma_msm"], last_run_initialisation_time=1790229600))}
        r, _ = run(self, meta_after=after)
        self.assertEqual(r["model_runs"]["jma_msm"]["same_before_after"], False)
        self.assertEqual(r["model_runs"]["jma_msm"]["init"], "2026-09-24T06:00:00Z")
        self.assertEqual(r["model_runs"]["ecmwf_ifs025"]["same_before_after"], True)

    def test_unreadable_metadata_gives_nulls_not_guesses(self):
        r, _ = run(self, meta_after=None)
        self.assertEqual(r["model_runs"]["jma_msm"]["same_before_after"], None)
        out = tmpdir(self) / "a"
        with mock.patch.dict(os.environ, {"FAKE_YAMA": "ok"}):
            r = collect(agents=["yamabiyori"], out_dir=out, checkouts={"yamabiyori": FAKE_YAMA}, pythons={"yamabiyori": sys.executable},
                        meta_fetch=lambda ph: None)
        self.assertEqual(r["model_runs"]["jma_msm"], {"init": None, "available": None, "same_before_after": None})

    def test_slot(self):
        from datetime import datetime
        from collect.common import JST
        self.assertEqual(slot_of(datetime(2026, 11, 14, 4, 31, tzinfo=JST)), "morning")
        self.assertEqual(slot_of(datetime(2026, 11, 14, 16, 50, tzinfo=JST)), "evening")


class MetadataChild(unittest.TestCase):
    def test_metadata_fetch_goes_through_the_hook_and_undeclared_means_no_send(self):
        from collect import meta
        d = tmpdir(self)
        with mock.patch.object(meta, "allow_hosts", lambda kind: []):
            doc, res = meta.fetch_meta(sys.executable, d / "meta.json", d / "req.jsonl")
        self.assertIsNone(doc)
        self.assertEqual(res.returncode, 75, res.stderr_tail)                     # 送る前にフックが止めた
        self.assertEqual(res.blocked_host, "api.open-meteo.com")
        self.assertEqual(res.records, [])
        self.assertEqual(meta.model_runs(doc, None)["jma_msm"], {"init": None, "available": None, "same_before_after": None, "init_before": None})


class Failures(unittest.TestCase):
    def check(self, mode, status, reason):
        r, out = run(self, mode=mode)
        y = r["agents"]["yamabiyori"]
        self.assertEqual((y["status"], y["reason"]), (status, reason), y)
        self.assertFalse((out / "proposals" / "yamabiyori.json").exists())
        self.assertFalse((out / "yamabiyori" / "explore.json").exists())
        self.assertIsNone(y["data_time"])
        return r, out

    def test_nonzero_exit(self):
        self.check("exit2", "failed", "exit_2")

    def test_missing_counts_is_unexpected_output(self):
        r, _ = self.check("no_counts", "failed", "unexpected_output")
        self.assertIn("pool_size", r["agents"]["yamabiyori"]["detail"])

    def test_wrong_schema_string(self):
        r, _ = self.check("bad_schema", "failed", "unexpected_output")
        self.assertIn("yamabiyori-report-data/2", r["agents"]["yamabiyori"]["detail"])

    def test_no_output(self):
        self.check("no_output", "failed", "no_output")

    def test_undeclared_host_is_stopped_and_named(self):
        r, out = self.check("net", "failed", "blocked_host")
        self.assertEqual(r["agents"]["yamabiyori"]["detail"], "blocked.example.invalid")
        self.assertEqual(read_json(out / "logs/requests.json")["agents"]["yamabiyori"]["blocked_host"], "blocked.example.invalid")

    def test_429_is_rate_limited_and_not_retried(self):
        r, out = self.check("429", "rate_limited", "rate_limited")
        self.assertEqual(r["agents"]["yamabiyori"]["requests"], 1)                  # 1回だけ(再試行しない)
        self.assertEqual(read_json(out / "logs/requests.json")["total"]["by_status"], {"429": 1})

    def test_hoshibiyori_is_not_run_yet(self):
        r, _ = run(self, agents=("yamabiyori", "hoshibiyori"))
        self.assertEqual(r["agents"]["hoshibiyori"]["status"], "skipped")
        self.assertEqual(r["agents"]["yamabiyori"]["status"], "ok")                 # 片方が動かなくても、もう片方は進む


if __name__ == "__main__":
    unittest.main()
