"""--yama-limit の検査(all = 全座、1 以上の整数。空・それ以外・0 以下はエラーで、通信の前に止まる)。通信しない。"""
import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import helpers  # noqa: F401  (ソケット禁止)

from collect import __main__ as cli
from collect import run as run_mod
from collect.run import parse_yama_limit


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


if __name__ == "__main__":
    unittest.main()
