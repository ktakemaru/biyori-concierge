"""リポジトリの決まり: スキーマが正しい JSON Schema であること・テスト中はソケットが使えないこと・
取得の側だけが通信の部品を持つこと・手元だけの設定を commit しないこと。通信しない。"""
import json
import socket
import unittest

from jsonschema import Draft202012Validator
from helpers import ROOT

from collect.common import allow_hosts, config


class Schemas(unittest.TestCase):
    def test_all_schemas_are_valid(self):
        files = sorted((ROOT / "schemas").glob("*.schema.json"))
        self.assertEqual([f.name for f in files], ["biyori-collect-run.schema.json", "biyori-mountains.schema.json",
                                                   "biyori-proposal.schema.json", "biyori-request-log.schema.json",
                                                   "biyori-shelf.schema.json"])
        for f in files:
            with self.subTest(f.name):
                d = json.loads(f.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(d)
                self.assertEqual(d["$id"], f.name.replace(".schema.json", "") + "/1")


class NoNetwork(unittest.TestCase):
    def test_sockets_are_blocked_in_tests(self):
        with self.assertRaises(AssertionError):
            socket.create_connection(("api.open-meteo.com", 443))
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("api.open-meteo.com", 443)


class Hosts(unittest.TestCase):
    def test_only_open_meteo_is_declared_at_first(self):
        self.assertEqual(allow_hosts("yamabiyori"), ["api.open-meteo.com"])
        self.assertEqual(allow_hosts("meta"), ["api.open-meteo.com"])
        self.assertEqual(allow_hosts("unknown"), [])


class LocalFiles(unittest.TestCase):
    def test_gitignore(self):
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for pat in ("config.local.yaml", "__pycache__/", "/_out/", "/_agents/", "/_venvs/"):
            self.assertIn(pat, gi)
        self.assertTrue((ROOT / "config.local.example.yaml").is_file())

    def test_provisional_values_are_marked(self):
        text = (ROOT / "config.yaml").read_text(encoding="utf-8")
        for key in ("near_km: 20", "max_chars: 2000", "max_requests: 300", "timeout_s: 3600", "backtest_min_gap_minutes: 30"):
            i = text.index(key)
            block = text[max(0, text.rfind("\n\n", 0, i)):i]
            self.assertIn("仮置き", block[-400:], key)
        self.assertEqual(config()["origin"]["max_straight_line_km"], 250)


if __name__ == "__main__":
    unittest.main()
