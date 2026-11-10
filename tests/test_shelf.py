"""棚(data ブランチ)の木の組み立て(collect/shelf.py)。記録済みの入力から manifest・山のファイル・提案ができること、
ビヨリごとの「成功したら入れ替える」、個人の設定・座標が入らないこと。通信しない。"""
import json
import os
import sys
import unittest
from unittest import mock

from helpers import FAKE_YAMA, FIX, ROOT, tmpdir

from collect import shelf
from collect.common import read_json, schema_errors
from collect.run import collect

META = read_json(FIX / "meta" / "before.json")
EXPECTED = ["ATTRIBUTION.md", "logs/requests.json", "manifest.json", "proposals/yamabiyori.json",
            "yamabiyori/explore.json", "yamabiyori/mountains.json"]


def artifact(test, mode="ok"):
    out = tmpdir(test) / "art"
    with mock.patch.dict(os.environ, {"FAKE_YAMA": mode}):
        collect(agents=["yamabiyori"], out_dir=out, checkouts={"yamabiyori": FAKE_YAMA}, pythons={"yamabiyori": sys.executable},
                yama_limit=None, meta_fetch=lambda ph: META)
    return out


def publish(test, art, existing=None):
    base = tmpdir(test)
    ex = existing or (base / "empty")
    ex.mkdir(exist_ok=True)
    out = base / "pub"
    summary = shelf.prepare(art, ex, out)
    return out, summary, read_json(out / "manifest.json")


class FirstPublish(unittest.TestCase):
    def test_tree_from_recorded_input(self):
        out, s, m = publish(self, artifact(self))
        self.assertEqual(s["files"], EXPECTED)
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])
        y = m["agents"]["yamabiyori"]
        self.assertEqual((y["status"], y["kept_from"], y["version"]), ("ok", None, "1.9.0"))
        self.assertIsNone(y["limit"])
        self.assertEqual(y["files"], ["proposals/yamabiyori.json", "yamabiyori/explore.json", "yamabiyori/mountains.json"])
        self.assertEqual(m["model_runs"]["ecmwf_ifs025"]["init"], "2026-09-24T00:00:00Z")
        self.assertEqual(schema_errors(read_json(out / "proposals/yamabiyori.json"), "biyori-proposal"), [])
        self.assertEqual(read_json(out / "yamabiyori/mountains.json")["count"], 76)
        self.assertNotIn("raw", {p.parts[0] for p in out.iterdir()})

    def test_no_personal_settings_or_coordinates_in_manifest_and_logs(self):
        out, _, m = publish(self, artifact(self))
        text = (out / "manifest.json").read_text(encoding="utf-8") + (out / "logs/requests.json").read_text(encoding="utf-8")
        for word in ("origin", "横浜", "35.466", "139.622", "latitude", "longitude"):
            self.assertNotIn(word, text)

    def test_first_run_failure_publishes_a_failed_entry_without_files(self):
        out, s, m = publish(self, artifact(self, "exit2"))
        self.assertEqual(m["agents"]["yamabiyori"]["status"], "failed")
        self.assertEqual(m["agents"]["yamabiyori"]["files"], [])
        self.assertFalse((out / "proposals").exists())

    def test_same_inputs_same_tree(self):
        art = artifact(self)
        a, _, _ = publish(self, art)
        b, _, _ = publish(self, art)
        for rel in EXPECTED:
            self.assertEqual((a / rel).read_bytes(), (b / rel).read_bytes(), rel)

    def test_output_dir_must_be_empty(self):
        art = artifact(self)
        d = tmpdir(self)
        (d / "x").write_text("x")
        with self.assertRaises(ValueError):
            shelf.prepare(art, tmpdir(self), d)

    def test_broken_run_json_publishes_nothing(self):
        art = artifact(self)
        (art / "run.json").write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            publish(self, art)


class SwapOnlyOnSuccess(unittest.TestCase):
    def previous(self):
        out, _, m = publish(self, artifact(self))
        return out, m

    def test_failure_keeps_previous_files_and_says_why(self):
        prev, pm = self.previous()
        for mode, reason in (("exit2", "exit_2"), ("429", "rate_limited"), ("bad_schema", "unexpected_output")):
            with self.subTest(mode=mode):
                out, s, m = publish(self, artifact(self, mode), existing=prev)
                y = m["agents"]["yamabiyori"]
                self.assertEqual((y["status"], y["reason"]), ("kept_previous", reason))
                self.assertEqual(y["kept_from"], pm["finished_at"])
                self.assertEqual(y["data_time"], pm["agents"]["yamabiyori"]["data_time"])
                self.assertEqual((out / "proposals/yamabiyori.json").read_bytes(), (prev / "proposals/yamabiyori.json").read_bytes())
                self.assertEqual(s["files"], EXPECTED)
                self.assertEqual(schema_errors(m, "biyori-shelf"), [])

    def test_kept_twice_still_points_at_the_run_that_made_the_files(self):
        prev, pm = self.previous()
        once, _, m1 = publish(self, artifact(self, "exit2"), existing=prev)
        _, _, m2 = publish(self, artifact(self, "exit2"), existing=once)
        self.assertEqual(m2["agents"]["yamabiyori"]["kept_from"], pm["finished_at"])

    def test_success_replaces(self):
        prev, pm = self.previous()
        _, _, m = publish(self, artifact(self), existing=prev)
        self.assertEqual(m["agents"]["yamabiyori"]["status"], "ok")
        self.assertNotEqual(m["started_at"], None)

    def test_invalid_artifact_file_is_not_used(self):
        prev, _ = self.previous()
        art = artifact(self)
        p = read_json(art / "proposals/yamabiyori.json")
        p["schema"] = "biyori-proposal/9"
        (art / "proposals/yamabiyori.json").write_text(json.dumps(p), encoding="utf-8")
        _, _, m = publish(self, art, existing=prev)
        self.assertEqual((m["agents"]["yamabiyori"]["status"], m["agents"]["yamabiyori"]["reason"]), ("kept_previous", "artifact_invalid"))

    def test_broken_existing_shelf_is_not_kept(self):
        prev, _ = self.previous()
        (prev / "manifest.json").write_text("{}", encoding="utf-8")
        _, _, m = publish(self, artifact(self, "exit2"), existing=prev)
        self.assertEqual(m["agents"]["yamabiyori"]["status"], "failed")

    def test_missing_previous_file_is_not_kept(self):
        prev, _ = self.previous()
        (prev / "yamabiyori/mountains.json").unlink()
        _, _, m = publish(self, artifact(self, "exit2"), existing=prev)
        self.assertEqual(m["agents"]["yamabiyori"]["status"], "failed")

    def test_incomplete_is_published_as_incomplete_not_ok(self):
        # 暫定(利用者が決めるまで): 全座そろわない回も入れ替えるが、status は incomplete で、何座そろったかを示す
        prev, _ = self.previous()
        out, s, m = publish(self, artifact(self, "partial"), existing=prev)
        y = m["agents"]["yamabiyori"]
        self.assertEqual((y["status"], y["reason"], y["kept_from"]), ("incomplete", "partial_fetch", None))
        self.assertEqual(y["coverage"], {"pool_size": 3, "fetched": 2, "missing": 1, "total_mountains": 76})
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])
        self.assertEqual(s["files"], EXPECTED)
        self.assertEqual(read_json(out / "proposals/yamabiyori.json")["status"], "partial")

    def test_incomplete_shelf_can_be_kept_and_keeps_its_coverage(self):
        inc = publish(self, artifact(self, "partial"))[0]
        _, _, m = publish(self, artifact(self, "exit2"), existing=inc)
        y = m["agents"]["yamabiyori"]
        self.assertEqual(y["status"], "kept_previous")
        self.assertEqual(y["coverage"]["fetched"], 2)                  # 残したファイルの山の数
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])

    def test_ok_manifest_has_full_coverage(self):
        _, _, m = publish(self, artifact(self))
        self.assertEqual(m["agents"]["yamabiyori"]["coverage"]["missing"], 0)

    def test_incomplete_manifest_needs_coverage(self):
        _, _, m = publish(self, artifact(self, "partial"))
        m["agents"]["yamabiyori"].pop("coverage")
        self.assertTrue(schema_errors(m, "biyori-shelf"))

    def test_unexpected_files_in_the_artifact_are_not_published(self):
        art = artifact(self)
        (art / "config.local.yaml").write_text("origin: 自宅", encoding="utf-8")
        (art / "yamabiyori" / "extra.json").write_text("{}", encoding="utf-8")
        out, s, _ = publish(self, art)
        self.assertEqual(s["files"], EXPECTED)


class RequestLogSchema(unittest.TestCase):
    def test_extra_fields_such_as_coordinates_are_rejected(self):
        logs = read_json(artifact(self) / "logs/requests.json")
        self.assertEqual(schema_errors(logs, "biyori-request-log"), [])
        logs["agents"]["yamabiyori"]["latitude"] = 35.1
        self.assertTrue(schema_errors(logs, "biyori-request-log"))

    def test_error_kinds_are_in_the_log_and_the_summary(self):
        art = artifact(self)
        logs = read_json(art / "logs/requests.json")
        self.assertEqual(logs["total"]["by_error"], {})                     # 偽のヤマビヨリは失敗しない
        logs["metadata"].update(requests=4, by_status={"200": 3, "error": 1}, by_error={"URLError": 1})
        logs["total"]["by_error"] = {"URLError": 1}
        self.assertEqual(schema_errors(logs, "biyori-request-log"), [])
        (art / "logs/requests.json").write_text(json.dumps(logs), encoding="utf-8")
        text = shelf.render_summary(art)
        self.assertIn("- 失敗の種類(例外の名前): URLError 1 件", text)
        self.assertIn("- メタデータ(meta.json): 4 件、ステータス別 {'200': 3, 'error': 1}、失敗の種類 URLError 1 件", text)

    def test_summary_shows_how_many_mountains(self):
        text = shelf.render_summary(artifact(self, "partial"))
        self.assertIn("| yamabiyori | incomplete | partial_fetch 3座のうち2座(1座取得できず)(全76座の先頭3座) | 3座のうち2座(1座取得できず)(全76座の先頭3座) |", text)
        self.assertNotIn("| yamabiyori | ok |", text)


class Attribution(unittest.TestCase):
    def test_open_meteo_cc_by_is_on_the_shelf(self):
        out, _, _ = publish(self, artifact(self))
        t = (out / "ATTRIBUTION.md").read_text(encoding="utf-8")
        self.assertIn("Open-Meteo.com", t)
        self.assertIn("CC BY 4.0", t)
        self.assertIn("非商用", t)
        self.assertEqual(t, (ROOT / "collect" / "ATTRIBUTION.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
