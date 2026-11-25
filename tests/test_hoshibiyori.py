"""星の取得(collect/hoshibiyori.py・collect/run.py の run_hoshibiyori)を、偽のホシビヨリ(tests/fixtures/hoshibiyori。通信しない)で通す。
本物の子プロセスを計測フックつきで起動する。見本は実物の出力から地点を減らしたもの(tests/make_stars_fixture.py)。"""
import json
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

from helpers import FAKE_YAMA, FIX, tmpdir

from collect import hoshibiyori as H
from collect import shelf
from collect.common import JST, allow_hosts, config, read_json, schema_errors
from collect.run import collect

FAKE_HOSHI = FIX / "hoshibiyori"
META = read_json(FIX / "meta" / "before.json")
NOW = datetime(2026, 11, 25, 22, 34, 21, tzinfo=JST)      # 見本の夜(11/25 から 14 夜)と合う時刻
CFG = {"nights": 14, "max_requests": 870, "timeout_s": 60, "total_timeout_s": 120, "http_429_max_total": 5}
FILES = ("hoshibiyori/stars.json", "hoshibiyori/milkyway.json", "proposals/hoshibiyori.json")


def run(test, plan="", agents=("hoshibiyori",), req=None, cfg=None, log=None):
    d = tmpdir(test)
    out = d / "art"
    env = {"FAKE_HOSHI": plan, "FAKE_YAMA": "ok"}
    if req:
        env["FAKE_HOSHI_REQ"] = req
    if log:
        env["FAKE_HOSHI_LOG"] = str(log)
    conf = json.loads(json.dumps(config()))
    conf["collect"]["agents"]["hoshibiyori"].update(dict(CFG, **(cfg or {})))
    with mock.patch.dict(os.environ, env), mock.patch("collect.run.now_jst", return_value=NOW), mock.patch("collect.run.config", return_value=conf):
        r = collect(agents=list(agents), out_dir=out, checkouts={"yamabiyori": FAKE_YAMA, "hoshibiyori": FAKE_HOSHI},
                    pythons={"yamabiyori": sys.executable, "hoshibiyori": sys.executable}, meta_fetch=lambda ph: META,
                    hoshibiyori_data_dir=d / "hd")
    return r, out


class Success(unittest.TestCase):
    def test_both_modes_are_taken_in_order_with_one_data_dir(self):
        log = tmpdir(self) / "log.jsonl"
        r, out = run(self, req="4,0", log=log)
        h = r["agents"]["hoshibiyori"]
        self.assertEqual((h["status"], h["version"], h["requests"], h["limit"]), ("ok", "1.2.0", 4, None))
        for rel in FILES:
            self.assertTrue((out / rel).is_file(), rel)
        self.assertEqual(read_json(out / "hoshibiyori/stars.json"), read_json(FAKE_HOSHI / "stars.json"))      # そのまま
        self.assertEqual(schema_errors(read_json(out / "run.json"), "biyori-collect-run"), [])
        self.assertEqual(schema_errors(read_json(out / "logs/requests.json"), "biyori-request-log"), [])
        calls = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([c["target"] for c in calls], ["stars", "milkyway"])
        self.assertEqual(len({c["data_dir"] for c in calls}), 1)
        self.assertTrue(calls[0]["data_dir"])
        self.assertEqual(calls[0]["nights"].split(",")[0], "2026-11-25")
        self.assertEqual(len(calls[0]["nights"].split(",")), 14)
        self.assertEqual({(c["tz"], c["max_429"]) for c in calls}, {("Asia/Tokyo", "5")})
        self.assertEqual([c["req_max"] for c in calls], ["870", "866"])                      # 上限は 2 つの合計
        self.assertEqual([(m["mode"], m["requests"], m["api_calls"], m["total_cells"]) for m in h["modes"]],
                         [("stars", 4, 455, 456), ("milkyway", 0, 0, 2)])

    def test_yamabiyori_only_run_is_unchanged(self):
        both, _ = run(self, agents=("yamabiyori", "hoshibiyori"))
        only, out = run(self, agents=("yamabiyori",))
        self.assertEqual(list(only["agents"]), ["yamabiyori"])
        self.assertFalse((out / "hoshibiyori").exists())
        self.assertNotIn("modes", only["agents"]["yamabiyori"])
        drop = ("runtime_s", "attempts", "data_time")                      # 実行のたびに変わる時刻と秒
        self.assertEqual({k: v for k, v in only["agents"]["yamabiyori"].items() if k not in drop},
                         {k: v for k, v in both["agents"]["yamabiyori"].items() if k not in drop})

    def test_partial_fetch_is_marked_in_the_proposals(self):
        r, out = run(self, "stars=partial")
        self.assertEqual(r["agents"]["hoshibiyori"]["status"], "ok")
        p = read_json(out / "proposals/hoshibiyori.json")
        self.assertEqual((p["status"], p["status_reason"]), ("partial", "fetch_incomplete"))
        self.assertEqual(r["agents"]["hoshibiyori"]["modes"][0]["failed_cells"], 3)


class Failures(unittest.TestCase):
    def check(self, plan, status, reason, modes, **kw):
        r, out = run(self, plan, **kw)
        h = r["agents"]["hoshibiyori"]
        self.assertEqual((h["status"], h["reason"]), (status, reason), h)
        self.assertEqual([m["mode"] for m in h["modes"]], modes)
        for rel in FILES:
            self.assertFalse((out / rel).exists(), rel)             # 1 つでも失敗したら、ファイルを 1 つも置かない
        self.assertIsNone(h["data_time"])
        self.assertEqual(schema_errors(read_json(out / "run.json"), "biyori-collect-run"), [])
        return h

    def test_exit_2(self):
        h = self.check("stars=exit2", "failed", "exit_2", ["stars"])
        self.assertIn("stars", h["detail"])

    def test_only_the_second_mode_fails(self):
        h = self.check("milkyway=exit2", "failed", "exit_2", ["stars", "milkyway"])
        self.assertEqual([m["status"] for m in h["modes"]], ["ok", "failed"])

    def test_wrong_schema_string(self):
        self.assertIn("hoshibiyori-explore/2", self.check("stars=bad_schema", "failed", "unexpected_output", ["stars"])["detail"])

    def test_output_that_breaks_the_schema_of_the_checkout(self):
        self.assertIn("scanned_nights", self.check("milkyway=broken", "failed", "unexpected_output", ["stars", "milkyway"])["detail"])

    def test_other_nights_than_asked(self):
        self.assertIn("夜", self.check("stars=other_nights", "failed", "unexpected_output", ["stars"])["detail"])

    def test_no_output(self):
        self.check("stars=no_output", "failed", "no_output", ["stars"])

    def test_timeout(self):
        self.check("stars=sleep", "failed", "timeout", ["stars"], cfg={"timeout_s": 2})

    def test_undeclared_host_is_stopped_and_named(self):
        self.assertEqual(self.check("stars=net", "failed", "blocked_host", ["stars"])["detail"], "blocked.example.invalid")

    def test_no_checkout(self):
        out = tmpdir(self) / "a"
        r = collect(agents=["hoshibiyori"], out_dir=out, checkouts={}, pythons={}, meta_fetch=lambda ph: META)
        self.assertEqual((r["agents"]["hoshibiyori"]["status"], r["agents"]["hoshibiyori"]["reason"]), ("failed", "no_checkout"))

    def test_schema_of_the_checkout_is_unreadable(self):
        with self.assertRaises(ValueError):
            H.load_schema(FAKE_YAMA)


class RateLimit(unittest.TestCase):
    def test_429_within_the_limit_and_all_fetched_is_ok(self):
        r, out = run(self, "stars=rl2ok")
        h = r["agents"]["hoshibiyori"]
        self.assertEqual((h["status"], h["http_429"], h["http_429_tolerated"], h["http_429_kinds"]), ("ok", 2, 2, {"minutely": 2}))
        self.assertIn("429: hoshibiyori 2 回(1 分の上限。待って取り直し、最後まで取れた)", shelf.render_summary(out))

    def test_429_over_the_limit_stops_the_agent(self):
        r, _ = run(self, "stars=rl6ok")
        h = r["agents"]["hoshibiyori"]
        self.assertEqual((h["status"], h["http_429"], len(h["modes"])), ("rate_limited", 6, 1))

    def test_429_with_missing_cells_is_rate_limited(self):
        r, _ = run(self, "milkyway=rl1partial")
        self.assertEqual(r["agents"]["hoshibiyori"]["status"], "rate_limited")

    def test_without_the_setting_the_first_429_stops(self):
        r, _ = run(self, "stars=rl1ok", cfg={"http_429_max_total": 0})
        self.assertEqual(r["agents"]["hoshibiyori"]["status"], "rate_limited")


class Convert(unittest.TestCase):
    def natives(self):
        return {m: read_json(FAKE_HOSHI / f"{m}.json") for m in H.MODES}

    def convert(self, natives):
        return H.convert(natives, now=NOW, fetched_at=NOW, agent_version="1.2.0", agent_commit="0" * 40)

    def test_schema_ids_windows_and_no_invented_values(self):
        p = self.convert(self.natives())
        self.assertEqual(schema_errors(p, "biyori-proposal"), [])
        self.assertEqual(p, self.convert(self.natives()))                       # 決定論
        self.assertEqual(len({x["id"] for x in p["proposals"]}), len(p["proposals"]))
        x = next(x for x in p["proposals"] if x["place"]["name"] == "丹沢湖(山北町)" and x["details"]["night_date"] == "2026-11-28")
        self.assertEqual(x["place"]["site_ref"], "hoshibiyori:" + x["details"]["site_id"])
        self.assertIsNone(x["place"]["elevation_m"])
        self.assertIsNone(x["suitability"]["score"])                            # 星空・星座モードはスコアが無い
        self.assertEqual((x["time_window"]["kind"], x["suitability"]["band"], x["uncertainty"]["lead_days"]), ("clear_window", "maybe", 3))
        self.assertRegex(x["time_window"]["start"], r"\+09:00$")
        ranks = {e["metric"]: e["value"] for e in x["evidence"]}
        self.assertIsNone(ranks["rank"])                                        # 候補の夜(上位の夜)でないので順位は無い
        y = next(x for x in p["proposals"] if x["details"]["night_date"] == "2026-12-06")
        self.assertIsInstance({e["metric"]: e["value"] for e in y["evidence"]}["rank"], int)

    def test_moon_nights_and_failed_sites_are_not_proposals(self):
        p = self.convert(self.natives())
        days = {x["details"]["night_date"] for x in p["proposals"]}
        self.assertFalse(days & {"2026-11-25", "2026-11-26"})                  # 月が一晩じゅう出ている夜(dark)
        self.assertNotIn("2026-12-04", days)                                    # 条件を通った地点が無い夜
        self.assertTrue(any("月の無い時間帯で調べていない夜" in w for w in p["diagnostics"]["warnings"]))

    def test_lift_site_has_a_constraint(self):
        p = self.convert(self.natives())
        lift = [x for x in p["proposals"] if x["place"]["name"].startswith("千畳敷")]
        self.assertTrue(lift)
        self.assertEqual({c["kind"] for x in lift for c in x["constraints"]}, {"access"})

    def test_site_without_an_id_is_never_a_proposal(self):
        r, out = run(self, "stars=null_id")
        self.assertEqual(r["agents"]["hoshibiyori"]["status"], "ok")
        p = read_json(out / "proposals/hoshibiyori.json")
        self.assertTrue(any("site_id の無い地点" in w for w in p["diagnostics"]["warnings"]))
        self.assertFalse([x for x in p["proposals"] if x["place"]["site_ref"] in ("hoshibiyori:None", "hoshibiyori:")])
        self.assertLess(len(p["proposals"]), len(self.convert(self.natives())["proposals"]))

    def test_score_keeps_its_own_scale(self):
        n = self.natives()
        n["milkyway"]["requested_nights"] = n["stars"]["requested_nights"]      # 作り物: 天の川の候補がある形(見本の季節には無い)
        n["milkyway"]["outlooks"] = [dict(x, score=81.5) for x in n["stars"]["outlooks"]]
        p = self.convert(n)
        sc = [x["suitability"]["score"] for x in p["proposals"] if x["details"]["mode"] == "milkyway" and x["suitability"]["score"]]
        self.assertTrue(sc)
        self.assertEqual({s["scale"] for s in sc}, {"hoshibiyori-outlook-score"})


class Publish(unittest.TestCase):
    def publish(self, art, existing=None):
        base = tmpdir(self)
        ex = existing or base / "empty"
        ex.mkdir(exist_ok=True)
        shelf.prepare(art, ex, base / "pub")
        return base / "pub", read_json(base / "pub" / "manifest.json")

    def test_both_agents_on_the_first_shelf(self):
        _, out = run(self, agents=("yamabiyori", "hoshibiyori"))
        pub, m = self.publish(out)
        self.assertEqual({a: e["status"] for a, e in m["agents"].items()}, {"yamabiyori": "ok", "hoshibiyori": "ok"})
        self.assertEqual(m["agents"]["hoshibiyori"]["files"], sorted(FILES))
        self.assertEqual([x["mode"] for x in m["agents"]["hoshibiyori"]["modes"]], ["stars", "milkyway"])
        self.assertNotIn("modes", m["agents"]["yamabiyori"])
        self.assertEqual(schema_errors(m, "biyori-shelf"), [])
        for rel in FILES:
            self.assertTrue((pub / rel).is_file(), rel)

    def test_failed_stars_keep_the_previous_two_files_together(self):
        pub, first = self.publish(run(self)[1])
        _, art = run(self, "milkyway=exit2")
        pub2, m = self.publish(art, pub)
        h = m["agents"]["hoshibiyori"]
        self.assertEqual((h["status"], h["reason"], h["kept_from"]), ("kept_previous", "exit_2", first["finished_at"]))
        self.assertEqual([x["status"] for x in h["modes"]], ["ok", "ok"])       # 残したファイルのモードの記録
        for rel in FILES:
            self.assertEqual((pub / rel).read_bytes(), (pub2 / rel).read_bytes())

    def test_stars_only_run_keeps_the_mountain_files(self):
        # 星だけの手動の取得: 山は前回のまま kept_previous(理由 not_requested)になる(今の動き。変えていない)
        pub, _ = self.publish(run(self, agents=("yamabiyori",))[1])
        pub2, m = self.publish(run(self)[1], pub)
        self.assertEqual((m["agents"]["yamabiyori"]["status"], m["agents"]["yamabiyori"]["reason"]), ("kept_previous", "not_requested"))
        self.assertEqual((pub / "yamabiyori/explore.json").read_bytes(), (pub2 / "yamabiyori/explore.json").read_bytes())

    def test_yamabiyori_only_run_keeps_the_star_files(self):
        pub, _ = self.publish(run(self)[1])
        _, m = self.publish(run(self, agents=("yamabiyori",))[1], pub)
        self.assertEqual((m["agents"]["hoshibiyori"]["status"], m["agents"]["yamabiyori"]["status"]), ("kept_previous", "ok"))

    def test_summary_has_the_modes(self):
        text = shelf.render_summary(run(self, req="3,0")[1])
        self.assertIn("| stars | ok | 3 | 456 | 0 |", text)
        self.assertIn("| milkyway | ok | 0 | 2 | 0 |", text)


class Settings(unittest.TestCase):
    def test_limits_fit_in_the_job(self):
        a = config()["collect"]["agents"]
        h = a["hoshibiyori"]
        self.assertEqual((h["nights"], h["max_requests"], h["timeout_s"], h["total_timeout_s"], h["http_429_max_total"]), (14, 870, 1500, 2300, 5))
        self.assertLess(a["yamabiyori"]["total_timeout_s"] + h["total_timeout_s"], 90 * 60)
        self.assertLessEqual(h["timeout_s"], h["total_timeout_s"])
        self.assertEqual(h["expected_schema"], H.SCHEMA_IN)

    def test_hosts(self):
        self.assertEqual(allow_hosts("hoshibiyori"), ["api.open-meteo.com", "ssd.jpl.nasa.gov"])

    def test_command_is_an_argument_list_without_reports(self):
        c = H.command("py", "chk", "stars", ["2026-11-25", "2026-11-26"], "o.json")
        self.assertEqual(c[1:3], ["-X", "utf8"])
        self.assertEqual(c[4:], ["--target", "stars", "--nights", "2026-11-25,2026-11-26", "--json-out", "o.json"])


class Workflow(unittest.TestCase):
    def setUp(self):
        import yaml
        from helpers import ROOT
        self.jobs = yaml.safe_load((ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8"))["jobs"]

    def test_hoshibiyori_is_main_in_its_own_venv_and_only_when_asked(self):
        steps = self.jobs["collect"]["steps"]
        h = [s for s in steps if s.get("with", {}).get("repository") == "ktakemaru/hoshibiyori"]
        self.assertEqual([(s["with"]["ref"], s["with"]["persist-credentials"]) for s in h], [("main", False)])
        run = chr(10).join(s.get("run", "") for s in steps)
        self.assertIn("_venvs/hoshibiyori/bin/python -m pip install -r _agents/hoshibiyori/requirements.txt", run)
        self.assertIn('--hoshibiyori-data-dir "$PWD/_hoshi_data"', run)
        mine = [s for s in steps if "hoshi" in str(s.get("with", {})) or "Install hoshibiyori" in s.get("name", "")]
        self.assertEqual(len(mine), 4)
        for s in mine:
            self.assertEqual(s["if"], "${{ env.AGENTS == 'hoshibiyori' || env.AGENTS == 'both' }}")

    def test_only_the_ephemeris_and_the_astro_results_are_carried_over(self):
        paths = [s["with"]["path"] for s in self.jobs["collect"]["steps"] if "actions/cache" in s.get("uses", "")]
        self.assertEqual(paths, ["_hoshi_data/step1_astronomy/de421.bsp", "_hoshi_data/step1_astronomy/astro_cache"])
        self.assertFalse([s for s in self.jobs["publish"]["steps"] if "actions/cache" in s.get("uses", "") or "hoshi" in str(s.get("with", {}))])


if __name__ == "__main__":
    unittest.main()
