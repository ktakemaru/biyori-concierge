"""ヤマビヨリの出力 → 共通の形(biyori-proposal/1)。記録済みの入力(ヤマビヨリ tests/fixtures/report/explore.json の写し)を使う。通信しない。"""
import json
import unittest
from datetime import datetime

from helpers import FAKE_YAMA

from collect import yamabiyori as Y
from collect.common import JST, read_json, schema_errors

NOW = datetime(2026, 10, 12, 5, 10, tzinfo=JST)
FETCHED = datetime(2026, 10, 12, 4, 38, tzinfo=JST)


def native():
    return read_json(FAKE_YAMA / "explore.json")


def convert(n=None, **kw):
    args = dict(now=NOW, fetched_at=FETCHED, native_path="yamabiyori/explore.json", agent_version="1.9.0",
                agent_commit="b0183552217c9dc116547c272f3b4192f44f6ea0", mountains=Y.load_mountains(FAKE_YAMA))
    args.update(kw)
    return Y.convert(n or native(), **args)


class Mountains(unittest.TestCase):
    def test_read_by_ast_without_running_the_code(self):
        ms = Y.load_mountains(FAKE_YAMA)                     # 写しの先頭の import requests は実行されない
        self.assertEqual(len(ms), 76)
        self.assertEqual(ms[0], {"id": "m001", "name": "谷川岳", "lat": 36.837, "lon": 138.9297, "elevation_m": 1977,
                                 "region": "関東甲信", "access": "ロープウェイ/ゴンドラ"})
        self.assertEqual(ms[1]["id"], "m002")
        self.assertEqual(len({m["id"] for m in ms}), 76)

    def test_mountains_doc_matches_its_schema(self):
        doc = Y.mountains_doc(Y.load_mountains(FAKE_YAMA), None, "1.9.0")
        self.assertEqual(schema_errors(doc, "biyori-mountains"), [])
        self.assertEqual(doc["count"], 76)

    def test_version_from_plugin_json(self):
        self.assertEqual(Y.load_version(FAKE_YAMA), "1.9.0")

    def test_command_is_an_array_with_utf8_and_optional_limit(self):
        self.assertEqual(Y.command("py", "/c", "/o.json")[1:3], ["-X", "utf8"])
        self.assertNotIn("--limit", Y.command("py", "/c", "/o.json"))
        self.assertEqual(Y.command("py", "/c", "/o.json", 3)[-2:], ["--limit", "3"])


class Convert(unittest.TestCase):
    def test_fixture_becomes_a_valid_proposal(self):
        out = convert()
        self.assertEqual(schema_errors(out, "biyori-proposal"), [])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["proposals"]), 24)                                      # 17 go + 7 no(hub の対応表と同じ件数)
        self.assertEqual(sum(p["suitability"]["band"] == "go" for p in out["proposals"]), 17)
        p = out["proposals"][0]
        self.assertEqual(p["id"], "yamabiyori:explore:2026-10-12:m002")
        self.assertEqual(p["place"]["site_ref"], "yamabiyori:m002")
        self.assertEqual(p["place"]["name"], "八ヶ岳(赤岳)")
        self.assertEqual(p["uncertainty"]["lead_days"], 0)
        self.assertEqual(p["uncertainty"]["reliable_up_to_days"], 3)
        self.assertEqual(out["data_as_of"][0]["fetched_at"], "2026-10-12T04:38:00+09:00")

    def test_same_input_same_output(self):
        a = json.dumps(convert(), ensure_ascii=False, sort_keys=True)
        b = json.dumps(convert(), ensure_ascii=False, sort_keys=True)
        self.assertEqual(a, b)

    def test_band_boundary_is_70_inclusive(self):
        self.assertEqual(Y.band(70.0), "go")
        self.assertEqual(Y.band(69.99), "no")
        self.assertIsNone(Y.band(None))
        self.assertIsNone(Y.band(True))

    def test_hazard_levels_hard_only_for_warning_and_danger(self):
        c = Y._constraints({"thunder": "注意", "wind": "警戒", "cold": "危険"})
        self.assertEqual([(x["hazard"], x["level"], x["hard"]) for x in c],
                         [("thunder", "注意", False), ("wind", "警戒", True), ("cold", "危険", True)])
        self.assertEqual(Y._constraints({"thunder": "-", "wind": "-", "cold": "-"}), [])
        self.assertTrue(Y._constraints_from_class("warning")[0]["hard"])
        self.assertFalse(Y._constraints_from_class("caution")[0]["hard"])

    def test_score_only_rows_have_no_evidence(self):
        no = [p for p in convert()["proposals"] if p["suitability"]["band"] == "no"]
        self.assertTrue(no)
        self.assertTrue(all(p["evidence"] == [] and p["details"]["detail_level"] == "score_only" for p in no))

    def test_sun_times_give_activity_windows(self):
        sun = Y.load_sun_times(FAKE_YAMA / "cache", Y.load_mountains(FAKE_YAMA))        # 合成の日の出 5:40・日没 17:10(赤岳だけ)
        out = convert(sun_times=sun)
        ps = {p["id"]: p for p in out["proposals"]}
        self.assertEqual(ps["yamabiyori:explore:2026-10-12:m002"]["time_window"],
                         {"start": "2026-10-12T04:40+09:00", "end": "2026-10-12T17:40+09:00", "kind": "activity_window"})
        self.assertEqual(ps["yamabiyori:explore:2026-10-12:m003"]["time_window"]["kind"], "calendar_day")

    def test_model_runs_go_into_data_as_of(self):
        out = convert(model_runs={"jma_msm": {"init": "2026-10-11T15:00:00Z", "available": None, "same_before_after": True}})
        self.assertEqual(out["data_as_of"][1], {"source": "Open-Meteo jma_msm", "source_type": "forecast",
                                                "run_time": "2026-10-11T15:00:00Z", "fetched_at": "2026-10-12T04:38:00+09:00"})

    def test_unknown_mountain_is_dropped_with_a_warning_not_guessed(self):
        n = native()
        n["days"][0]["rows"][0]["mountain"] = "架空の山(1234m)"
        n["days"][0]["all"][[a["mountain"] for a in n["days"][0]["all"]].index("八ヶ岳(赤岳)(2899m)")]["mountain"] = "架空の山(1234m)"
        out = convert(n)
        self.assertEqual(out["status"], "partial")
        self.assertEqual(len(out["proposals"]), 23)
        self.assertTrue(any("架空の山" in w for w in out["diagnostics"]["warnings"]))

    def test_partial_fetch_is_marked(self):
        n = native()
        n["fetched"] = 2
        out = convert(n)
        self.assertEqual((out["status"], out["status_reason"]), ("partial", "partial_fetch"))


class OutputShape(unittest.TestCase):
    def test_fixture_has_no_problems(self):
        self.assertEqual(Y.output_problems(native()), [])

    def test_wrong_shapes_are_reported(self):
        cases = {"schema": ("schema", "yamabiyori-report-data/2"), "mode": ("mode", "diagnosis"), "days": ("days", [])}
        for name, (k, v) in cases.items():
            with self.subTest(name):
                n = native()
                n[k] = v
                self.assertTrue(Y.output_problems(n))
                with self.assertRaises(ValueError):
                    convert(n)
        n = native()
        del n["days"][0]["rows"][0]["score"]
        self.assertTrue(Y.output_problems(n))
        self.assertTrue(Y.output_problems([]))

    def test_naive_times_are_refused(self):
        with self.assertRaises(ValueError):
            convert(now=datetime(2026, 10, 12, 5, 0))


class Coverage(unittest.TestCase):
    def test_text(self):
        from collect.yamabiyori import coverage_text
        self.assertEqual(coverage_text({"pool_size": 76, "fetched": 60, "missing": 16, "total_mountains": 76}), "76座のうち60座(16座取得できず)")
        self.assertEqual(coverage_text({"pool_size": 76, "fetched": 76, "missing": 0, "total_mountains": 76}), "76座のうち76座")
        self.assertEqual(coverage_text({"pool_size": 3, "fetched": 3, "missing": 0, "total_mountains": 76}), "3座のうち3座(全76座の先頭3座)")
        self.assertEqual(coverage_text(None), "不明")

    def test_counts_are_checked(self):
        from collect.yamabiyori import output_problems
        base = {"schema": "yamabiyori-report-data/1", "mode": "explore", "days": [{"date": "2026-11-11", "rows": [], "all": []}]}
        self.assertEqual(output_problems(dict(base, pool_size=76, fetched=60)), [])
        for pool, fetched in ((76, 77), (None, 60), (76, None), ("76", 60), (76, -1), (True, 1), (76, 6.0)):
            with self.subTest(pool=pool, fetched=fetched):
                self.assertTrue(output_problems(dict(base, pool_size=pool, fetched=fetched)))


if __name__ == "__main__":
    unittest.main()
