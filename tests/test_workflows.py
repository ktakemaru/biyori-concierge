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


def eval_expr(expr, ctx, funcs=None):
    """GitHub Actions の式の小さな評価(このファイルの式だけ。&&・||・==・!=・括弧・文字列・true/false・always())。
    && と || は Python の and・or と同じく値を返す。== は大文字・小文字を区別しない(GitHub の決まり)。未設定の変数は空文字。"""
    body = expr.strip()
    if body.startswith("${{"):
        body = body[3:-2].strip()
    toks = re.findall(r"'[^']*'|&&|\|\||==|!=|\(|\)|[A-Za-z_][\w.]*\(\)|[A-Za-z_][\w.]*", body)
    funcs = funcs or {}
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def atom():
        t = take()
        if t == "(":
            v = orx()
            assert take() == ")"
            return v
        if t.startswith("'"):
            return t[1:-1]
        if t in ("true", "false"):
            return t == "true"
        if t.endswith("()"):
            return funcs[t]
        v = ctx.get(t)
        return "" if v is None else v

    def cmp():
        a = atom()
        while peek() in ("==", "!="):
            op, b = take(), atom()
            eq = (a.lower() == b.lower()) if isinstance(a, str) and isinstance(b, str) else (a == b)
            a = eq if op == "==" else not eq
        return a

    def andx():
        a = cmp()
        while peek() == "&&":
            take()
            b = cmp()
            a = a and b
        return a

    def orx():
        a = andx()
        while peek() == "||":
            take()
            b = andx()
            a = a or b
        return a

    v = orx()
    assert pos[0] == len(toks), toks[pos[0]:]
    return v


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
        self.assertEqual(set(inp), {"confirm", "agents", "yama_limit", "yamabiyori_ref", "publish"})
        self.assertEqual(inp["agents"]["options"], ["yamabiyori", "hoshibiyori", "both"])
        self.assertIs(inp["publish"]["default"], True)      # 利用者の決定(2026-11-25)。うっかり起動は confirm で防ぐ
        self.assertNotIn("default", inp["confirm"])
        self.assertTrue(inp["confirm"]["required"])

    def test_yama_limit_default_all_for_every_mountain(self):
        # 欄を空にしても 3 座で動いたため、全座は all と入れる方式。初期値は 3 → all(利用者の決定 2026-11-25)。定期実行は all
        y = self.wf["on"]["workflow_dispatch"]["inputs"]["yama_limit"]
        self.assertEqual((y["type"], y["default"]), ("string", "all"))
        self.assertIn("all", y["description"])
        self.assertNotIn("空 = 全", y["description"])
        env = self.jobs["collect"]["env"]["YAMA_LIMIT"]
        self.assertEqual(env, "${{ github.event_name == 'schedule' && 'all' || inputs.yama_limit }}")
        self.assertIn('--yama-limit "$YAMA_LIMIT"', runs(self.jobs["collect"]))

    def test_yamabiyori_ref_main_by_default_and_always_main_on_schedule(self):
        y = self.wf["on"]["workflow_dispatch"]["inputs"]["yamabiyori_ref"]
        self.assertEqual((y["type"], y["default"]), ("string", "main"))
        env = self.jobs["collect"]["env"]["YAMABIYORI_REF"]
        self.assertEqual(env, "${{ github.event_name == 'schedule' && 'main' || inputs.yamabiyori_ref }}")
        r = runs(self.jobs["collect"])
        self.assertIn('--yamabiyori-ref="$YAMABIYORI_REF"', r.split("-m collect run")[1])

    def test_inputs_are_checked_before_yamabiyori_is_fetched(self):
        steps = self.jobs["collect"]["steps"]
        names = [s.get("name", s.get("uses", "")) for s in steps]
        check = names.index("Check inputs (no network)")
        get = next(i for i, s in enumerate(steps) if s.get("with", {}).get("repository") == "ktakemaru/yamabiyori")
        self.assertLess(check, get)
        self.assertIn('-m collect check-inputs --yama-limit "$YAMA_LIMIT" --yamabiyori-ref="$YAMABIYORI_REF"', steps[check]["run"])

    def test_publish_skipped_when_yamabiyori_ref_is_not_main(self):
        cond = self.jobs["publish"]["if"]
        self.assertIn("inputs.publish == true && (inputs.yamabiyori_ref == 'main' || inputs.agents == 'hoshibiyori')", cond)
        self.assertIn("github.event_name == 'schedule' ||", cond)        # 定期実行は常に main

    def test_publish_skipped_when_yama_limit_is_not_all(self):
        # 一部の山だけを取った手動実行は、publish にチェックがあっても棚を置き換えない(利用者の決定 2026-11-25)。定期実行は変えない
        cond = self.jobs["publish"]["if"]
        base = {"github.event_name": "workflow_dispatch", "needs.collect.result": "success", "inputs.publish": True,
                "inputs.yamabiyori_ref": "main", "inputs.agents": "yamabiyori", "inputs.yama_limit": "all"}
        cases = [({}, True), ({"inputs.yama_limit": "3"}, False), ({"inputs.yama_limit": "76"}, False), ({"inputs.yama_limit": ""}, False),
                 ({"inputs.yama_limit": "3", "inputs.agents": "both"}, False), ({"inputs.yama_limit": "3", "inputs.agents": "hoshibiyori"}, True),
                 ({"inputs.yama_limit": "3", "inputs.publish": False}, False), ({"inputs.publish": False}, False),
                 ({"inputs.yamabiyori_ref": "feature/x"}, False), ({"needs.collect.result": "skipped"}, False),
                 ({"github.event_name": "schedule", "inputs.publish": None, "inputs.yama_limit": None, "inputs.yamabiyori_ref": None, "inputs.agents": None}, True)]
        for change, want in cases:
            with self.subTest(**change):
                self.assertEqual(bool(eval_expr(cond, {**base, **change}, funcs={"always()": True})), want)

    def test_input_descriptions_tell_the_guard(self):
        inp = self.wf["on"]["workflow_dispatch"]["inputs"]
        self.assertIn("棚は置き換わらない", inp["yama_limit"]["description"])
        self.assertNotIn("チェックも外す", inp["yama_limit"]["description"])
        self.assertIn("all の回だけ", inp["publish"]["description"])

    def test_scheduled_agents_come_from_the_variable(self):
        # 段階 2 の終わり(指示書 5.1。2026-11-22): 定期実行で取るビヨリは変数 BIYORI_COLLECT_AGENTS。未設定・それ以外は yamabiyori
        env = self.jobs["collect"]["env"]["AGENTS"]
        self.assertEqual(env, "${{ github.event_name == 'schedule' && ((vars.BIYORI_COLLECT_AGENTS == 'both' && 'both') || "
                              "(vars.BIYORI_COLLECT_AGENTS == 'hoshibiyori' && 'hoshibiyori') || 'yamabiyori') || inputs.agents }}")
        cases = [("schedule", None, "both", "yamabiyori"), ("schedule", "", "both", "yamabiyori"),
                 ("schedule", "yamabiyori", "both", "yamabiyori"), ("schedule", "hoshibiyori", "both", "hoshibiyori"),
                 ("schedule", "both", "yamabiyori", "both"), ("schedule", "Both", "yamabiyori", "both"),
                 ("schedule", "all", "both", "yamabiyori"), ("schedule", "yamabiyori,hoshibiyori", "both", "yamabiyori"),
                 ("workflow_dispatch", "both", "yamabiyori", "yamabiyori"), ("workflow_dispatch", None, "hoshibiyori", "hoshibiyori")]
        for event, var, inp, want in cases:
            with self.subTest(event=event, var=var):
                self.assertEqual(eval_expr(env, {"github.event_name": event, "vars.BIYORI_COLLECT_AGENTS": var, "inputs.agents": inp}), want)

    def test_schedule_switch_and_publish_are_unchanged_by_the_agents_variable(self):
        self.assertEqual(self.jobs["collect"]["if"],
                         "${{ github.event_name == 'workflow_dispatch' || (github.event_name == 'schedule' && vars.BIYORI_COLLECT_SCHEDULE == 'on') }}")
        cond = self.jobs["publish"]["if"]
        self.assertNotIn("BIYORI_COLLECT_AGENTS", cond)
        for agents_var in (None, "yamabiyori", "both"):
            with self.subTest(agents_var):
                ctx = {"github.event_name": "schedule", "needs.collect.result": "success", "vars.BIYORI_COLLECT_AGENTS": agents_var,
                       "inputs.publish": None, "inputs.yamabiyori_ref": None, "inputs.agents": None}
                self.assertTrue(eval_expr(cond, ctx, funcs={"always()": True}))
        off = {"github.event_name": "schedule", "vars.BIYORI_COLLECT_SCHEDULE": "", "vars.BIYORI_COLLECT_AGENTS": "both"}
        self.assertFalse(eval_expr(self.jobs["collect"]["if"], off))

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
        self.assertEqual(y[0]["with"]["ref"], "${{ env.YAMABIYORI_REF }}")       # 定期実行は main(下の test_yamabiyori_ref_…)
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
