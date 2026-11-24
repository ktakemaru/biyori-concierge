"""答える側の土台: 日付の規則・置き場・sync・status・コマンドの形・通信しないこと・リポジトリに書かないこと。
sync のテストは、一時フォルダに作った git のリポジトリ(data ブランチつき)を相手にする(実通信なし)。"""
import ast
import os
import shutil
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from concierge_helpers import NOW, QUESTION, SHELF_FIX, base_with_shelf
from helpers import ROOT, tmpdir

from concierge import dates as D
from concierge import shelf as S
from concierge import status as ST
from concierge.common import data_dir, parse_now


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                        "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false", *args],
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout


def make_repos(test, shelf_src=SHELF_FIX, break_manifest=False):
    """→ 作業フォルダ(origin に data ブランチがある)。"""
    t = tmpdir(test, "biyori-git-")
    remote, work = t / "remote.git", t / "work"
    git(t, "init", "--bare", str(remote))
    git(t, "init", str(work))
    (work / "README.md").write_text("main\n", encoding="utf-8")
    git(work, "add", "README.md")
    git(work, "commit", "-q", "-m", "main")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-q", "origin", "main")
    git(work, "switch", "-q", "--orphan", "data")
    for p in shelf_src.rglob("*"):
        if p.is_file():
            dst = work / p.relative_to(shelf_src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
    if break_manifest:
        (work / "manifest.json").write_text("{", encoding="utf-8")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "data")
    git(work, "push", "-q", "origin", "data")
    git(work, "switch", "-q", "main")
    git(work, "branch", "-q", "-D", "data")
    return work


class Dates(unittest.TestCase):
    def days(self, when, today):
        return [d["date"] for d in D.resolve(when, date.fromisoformat(today))["days"]]

    def test_weekend_rules(self):
        self.assertEqual(self.days("今週末", "2026-11-18"), ["2026-11-21", "2026-11-22"])      # 水曜
        self.assertEqual(self.days("今週末", "2026-11-21"), ["2026-11-21", "2026-11-22"])      # 土曜は今日と明日
        self.assertEqual(self.days("今週末", "2026-11-22"), ["2026-11-22"])                    # 日曜は今日だけ
        self.assertEqual(self.days("来週末", "2026-11-18"), ["2026-11-28", "2026-11-29"])
        self.assertEqual(self.days("来週末", "2026-11-21"), ["2026-11-28", "2026-11-29"])
        self.assertEqual(self.days("来週末", "2026-11-22"), ["2026-11-28", "2026-11-29"])
        self.assertEqual(self.days("明日", "2026-11-22"), ["2026-11-23"])
        self.assertEqual(self.days("2026-11-25", "2026-11-22"), ["2026-11-25"])
        self.assertEqual(self.days("2026-11-25..2026-11-27", "2026-11-22"), ["2026-11-25", "2026-11-26", "2026-11-27"])
        r = D.resolve("今週末", date(2026, 11, 18))
        self.assertEqual(r["days"][0]["label"], "11月21日(土)")
        self.assertEqual(r["time_range"]["start"], "2026-11-21T00:00:00+09:00")

    def test_bad_when(self):
        for w in ("そのうち", "2026-11-27..2026-11-25", "2026-01-01..2026-12-31"):
            with self.subTest(w), self.assertRaises(ValueError):
                D.resolve(w, date(2026, 11, 22))

    def test_now_is_japan_time(self):
        self.assertEqual(parse_now("2026-11-21T20:00:00Z").isoformat(), "2026-11-22T05:00:00+09:00")
        self.assertEqual(parse_now("2026-11-22T05:00:00").isoformat(), "2026-11-22T05:00:00+09:00")


class DataDir(unittest.TestCase):
    def test_env_and_default_and_never_inside_the_repo(self):
        t = tmpdir(self)
        self.assertEqual(data_dir({"BIYORI_CONCIERGE_DATA_DIR": str(t)}), t.resolve())
        self.assertEqual(data_dir({"LOCALAPPDATA": str(t)}) if sys.platform == "win32" else t.resolve(),
                         (t / "biyori-concierge").resolve() if sys.platform == "win32" else t.resolve())
        for inside in (ROOT, ROOT / "x"):
            with self.subTest(str(inside)), self.assertRaises(ValueError):
                data_dir({"BIYORI_CONCIERGE_DATA_DIR": str(inside)})


class Sync(unittest.TestCase):
    def test_copies_the_data_branch_without_switching_branches(self):
        work = make_repos(self)
        base = base_with_shelf(self, shelf=False)
        r = S.sync(base, parse_now(NOW), repo=work)
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["fetched"])
        for rel in ("manifest.json", "ATTRIBUTION.md", "proposals/yamabiyori.json", "yamabiyori/mountains.json", "yamabiyori/explore.json"):
            self.assertEqual((base / "shelf" / rel).read_bytes(), (SHELF_FIX / rel).read_bytes(), rel)
        self.assertEqual(git(work, "branch", "--show-current").strip(), "main")
        self.assertFalse((work / "manifest.json").exists())                 # 作業フォルダに取り出さない
        self.assertEqual(git(work, "status", "--porcelain"), "")
        self.assertTrue(S.load(base)["ok"])

    def test_broken_manifest_keeps_the_previous_copy(self):
        base = base_with_shelf(self)
        before = (base / "shelf" / "manifest.json").read_bytes()
        r = S.sync(base, parse_now(NOW), repo=make_repos(self, break_manifest=True))
        self.assertFalse(r["ok"])
        self.assertIn("前回の写しを使います", r["message"])
        self.assertEqual((base / "shelf" / "manifest.json").read_bytes(), before)

    def test_broken_proposals_keep_the_previous_copy(self):
        src = tmpdir(self) / "shelf"
        shutil.copytree(SHELF_FIX, src)
        (src / "proposals" / "yamabiyori.json").write_text("{}", encoding="utf-8")
        base = base_with_shelf(self)
        before = (base / "shelf" / "proposals" / "yamabiyori.json").read_bytes()
        r = S.sync(base, parse_now(NOW), repo=make_repos(self, shelf_src=src))
        self.assertFalse(r["ok"])
        self.assertEqual((base / "shelf" / "proposals" / "yamabiyori.json").read_bytes(), before)

    def test_offline_or_no_git_does_not_stop(self):
        base = base_with_shelf(self)
        t = tmpdir(self)
        git(t, "init", "-q", str(t / "w"))
        git(t / "w", "remote", "add", "origin", str(t / "nowhere.git"))
        r = S.sync(base, parse_now(NOW), repo=t / "w")
        self.assertFalse(r["ok"])
        self.assertIn("前回の写しを使います", r["message"])
        self.assertTrue(S.load(base)["ok"])
        with mock.patch("concierge.shelf._git", side_effect=FileNotFoundError("git")):
            r = S.sync(base, parse_now(NOW), repo=t / "w")
        self.assertFalse(r["ok"])
        self.assertTrue(S.load(base)["ok"])


class Status(unittest.TestCase):
    def test_status_of_the_fixture(self):
        text = ST.render(base_with_shelf(self), parse_now(NOW))
        self.assertIn("10月15日(木) 5:00 時点(朝の回。気象庁 MSM は 9月24日(木) 12時の回、ECMWF は 9月24日(木) 9時の回)", text)
        self.assertIn("3.0 時間前", text)
        self.assertIn("76 座のうち 3 座", text)
        self.assertIn("ヤマビヨリ 1.9.0", text)
        self.assertIn("星: まだありません(段階 3 から)", text)
        self.assertIn("18 時間以上前の古い予報", ST.render(base_with_shelf(self), parse_now("2026-10-16T08:00:00+09:00")))

    def test_status_without_or_with_broken_shelf(self):
        self.assertIn("手元に棚の写しがありません", ST.render(base_with_shelf(self, shelf=False), parse_now(NOW)))
        b = base_with_shelf(self, edit=lambda d: (d / "manifest.json").write_text("[]", encoding="utf-8"))
        self.assertIn("壊れているか、検査に通りません", ST.render(b, parse_now(NOW)))


class Commands(unittest.TestCase):
    """コマンドとして動かす(子プロセス)。置き場は一時フォルダ。リポジトリの中に何も書かないこと。"""

    def run_cli(self, *args, base):
        env = dict(os.environ, BIYORI_CONCIERGE_DATA_DIR=str(base), PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "concierge", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8", check=False)

    def repo_state(self):
        r = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all", "--ignored"],
                           capture_output=True, text=True, check=False)
        return r.stdout if r.returncode == 0 else None

    def test_brief_verify_status_and_no_writes_in_the_repo(self):
        from test_concierge_answer import good_draft
        from concierge import brief as B
        base = base_with_shelf(self)
        before = self.repo_state()
        r = self.run_cli("brief", "--question", QUESTION, "--now", NOW, base=base)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(len(out), 3)
        bid = out[0]
        self.assertTrue(Path(out[1]).is_file() and out[1].endswith(".json"))
        self.assertTrue(Path(out[2]).is_file() and out[2].endswith(".md"))
        doc = B.load(bid, base)
        draft = tmpdir(self) / "draft.txt"
        draft.write_text(good_draft(doc), encoding="utf-8")
        r = self.run_cli("verify", str(draft), "--brief", bid, "--now", NOW, base=base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("今週末なら、土曜の八ヶ岳(赤岳)がいちばんのおすすめです。"))
        draft.write_text(good_draft(doc).replace("5.4 m/s", "15 m/s"), encoding="utf-8")
        r = self.run_cli("verify", str(draft), "--brief", bid, base=base)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("number_mismatch", r.stderr)
        self.assertIn("直し方", r.stderr)
        self.assertEqual(self.run_cli("status", "--now", NOW, base=base).returncode, 0)
        self.assertEqual(self.run_cli("verify", str(draft), "--brief", "b-none", base=base).returncode, 2)
        self.assertEqual(self.run_cli("brief", "--question", "x", "--when", "そのうち", base=base).returncode, 2)
        if before is not None:
            self.assertEqual(self.repo_state(), before)

    def test_sync_exits_zero_even_offline(self):
        base = base_with_shelf(self)
        t = tmpdir(self)
        git(t, "init", "-q", str(t / "w"))
        env = dict(os.environ, BIYORI_CONCIERGE_DATA_DIR=str(base), BIYORI_CONCIERGE_REPO=str(t / "w"), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-X", "utf8", "-m", "concierge", "sync"], cwd=ROOT, env=env, capture_output=True,
                           text=True, encoding="utf-8", check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("前回の写しを使います", r.stdout)


class NoNetworkCode(unittest.TestCase):
    """答える側のコードが通信の部品を import しない(sync の git の起動は別)。テスト中はソケット禁止(helpers の nonet)。"""
    FORBIDDEN = {"requests", "urllib.request", "socket", "http.client", "httpx", "aiohttp", "urllib3",
                 "collect.runner", "collect.meta_fetch", "collect.run", "collect.diag_probe", "collect.diag"}

    def test_no_network_imports(self):
        files = sorted((ROOT / "concierge").rglob("*.py"))
        self.assertTrue(files)
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            names = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    names |= {a.name for a in n.names}
                elif isinstance(n, ast.ImportFrom):
                    mod = n.module or ""
                    names.add(mod)
                    names |= {f"{mod}.{a.name}" for a in n.names}
            with self.subTest(f.name):
                self.assertFalse(names & self.FORBIDDEN, names & self.FORBIDDEN)
                self.assertFalse({x for x in names if x.startswith(("urllib.request", "http."))})

    def test_imported_modules_after_running_do_not_include_network_parts(self):
        code = ("import sys; import concierge.__main__, concierge.brief, concierge.verify, concierge.shelf, concierge.status, "
                "concierge.fallback; bad=[m for m in ('requests','urllib.request','http.client','collect.runner','collect.meta_fetch',"
                "'collect.run') if m in sys.modules]; print(bad)")
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(r.stdout.strip(), "[]", r.stderr)


if __name__ == "__main__":
    unittest.main()
