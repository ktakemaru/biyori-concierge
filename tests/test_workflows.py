"""ワークフローの定義の検査(ファイルを読むだけ)。main への強制 push がない・書き込み権限は publish だけ・
定期実行は停止スイッチつき・cron は利用者の決定どおりでバックテストの収集と重ならない、など(指示書 5.1・段階 1)。"""
import re
import unittest

import yaml
from helpers import ROOT

from collect.common import config

WF = ROOT / ".github" / "workflows"


def load(name):
    d = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    d["on"] = d.get("on", d.get(True))                 # YAML 1.1 では on: が True になる
    return d


def code_lines(path):
    """コメントを除いた行(説明文の「main には push しない」などを数えない)。"""
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]


def runs(job):
    return "\n".join(s.get("run", "") for s in job.get("steps", []))


def cron_times(expr):
    """'分 時 * * *' の分・時の展開(*/n とカンマだけ対応)→ [(時, 分)]。"""
    mi, hr = expr.split()[:2]

    def expand(f, top):
        out = []
        for part in f.split(","):
            if part.startswith("*/"):
                out += list(range(0, top, int(part[2:])))
            elif part == "*":
                out += list(range(top))
            else:
                out.append(int(part))
        return out
    return [(h, m) for h in expand(hr, 24) for m in expand(mi, 60)]


class Collect(unittest.TestCase):
    def setUp(self):
        self.wf = load("collect.yml")
        self.jobs = self.wf["jobs"]

    def test_write_permission_only_in_publish(self):
        self.assertEqual(self.wf["permissions"], {"contents": "read"})
        self.assertEqual(set(self.jobs), {"collect", "publish"})
        self.assertEqual(self.jobs["collect"]["permissions"], {"contents": "read"})
        self.assertEqual(self.jobs["publish"]["permissions"], {"contents": "write"})
        for name, job in self.jobs.items():
            perms = job.get("permissions") or {}
            writes = [k for k, v in perms.items() if v == "write"]
            self.assertEqual(writes, ["contents"] if name == "publish" else [], name)

    def test_force_push_only_to_data_and_never_to_main(self):
        pushes = [ln.strip() for ln in code_lines(WF / "collect.yml") if re.search(r"\bgit\b.*\bpush\b", ln)]
        self.assertEqual(len(pushes), 1, pushes)
        self.assertTrue(pushes[0].endswith("push --force origin HEAD:refs/heads/data"), pushes[0])
        self.assertNotIn("push", runs(self.jobs["collect"]))
        for wf in WF.glob("*.yml"):
            t = "\n".join(code_lines(wf))
            self.assertIsNone(re.search(r"push[^\n]*(main|master)", t), wf.name)
            self.assertNotRegex(t, r"push\s+(-f|--force)[^\n]*\s(origin\s+)?(HEAD:)?(refs/heads/)?main\b")

    def test_publish_runs_no_collect_code(self):
        r = runs(self.jobs["publish"])
        self.assertNotIn("collect run", r)
        self.assertIn("-m collect prepare", r)
        self.assertNotIn("yamabiyori", "".join(str(s.get("with", {}).get("repository", "")) for s in self.jobs["publish"]["steps"]))

    def test_live_run_only_in_collect_and_after_the_confirmation(self):
        steps = self.jobs["collect"]["steps"]
        names = [s.get("name", s.get("uses", "")) for s in steps]
        self.assertEqual(names[0], "Check confirmation")
        self.assertIn('"$CONFIRM" != "yes-run-live"', steps[0]["run"])
        self.assertIn("-m collect run", runs(self.jobs["collect"]))
        self.assertIn('"$CONFIRM" != "yes-run-live"', self.jobs["publish"]["steps"][0]["run"])

    def test_schedule_is_behind_the_switch_and_matches_the_decision(self):
        self.assertEqual([c["cron"] for c in self.wf["on"]["schedule"]], config()["collect"]["schedule_utc"])
        self.assertEqual(config()["collect"]["schedule_utc"], ["27 19 * * *", "47 7 * * *"])
        jst = sorted(((h + 9) % 24, m) for c in config()["collect"]["schedule_utc"] for h, m in cron_times(c))
        self.assertEqual(jst, [(4, 27), (16, 47)])                                # 利用者の決定 D3
        self.assertIn("vars.BIYORI_COLLECT_SCHEDULE == 'on'", self.jobs["collect"]["if"])
        self.assertIn("needs.collect.result != 'skipped'", self.jobs["publish"]["if"])

    def test_does_not_overlap_the_backtest_collection(self):
        gap = config()["collect"]["backtest_min_gap_minutes"]
        bt = [h * 60 + m for h, m in cron_times(config()["collect"]["backtest_cron_utc"])]
        for c in config()["collect"]["schedule_utc"]:
            for h, m in cron_times(c):
                t = h * 60 + m
                nearest = min(min((t - b) % 1440, (b - t) % 1440) for b in bt)
                self.assertGreaterEqual(nearest, gap, c)

    def test_dispatch_inputs(self):
        inp = self.wf["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inp), {"confirm", "agents", "yama_limit", "publish"})
        self.assertEqual(inp["agents"]["options"], ["yamabiyori", "hoshibiyori", "both"])
        self.assertFalse(inp["publish"]["default"])

    def test_runner_python_timeout_concurrency(self):
        for job in self.jobs.values():
            self.assertEqual(job["runs-on"], "ubuntu-24.04")
        self.assertEqual(self.jobs["collect"]["timeout-minutes"], 90)
        self.assertEqual(self.wf["concurrency"]["cancel-in-progress"], False)
        pys = [s["with"]["python-version"] for j in self.jobs.values() for s in j["steps"] if "setup-python" in s.get("uses", "")]
        self.assertEqual(set(pys), {"3.13"})

    def test_yamabiyori_main_without_credentials_and_without_playwright(self):
        steps = self.jobs["collect"]["steps"]
        y = [s for s in steps if s.get("with", {}).get("repository") == "ktakemaru/yamabiyori"]
        self.assertEqual(len(y), 1)
        self.assertEqual(y[0]["with"]["ref"], "main")
        for j in self.jobs.values():
            for s in j["steps"]:
                if "actions/checkout" in s.get("uses", ""):
                    self.assertIs(s["with"]["persist-credentials"], False)
        self.assertNotIn("playwright", "\n".join(code_lines(WF / "collect.yml")).lower())
        self.assertIn("_venvs/yamabiyori/bin/python -m pip install -r _agents/yamabiyori/requirements.txt", runs(self.jobs["collect"]))


class Tests(unittest.TestCase):
    def test_tests_workflow_is_read_only_and_not_scheduled(self):
        wf = load("tests.yml")
        self.assertEqual(wf["permissions"], {"contents": "read"})
        self.assertNotIn("schedule", wf["on"])
        self.assertIn("python -X utf8 -m unittest discover -s tests", runs(wf["jobs"]["unittest"]))


if __name__ == "__main__":
    unittest.main()
