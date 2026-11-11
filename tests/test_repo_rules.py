"""リポジトリの決まり: スキーマが正しい JSON Schema であること・テスト中はソケットが使えないこと・
取得の側だけが通信の部品を持つこと・手元だけの設定を commit しないこと。通信しない。"""
import json
import re
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
        for key in ("near_km: 20", "max_chars: 2000", "backtest_min_gap_minutes: 30"):
            self.assertIn("仮置き", self._comment_before(text, key), key)
        self.assertEqual(config()["origin"]["max_straight_line_km"], 250)

    def test_decided_limits_are_marked_and_match_the_decision(self):
        # 利用者の決定(2026-11-11): 山の通信の上限 450、時間の上限は 1 回ごと・合計とも 2700 秒
        text = (ROOT / "config.yaml").read_text(encoding="utf-8")
        for key in ("max_requests: 450", "timeout_s: 2700", "total_timeout_s: 2700"):
            self.assertIn("利用者の決定", self._comment_before(text, key), key)
        y = config()["collect"]["agents"]["yamabiyori"]
        self.assertEqual((y["max_requests"], y["timeout_s"], y["total_timeout_s"]), (450, 2700, 2700))
        self.assertLessEqual(y["timeout_s"], y["total_timeout_s"])

    @staticmethod
    def _comment_before(text, key):
        """key の行(行の頭から。timeout_s が total_timeout_s に当たらないように)の直前、空行までのコメント(最後の 400 字)。"""
        m = re.search(r"(?m)^[ \t]*" + re.escape(key) + r"\b", text)
        assert m, key
        i = m.start()
        return text[max(0, text.rfind("\n\n", 0, i)):i][-400:]


if __name__ == "__main__":
    unittest.main()
