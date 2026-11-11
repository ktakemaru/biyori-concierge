"""ヤマビヨリの ref(手動実行の yamabiyori_ref)。検査・記録(run.json・manifest・要約)と、main 以外の回を棚に載せないこと。通信しない。"""
import argparse
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from helpers import FAKE_YAMA, FIX, tmpdir

from collect import __main__ as cli
from collect import run as run_mod
from collect import shelf
from collect.common import read_json, schema_errors
from collect.run import collect, parse_yamabiyori_ref

META = read_json(FIX / "meta" / "before.json")
OTHER = "feature/reuse-connection"


def artifact(test, ref="main"):
    out = tmpdir(test) / "art"
    with mock.patch.dict(os.environ, {"FAKE_YAMA": "ok"}):
        collect(agents=["yamabiyori"], out_dir=out, checkouts={"yamabiyori": FAKE_YAMA}, pythons={"yamabiyori": sys.executable},
                yama_limit=3, yamabiyori_ref=ref, meta_fetch=lambda ph: META)
    return out


def prepare_into(test, art):
    base = tmpdir(test)
    (base / "empty").mkdir()
    shelf.prepare(art, base / "empty", base / "out")
    return base / "out"


def text_out():
    return io.TextIOWrapper(io.BytesIO(), encoding="utf-8")       # main() は sys.stdout.reconfigure を呼ぶ


def run_args(**kw):
    a = dict(agents="yamabiyori", out="unused", yamabiyori_checkout="x", yamabiyori_python=None, yama_limit="3",
             yamabiyori_ref="main", trigger="workflow_dispatch", concierge_commit=None)
    a.update(kw)
    return argparse.Namespace(**a)


class Parse(unittest.TestCase):
    def test_branches_and_commits(self):
        for ref in ("main", OTHER, "v1.9.0", "0123456789abcdef0123456789abcdef01234567", "a_b-c.d"):
            with self.subTest(ref=ref):
                self.assertEqual(parse_yamabiyori_ref(ref), ref)

    def test_errors(self):
        for raw in ("", "   ", None, " main", "main ", "-main", "/main", "feature/", "a..b", "a//b", "x.lock", "a b", "a;b",
                    "$(id)", "main\n", "ブランチ", "refs:heads", "x" * 201):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_yamabiyori_ref(raw)

    def test_check_inputs_command(self):
        for ref, warned in ((OTHER, True), ("main", False)):
            with self.subTest(ref=ref), redirect_stdout(text_out()) as buf:
                self.assertEqual(cli.main(["check-inputs", "--yama-limit", "all", "--yamabiyori-ref", ref]), 0)
                buf.flush()
                self.assertEqual("棚に載せません" in buf.buffer.getvalue().decode("utf-8"), warned)
        for limit, ref in (("3", ""), ("3", "-x"), ("0", "main")):
            with self.subTest(limit=limit, ref=ref), redirect_stdout(text_out()), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(cli.main(["check-inputs", "--yama-limit", limit, f"--yamabiyori-ref={ref}"]), 2)
                self.assertIn("通信していません", err.getvalue())

    def test_bad_ref_stops_before_collect(self):
        with mock.patch.object(run_mod, "collect") as c, redirect_stderr(io.StringIO()):
            self.assertEqual(run_mod.main_run(run_args(yamabiyori_ref="")), 2)
            c.assert_not_called()                                      # 取得(通信)を始めない

    def test_ref_is_passed_to_collect(self):
        with mock.patch.object(run_mod, "collect", return_value={"agents": {}}) as c, \
                mock.patch.object(run_mod, "read_json", return_value={}), redirect_stdout(io.StringIO()):
            self.assertEqual(run_mod.main_run(run_args(yamabiyori_ref=OTHER)), 0)
        self.assertEqual(c.call_args.kwargs["yamabiyori_ref"], OTHER)


class Recorded(unittest.TestCase):
    def test_main_is_recorded_and_published(self):
        art = artifact(self)
        run = read_json(art / "run.json")
        self.assertEqual(schema_errors(run, "biyori-collect-run"), [])
        self.assertEqual((run["yamabiyori_ref"], run["publish_blocked"], run["agents"]["yamabiyori"]["ref"]), ("main", None, "main"))
        m = read_json(prepare_into(self, art) / "manifest.json")
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])
        self.assertEqual(m["agents"]["yamabiyori"]["ref"], "main")
        self.assertEqual(m["agents"]["yamabiyori"]["commit"], run["agents"]["yamabiyori"]["commit"])
        text = shelf.render_summary(art)
        self.assertIn("- ヤマビヨリの取り出し: ref `main`、commit `", text)
        self.assertNotIn("載せません", text)

    def test_other_ref_is_recorded_and_not_published(self):
        art = artifact(self, ref=OTHER)
        run = read_json(art / "run.json")
        self.assertEqual(schema_errors(run, "biyori-collect-run"), [])
        self.assertEqual(run["agents"]["yamabiyori"]["status"], "ok")      # 取得そのものは ok(verdict は緑)
        self.assertEqual((run["yamabiyori_ref"], run["publish_blocked"]), (OTHER, "yamabiyori_ref_not_main"))
        self.assertEqual(run["agents"]["yamabiyori"]["ref"], OTHER)
        text = shelf.render_summary(art)
        self.assertIn(f"ref `{OTHER}`", text)
        self.assertIn("**この回は棚(data ブランチ)に載せません**(yamabiyori_ref_not_main)", text)
        base = tmpdir(self)
        (base / "empty").mkdir()
        with self.assertRaises(ValueError):
            shelf.prepare(art, base / "empty", base / "out")
        self.assertFalse((base / "out").exists())                          # 何も組み立てない

    def test_prepare_also_checks_the_agent_ref(self):
        # run.json の publish_blocked が空でも、ヤマビヨリの ref が main でなければ載せない
        art = artifact(self, ref=OTHER)
        run = read_json(art / "run.json")
        run["publish_blocked"] = None
        (art / "run.json").write_text(json.dumps(run), encoding="utf-8")
        base = tmpdir(self)
        (base / "empty").mkdir()
        with self.assertRaises(ValueError):
            shelf.prepare(art, base / "empty", base / "out")

    def test_ref_does_not_matter_without_yamabiyori(self):
        self.assertIsNone(run_mod.publish_blocked(["hoshibiyori"], OTHER))
        self.assertEqual(run_mod.publish_blocked(["yamabiyori", "hoshibiyori"], OTHER), "yamabiyori_ref_not_main")


if __name__ == "__main__":
    unittest.main()
