"""--yama-limit の検査(all = 全座、1 以上の整数。空・それ以外・0 以下はエラーで、通信の前に止まる)。通信しない。"""
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
from collect.run import collect, parse_yama_limit

META = read_json(FIX / "meta" / "before.json")
OTHER = "feature/reuse-connection"
HEAD = "この回は棚(data ブランチ)に載せません(yama_limit_not_all)"
WHY = "一部の山だけの取得だったため(yama_limit が 3)"
HOW = "棚に残すには、yama_limit を all にして実行し直してください"


def artifact(test, limit, ref="main"):
    out = tmpdir(test) / "art"
    with mock.patch.dict(os.environ, {"FAKE_YAMA": "ok"}):
        collect(agents=["yamabiyori"], out_dir=out, checkouts={"yamabiyori": FAKE_YAMA}, pythons={"yamabiyori": sys.executable},
                yama_limit=limit, yamabiyori_ref=ref, meta_fetch=lambda ph: META)
    return out


class Parse(unittest.TestCase):
    def test_all_means_every_mountain(self):
        self.assertIsNone(parse_yama_limit("all"))
        self.assertIsNone(parse_yama_limit(" all "))

    def test_positive_integers(self):
        self.assertEqual(parse_yama_limit("3"), 3)
        self.assertEqual(parse_yama_limit("76"), 76)
        self.assertEqual(parse_yama_limit("1"), 1)

    def test_errors(self):
        for raw in ("", "  ", None, "0", "-1", "-3", "ALL", "All", "3.5", "1e2", "three", "3 座", "３", "all,3"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_yama_limit(raw)


class MainRun(unittest.TestCase):
    def args(self, limit):
        return argparse.Namespace(agents="yamabiyori", out="unused", yamabiyori_checkout="x", yamabiyori_python=None,
                                  yama_limit=limit, trigger="workflow_dispatch", concierge_commit=None)

    def test_bad_value_stops_before_collect(self):
        for raw in ("", "0", "abc"):
            with self.subTest(raw=raw), mock.patch.object(run_mod, "collect") as c, redirect_stderr(io.StringIO()) as err:
                self.assertEqual(run_mod.main_run(self.args(raw)), 2)
                c.assert_not_called()                      # 取得(通信)を始めない
                self.assertIn("通信していません", err.getvalue())

    def test_all_and_number_are_passed_to_collect(self):
        for raw, want in (("all", None), ("3", 3)):
            with self.subTest(raw=raw), mock.patch.object(run_mod, "collect", return_value={"agents": {}}) as c, \
                    mock.patch.object(run_mod, "read_json", return_value={}), redirect_stdout(io.StringIO()):
                self.assertEqual(run_mod.main_run(self.args(raw)), 0)
                self.assertEqual(c.call_args.kwargs["yama_limit"], want)

    def test_flag_is_required(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["run", "--agents", "yamabiyori", "--out", "o", "--yamabiyori-checkout", "x"])


class NotAllIsNotPublished(unittest.TestCase):
    """一部の山だけを取った回は、棚を置き換えない(利用者の決定 2026-11-25)。"""

    def prepare_fails(self, art):
        base = tmpdir(self)
        (base / "empty").mkdir()
        with self.assertRaisesRegex(ValueError, "yama_limit_not_all"):
            shelf.prepare(art, base / "empty", base / "out")
        self.assertFalse((base / "out").exists())                          # 何も組み立てない

    def test_a_part_is_collected_but_not_published(self):
        art = artifact(self, 3)
        run = read_json(art / "run.json")
        self.assertEqual(schema_errors(run, "biyori-collect-run"), [])
        self.assertEqual(run["agents"]["yamabiyori"]["status"], "ok")      # 取得は行う(verdict は緑)
        self.assertEqual(run["publish_blocked"], "yama_limit_not_all")
        self.prepare_fails(art)

    def test_all_is_published(self):
        art = artifact(self, None)
        run = read_json(art / "run.json")
        self.assertIsNone(run["publish_blocked"])
        base = tmpdir(self)
        (base / "empty").mkdir()
        shelf.prepare(art, base / "empty", base / "out")
        self.assertTrue((base / "out" / "manifest.json").is_file())
        self.assertNotIn("載せません", shelf.render_summary(art))

    def test_prepare_also_checks_the_number_of_mountains(self):
        # run.json の publish_blocked が空でも、山の数(limit)があれば載せない
        art = artifact(self, 3)
        run = read_json(art / "run.json")
        run["publish_blocked"] = None
        (art / "run.json").write_text(json.dumps(run), encoding="utf-8")
        self.prepare_fails(art)

    def test_the_summary_says_why_and_what_to_do(self):
        text = shelf.render_summary(artifact(self, 3))
        for want in ("**この回は棚(data ブランチ)に載せません**(yama_limit_not_all)", WHY, "棚は置き換えていません", HOW):
            self.assertIn(want, text)

    def test_the_log_says_why_and_what_to_do(self):
        out = io.StringIO()
        args = argparse.Namespace(agents="yamabiyori", out=str(tmpdir(self) / "art"), yamabiyori_checkout=FAKE_YAMA, yamabiyori_python=None,
                                  yama_limit="3", yamabiyori_ref="main", trigger="workflow_dispatch", concierge_commit=None)
        with mock.patch.object(run_mod, "collect", return_value={"agents": {}, "yama_limit": 3, "publish_blocked": "yama_limit_not_all"}),                 mock.patch.object(run_mod, "read_json", return_value={}), redirect_stdout(out):
            self.assertEqual(run_mod.main_run(args), 0)
        for want in (HEAD, WHY, "棚は置き換えていません", HOW):
            self.assertIn(want, out.getvalue())

    def test_both_reasons_are_told(self):
        text = shelf.render_summary(artifact(self, 3, ref=OTHER))
        self.assertIn("yamabiyori_ref_not_main", text)
        self.assertIn("yama_limit_not_all", text)

    def test_the_limit_does_not_matter_without_yamabiyori(self):
        self.assertIsNone(run_mod.publish_blocked(["hoshibiyori"], "main", 3))
        self.assertEqual(run_mod.publish_blocked(["yamabiyori", "hoshibiyori"], "main", 3), "yama_limit_not_all")
        self.assertIsNone(run_mod.publish_blocked(["yamabiyori"], "main", None))

    def test_check_inputs_tells_before_the_collection(self):
        for raw, code, want in (("all", 0, "yama_limit=all"), ("3", 0, "棚は置き換えません"), (" all ", 2, "")):
            with self.subTest(raw=raw):
                out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
                with redirect_stdout(out), redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(cli.main(["check-inputs", "--yama-limit", raw, "--yamabiyori-ref", "main"]), code)
                out.flush()
                text = out.buffer.getvalue().decode("utf-8")
                self.assertIn(want, text)
                self.assertEqual("載せません" in text, raw == "3")
                self.assertEqual("通信していません" in err.getvalue(), code == 2)


if __name__ == "__main__":
    unittest.main()
