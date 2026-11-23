"""Stop フック(concierge/stop_hook.py・.claude/hooks/stop_check.py・.claude/settings.json)。通信しない。
会話の記録の見本は tests/fixtures/stop_hook/(作り物。形はイキモノビヨリのテストの見本にそろえた)。"""
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from concierge_helpers import NOW, base_with_shelf, build
from helpers import FIX, ROOT, tmpdir

from concierge import stop_hook as SH
from concierge import verify as V
from concierge.common import dump_json, parse_now, write_text

HOOK_FIX = FIX / "stop_hook"
BID = "b20261015-080000-0000aaaa"
ANSWER = "今週末なら、横岳がいちばんのおすすめです。\n\n気象データ: Weather data by Open-Meteo.com(CC BY 4.0)。\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tmpdir(self, "biyori-hook-")
        write_text(self.base / "last_answer.json", dump_json({"brief": BID, "at": NOW, "text": ANSWER}))
        self.env = {"BIYORI_CONCIERGE_DATA_DIR": str(self.base)}

    def transcript(self, name):
        text = (HOOK_FIX / f"{name}.jsonl").read_text(encoding="utf-8").replace("@ROOT@", ROOT.as_posix())
        text = text.replace("@TMP@", self.base.as_posix())                     # 下書きの場所(リポジトリの外の絶対パス。どの OS でも)
        p = tmpdir(self) / f"{name}.jsonl"
        p.write_text(text, encoding="utf-8", newline="\n")
        return p

    def payload(self, name, message=ANSWER, session="s1"):
        return {"session_id": session, "hook_event_name": "Stop", "stop_hook_active": False, "transcript_path": str(self.transcript(name)),
                "last_assistant_message": message}

    def run_hook(self, name, message=ANSWER, **kw):
        return SH.run(self.payload(name, message, **kw), env=self.env)

    def why(self, name, message=ANSWER):
        turn = SH.read_turn(self.transcript(name).read_text(encoding="utf-8").split("\n"))
        return SH.decide(message, turn, self.base)["why"]


class Decide(Base):
    def test_the_verified_text_passes(self):
        self.assertIsNone(self.run_hook("verified"))
        self.assertIsNone(self.run_hook("verified", "\n" + ANSWER.replace("\n", "\r\n") + "  \n"))      # 前後の空白・改行の形の違い

    def test_brief_without_verify_is_stopped(self):
        r = self.run_hook("no_verify", "横岳がおすすめです。")
        self.assertIn(SH.cfg()["reason_marker"], r)
        self.assertIn("concierge verify", r)
        self.assertEqual(self.why("no_verify"), "no_verify")
        self.assertEqual(self.why("powershell"), "no_verify")

    def test_text_added_before_or_after_is_stopped(self):
        for msg in ("照合に合格しました。\n" + ANSWER, ANSWER + "\nほかの日も調べました。", ANSWER.replace("横岳", "赤岳"), "横岳がおすすめです。"):
            with self.subTest(msg[:20]):
                self.assertEqual(self.why("verified", msg), "mismatch")

    def test_the_notice_between_the_commands_is_not_stopped(self):
        """長い作業の前の予告の 1 行(AGENTS.md 6 章)が合間にあっても止まらない。答えの前に付けて 1 つのメッセージにすると止まる。"""
        notice = "予報を確かめます。1 分ほどかかります。"
        self.assertIn(notice, (HOOK_FIX / "notice.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(self.why("notice"), "ok")
        self.assertIsNone(self.run_hook("notice"))
        self.assertEqual(self.why("notice", f"{notice}\n\n{ANSWER}"), "mismatch")

    def test_no_words_before_reading_the_files(self):
        """ファイルを読む前にも作業の説明を書かない決まりが、3 つの文書にある。最後のメッセージに入れば止まる。"""
        for name in ("AGENTS.md", "CLAUDE.md", ".claude/skills/biyori-concierge/SKILL.md"):
            with self.subTest(name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("ファイルを読む前・", text)
                self.assertIn("まず AGENTS.md を読みます", text)
        self.assertEqual(self.why("verified", "まず AGENTS.md を読みます。" + chr(10) + ANSWER), "mismatch")

    def test_the_notice_is_the_same_sentence_everywhere(self):
        for name in ("AGENTS.md", "CLAUDE.md", ".claude/skills/biyori-concierge/SKILL.md", "docs/stop-hook.md"):
            with self.subTest(name):
                self.assertIn("予報を確かめます。1 分ほどかかります。", (ROOT / name).read_text(encoding="utf-8"))

    def test_verify_before_the_last_brief_does_not_count(self):
        self.assertEqual(self.why("verify_before_brief"), "no_verify")

    def test_brief_and_verify_in_one_command(self):
        self.assertEqual(self.why("one_command"), "ok")

    def test_the_text_of_another_brief_is_not_accepted(self):
        write_text(self.base / "last_answer.json", dump_json({"brief": "b20260101-000000-ffffffff", "at": NOW, "text": ANSWER}))
        self.assertEqual(self.why("verified"), "mismatch")
        write_text(self.base / "briefs" / f"{BID}.final.txt", ANSWER)             # この回の資料の文なら通す
        self.assertEqual(self.why("verified"), "ok")

    def test_two_answers_in_one_message(self):
        write_text(self.base / "briefs" / f"{BID}.final.txt", "1 問目の答え。\n")
        self.assertEqual(self.why("verified", "1 問目の答え。\n\n" + ANSWER), "ok")
        self.assertEqual(self.why("verified", "1 問目の答え。\n\nここからは 2 問目です。\n" + ANSWER), "mismatch")


class NotChecked(Base):
    def test_no_brief_in_this_turn(self):
        for name in ("no_brief", "only_mentioned", "brief_failed", "notification", "slash_command"):
            with self.subTest(name):
                self.assertEqual(self.why(name, "何でもよい文"), "no_brief")
                self.assertIsNone(self.run_hook(name, "何でもよい文"))

    def test_development_is_not_stopped(self):
        for name, why in (("dev_words", "skip_word"), ("dev_commands", "dev_command"), ("dev_edit", "dev_edit")):
            with self.subTest(name):
                self.assertEqual(self.why(name, "報告です。"), why)
                self.assertIsNone(self.run_hook(name, "報告です。"))

    def test_drafts_outside_the_repo_are_not_development(self):
        self.assertEqual(self.why("verified", "違う文"), "mismatch")               # 見本は下書きを一時フォルダに書いている

    def test_switched_off(self):
        self.env["BIYORI_CONCIERGE_STOP_HOOK"] = "off"
        self.assertIsNone(self.run_hook("no_verify"))

    def test_unreadable_input_passes(self):
        self.assertIsNone(SH.run({}, env=self.env))
        self.assertIsNone(SH.run({"transcript_path": str(self.base / "none.jsonl"), "last_assistant_message": "x"}, env=self.env))
        p = self.base / "broken.jsonl"
        p.write_text("{\n[]\nnull\n", encoding="utf-8")
        self.assertIsNone(SH.run({"transcript_path": str(p), "last_assistant_message": "x"}, env=self.env))
        self.assertIsNone(self.run_hook("no_verify", ""))                          # 最後の文がない

    def test_errors_inside_pass(self):
        with mock.patch.object(SH, "decide", side_effect=RuntimeError("x")):
            out = io.StringIO()
            self.assertEqual(SH.main(io.StringIO(json.dumps(self.payload("no_verify"))), out), 0)
            self.assertEqual(out.getvalue(), "")
        out = io.StringIO()
        for raw in ("{", "[]", ""):
            self.assertEqual(SH.main(io.StringIO(raw), out), 0)
        self.assertEqual(out.getvalue(), "")


class Limit(Base):
    def test_the_third_time_passes_and_other_turns_are_counted_apart(self):
        got = [self.run_hook("no_verify", "x") is not None for _ in range(4)]
        self.assertEqual(got, [True, True, False, False])
        self.assertIsNotNone(self.run_hook("no_verify", "x", session="s2"))
        self.assertIsNotNone(self.run_hook("verify_before_brief", "x"))

    def test_broken_state_file(self):
        write_text(self.base / "logs" / "stop_hook_state.json", "[1")
        self.assertIsNotNone(self.run_hook("no_verify", "x"))


class Wiring(Base):
    def test_verify_leaves_the_last_text(self):
        from test_concierge_answer import good_draft
        base = base_with_shelf(self)
        doc = build(base)
        r = V.run(good_draft(doc).replace("稜線風速は5.4 m/s", "稜線風速は13 m/s"), doc["id"], base, parse_now(NOW))
        self.assertEqual(r["status"], "FAIL")
        self.assertFalse((base / "last_answer.json").exists())                     # 不合格では残さない
        r = V.run(good_draft(doc), doc["id"], base, parse_now(NOW))
        last = json.loads((base / "last_answer.json").read_text(encoding="utf-8"))
        self.assertEqual((last["brief"], last["text"]), (doc["id"], r["text"]))

    def test_settings_register_the_hook(self):
        s = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        cmd = s["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("$CLAUDE_PROJECT_DIR/.claude/hooks/stop_check.py", cmd)
        self.assertTrue((ROOT / ".claude" / "hooks" / "stop_check.py").is_file())

    def test_the_entry_as_a_child_process(self):
        env = dict(os.environ, **self.env, PYTHONDONTWRITEBYTECODE="1")
        env.pop("BIYORI_CONCIERGE_STOP_HOOK", None)

        def go(payload, **extra):
            return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / ".claude" / "hooks" / "stop_check.py")], cwd=self.base,
                                  input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), env=dict(env, **extra),
                                  capture_output=True, check=False)
        r = go(self.payload("no_verify", "横岳がおすすめです。"))
        self.assertEqual((r.returncode, r.stderr), (0, b""))
        out = json.loads(r.stdout.decode("utf-8"))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertIn("concierge verify", out["hookSpecificOutput"]["additionalContext"])
        for p, extra in ((self.payload("verified"), {}), (self.payload("no_verify", "x", session="s9"), {"BIYORI_CONCIERGE_STOP_HOOK": "off"})):
            r = go(p, **extra)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))

    def test_output_shapes(self):
        self.assertEqual(SH.to_output("r", {"output": "block"}), {"decision": "block", "reason": "r"})
        self.assertEqual(SH.to_output("r")["hookSpecificOutput"]["additionalContext"], "r")

    def test_mountain_questions_are_not_skipped(self):
        import re
        qa = (ROOT / "docs" / "qa.md").read_text(encoding="utf-8")
        qs = re.findall(r"(?m)^\| \d+ \| ([^|]+?) \| ", qa.split("## 問い", 1)[1].split("## hub", 1)[0])
        self.assertEqual(len(qs), 10)
        for q in qs:
            with self.subTest(q):
                self.assertIsNone(SH.exempt({"prompt": q, "calls": []}))


if __name__ == "__main__":
    unittest.main()
