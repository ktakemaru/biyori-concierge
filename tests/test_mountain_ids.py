"""山の ID は MOUNTAINS の "id" をそのまま使う(指示書 D10。2026-11-22)。並び順では作らない。通信しない。"""
import json
import os
import re
import shutil
import sys
import unittest
from datetime import datetime
from unittest import mock

from helpers import FAKE_YAMA, tmpdir

from collect import yamabiyori as Y
from collect.common import JST, read_json, schema_errors
from collect.run import run_yamabiyori

NOW = datetime(2026, 10, 12, 5, 10, tzinfo=JST)
FETCHED = datetime(2026, 10, 12, 4, 38, tzinfo=JST)
CORE = "mountain_weather_core.py"
LINE_RE = re.compile(r'^\s*\{"id": "m\d{3}", "name": .*\},\s*$')


def mountain_lines(src):
    return [i for i, line in enumerate(src.splitlines(keepends=True)) if LINE_RE.match(line)]


def fake_checkout(test, edit):
    """偽のヤマビヨリを一時フォルダに写し、MOUNTAINS の行を edit(lines, idx) で書き換える。"""
    d = tmpdir(test) / "yama"
    shutil.copytree(FAKE_YAMA, d)
    lines = (d / CORE).read_text(encoding="utf-8").splitlines(keepends=True)
    idx = mountain_lines("".join(lines))
    edit(lines, idx)
    (d / CORE).write_text("".join(lines), encoding="utf-8", newline="\n")
    return d


def convert(n, mountains=None):
    return Y.convert(n, now=NOW, fetched_at=FETCHED, native_path="yamabiyori/explore.json", agent_version="1.10.1",
                     agent_commit=None, mountains=mountains or Y.load_mountains(FAKE_YAMA))


def with_ids(n, mountains):
    """古い形の見本(行に id なし)に、ヤマビヨリ 1.10.x と同じく各行の id を足す(名前と標高で引く)。"""
    key = {f"{m['name']}({m['elevation_m']}m)": m["id"] for m in mountains}
    for d in n["days"]:
        for r in d["rows"] + d["all"]:
            r["id"] = key[r["mountain"]]
    return n


class LoadMountains(unittest.TestCase):
    def test_ids_come_from_the_list_not_from_the_order(self):
        def reverse(lines, idx):
            body = [lines[i] for i in idx]
            for i, line in zip(idx, reversed(body)):
                lines[i] = line
        ms = Y.load_mountains(fake_checkout(self, reverse))
        self.assertEqual(ms[0]["id"], "m076")                        # 並びの先頭でも m001 にならない
        self.assertEqual({m["id"]: m["name"] for m in ms}["m002"], "八ヶ岳(赤岳)")
        self.assertEqual({m["id"]: m["name"] for m in ms}, {m["id"]: m["name"] for m in Y.load_mountains(FAKE_YAMA)})

    def test_fixture_ids_are_the_real_ones(self):
        ms = Y.load_mountains(FAKE_YAMA)
        self.assertEqual(sorted(m["id"] for m in ms), [f"m{i:03d}" for i in range(1, 77)])
        self.assertEqual(Y.mountains_doc(ms, None, "1.10.1")["id_rule"].count("並び順では作らない"), 1)

    def bad(self, edit):
        d = fake_checkout(self, edit)
        with self.assertRaises(ValueError) as cm:
            Y.load_mountains(d)
        return d, str(cm.exception)

    def test_missing_id_is_refused(self):
        def drop(lines, idx):
            lines[idx[5]] = re.sub(r'"id": "m\d{3}", ', "", lines[idx[5]])
        _, msg = self.bad(drop)
        self.assertIn("id が無い", msg)

    def test_bad_id_forms_are_refused(self):
        for new in ('"id": "m1"', '"id": "x001"', '"id": "u001"', '"id": 3', '"id": None', '"id": "m0011"'):
            with self.subTest(new):
                def form(lines, idx, new=new):
                    lines[idx[0]] = re.sub(r'"id": "m\d{3}"', new, lines[idx[0]])
                _, msg = self.bad(form)
                self.assertIn("形でない", msg)

    def test_duplicate_id_is_refused(self):
        def dup(lines, idx):
            lines[idx[1]] = lines[idx[1]].replace('"id": "m002"', '"id": "m001"')
        _, msg = self.bad(dup)
        self.assertIn("2 つ以上", msg)

    def test_unreadable_before_any_request(self):
        def drop(lines, idx):
            lines[idx[0]] = re.sub(r'"id": "m\d{3}", ', "", lines[idx[0]])
        d = fake_checkout(self, drop)
        out = tmpdir(self)
        with mock.patch.dict(os.environ, {"FAKE_YAMA": "ok"}):
            r = run_yamabiyori(checkout=d, python=sys.executable, out_dir=out / "art", limit=3,
                               cfg={"max_requests": 450, "timeout_s": 3600, "max_runs": 3, "total_timeout_s": 4500})
        self.assertEqual((r["status"], r["reason"], r["requests"]), ("failed", "mountains_unreadable", 0))
        self.assertIn("id が無い", r["detail"])
        self.assertNotIn("attempts", r)                               # 子プロセスを起動していない
        self.assertFalse(list((out / "art" / "raw").glob("*requests.jsonl")))


class MatchById(unittest.TestCase):
    def native(self):
        return read_json(FAKE_YAMA / "explore.json")

    def test_rows_with_ids_give_the_same_proposals_as_name_matching(self):
        ms = Y.load_mountains(FAKE_YAMA)
        a = convert(self.native())
        b = convert(with_ids(self.native(), ms))
        self.assertEqual(schema_errors(b, "biyori-proposal"), [])
        strip = lambda out: [dict(p, details=dict(p["details"], native_row=None)) for p in out["proposals"]]   # noqa: E731
        self.assertEqual(json.dumps(strip(a), ensure_ascii=False), json.dumps(strip(b), ensure_ascii=False))
        self.assertEqual(b["status"], "ok")

    def test_id_decides_the_mountain(self):
        ms = Y.load_mountains(FAKE_YAMA)
        n = with_ids(self.native(), ms)
        # 一覧の側で m002 の標高を変えても、行の id で引くので候補になる(名前と標高の突き合わせなら外れる)
        ms2 = [dict(m, elevation_m=2900) if m["id"] == "m002" else m for m in ms]
        out = convert(n, ms2)
        self.assertIn("yamabiyori:explore:2026-10-12:m002", {p["id"] for p in out["proposals"]})
        self.assertEqual(convert(self.native(), ms2)["status"], "partial")      # id なしの行は名前と標高で引くので外れる

    def test_name_mismatch_is_not_a_proposal_and_warns(self):
        n = with_ids(self.native(), Y.load_mountains(FAKE_YAMA))
        row = n["days"][0]["rows"][0]
        self.assertEqual(row["id"], "m002")
        row["id"] = "m003"                                            # 行は八ヶ岳(赤岳)、m003 は横岳
        out = convert(n)
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["status_reason"], "unresolved_place_or_score")
        ids = [p["id"] for p in out["proposals"] if p["details"]["date"] == "2026-10-12"]
        self.assertEqual(ids.count("yamabiyori:explore:2026-10-12:m003"), 1)   # 横岳の本当の行だけ
        self.assertTrue(any("ID のずれ" in w and "m003" in w for w in out["diagnostics"]["warnings"]))

    def test_unknown_id_is_dropped_not_matched_by_name(self):
        n = with_ids(self.native(), Y.load_mountains(FAKE_YAMA))
        n["days"][0]["rows"][0]["id"] = "m999"
        out = convert(n)
        self.assertEqual(out["status"], "partial")
        self.assertTrue(any("m999" in w for w in out["diagnostics"]["warnings"]))

    def test_null_id_falls_back_to_name_and_elevation(self):
        n = with_ids(self.native(), Y.load_mountains(FAKE_YAMA))
        for d in n["days"]:
            for r in d["rows"] + d["all"]:
                r["id"] = None                                         # 76 座に無い山の行は null
        out = convert(n)
        self.assertEqual((out["status"], len(out["proposals"])), ("ok", 24))


if __name__ == "__main__":
    unittest.main()
