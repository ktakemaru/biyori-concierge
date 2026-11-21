"""棚の写し(置き場の shelf/)の取り込み(sync)と読み出し。

sync: リポジトリ(このコードが置かれた git の作業フォルダ)で `git fetch origin data` を実行し、`origin/data` のファイルを
`git show` で読んで一時フォルダにそろえ、検査に通ったときだけ置き場の shelf/ と入れ替える。作業フォルダのブランチは切り替えない・
ファイルを取り出さない。取り込みに失敗しても止めない(前回の写しを使う)。通信は git だけ(Open-Meteo には通信しない)。

検査に通らないファイルがあれば、そのビヨリのファイルを含めて今回の写しを全部使わず、前回の写しを残す(新しい manifest と
古い提案が混ざると「いつ時点か」の文が食い違うため。指示書 4.3 の読み方。報告書に書いた)。"""
import os
import shutil
import subprocess
from pathlib import Path

from collect.common import ROOT, schema_errors
from collect.shelf import AGENT_FILES, agent_files_problems

from .common import dump_json, iso, parse_iso, read_json, write_text

REF = "origin/data"
EXTRA_FILES = ("manifest.json", "ATTRIBUTION.md", "logs/requests.json")
GIT_TIMEOUT_S = 120      # git の 1 コマンドの時間の上限(秒)。仮置き


def shelf_dir(base):
    return Path(base) / "shelf"


def _git(repo, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=GIT_TIMEOUT_S, env=env, check=False)


def repo_dir():
    """取り込みに使う git の作業フォルダ。既定はこのコードのリポジトリ。BIYORI_CONCIERGE_REPO はテスト用。"""
    return Path(os.environ.get("BIYORI_CONCIERGE_REPO") or ROOT)


def _wanted(manifest):
    files = set(EXTRA_FILES)
    for a in (manifest.get("agents") or {}).values():
        files.update(a.get("files") or [])
    allowed = {f for fs in AGENT_FILES.values() for f in fs} | set(EXTRA_FILES)
    return sorted(f for f in files if f in allowed)


def sync(base, now, repo=None):
    """→ {ok, fetched, message, kept_previous}。終了コードは常に 0 で扱う(呼び出し側)。"""
    repo = Path(repo or repo_dir())
    base = Path(base)
    res = {"at": iso(now), "ok": False, "fetched": False, "kept_previous": shelf_dir(base).joinpath("manifest.json").is_file(),
           "message": ""}
    try:
        f = _git(repo, "fetch", "--quiet", "origin", "data")
        res["fetched"] = f.returncode == 0
        if f.returncode != 0:
            res["message"] = "棚を取り込めませんでした(git fetch origin data が失敗。オフラインかもしれません)。"
        m = _git(repo, "show", f"{REF}:manifest.json")
        if m.returncode != 0:
            res["message"] = (res["message"] + " " if res["message"] else "") + "手元に棚(origin/data)がありません。"
            return _finish(base, res)
        tmp = base / f"shelf.tmp-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        try:
            (tmp / "manifest.json").write_bytes(m.stdout)
            manifest = read_json(tmp / "manifest.json")
            if not isinstance(manifest, dict) or schema_errors(manifest, "biyori-shelf"):
                res["message"] += " 棚の目次(manifest)が検査に通りませんでした。"
                return _finish(base, res)
            for rel in _wanted(manifest):
                if rel == "manifest.json":
                    continue
                g = _git(repo, "show", f"{REF}:{rel}")
                if g.returncode != 0:
                    continue
                dst = tmp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(g.stdout)
            probs = []
            for agent, e in (manifest.get("agents") or {}).items():
                if agent in AGENT_FILES and e.get("files"):
                    probs += agent_files_problems(tmp, agent)
            if probs:
                res["message"] += " 棚のファイルが検査に通りませんでした: " + "; ".join(probs[:3])
                return _finish(base, res)
            dst = shelf_dir(base)
            old = base / f"shelf.old-{os.getpid()}"
            if dst.exists():
                dst.rename(old)
            tmp.rename(dst)
            shutil.rmtree(old, ignore_errors=True)
            res.update(ok=True, kept_previous=False)
            res["message"] = ("棚を取り込みました。" if res["fetched"] else res["message"] + " 手元にある前回の取り込み(origin/data)を写しました。").strip()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except (OSError, subprocess.SubprocessError) as e:
        res["message"] = f"棚を取り込めませんでした({type(e).__name__})。"
    return _finish(base, res)


def _finish(base, res):
    res["message"] = res["message"].strip()
    if not res["ok"]:
        res["message"] += " 前回の写しを使います。" if res["kept_previous"] else " 手元に写しがありません。"
    try:
        write_text(Path(base) / "sync.json", dump_json(res))
    except OSError:
        pass
    return res


def load(base):
    """置き場の写しを読んで検査する。→ {ok, problem, manifest, entry(yamabiyori), proposals, mountains, sync}。"""
    d = shelf_dir(base)
    out = {"ok": False, "problem": None, "manifest": None, "entry": None, "proposals": None, "mountains": None,
           "sync": read_json(Path(base) / "sync.json")}
    m = read_json(d / "manifest.json")
    if m is None:
        out["problem"] = "no_shelf" if not (d / "manifest.json").exists() else "broken_manifest"
        return out
    if not isinstance(m, dict) or schema_errors(m, "biyori-shelf"):
        out["problem"] = "broken_manifest"
        return out
    out["manifest"] = m
    e = (m.get("agents") or {}).get("yamabiyori")
    out["entry"] = e
    if not e or e.get("status") not in ("ok", "incomplete", "kept_previous") or not e.get("files"):
        out["problem"] = "no_yamabiyori"
        return out
    if agent_files_problems(d, "yamabiyori"):
        out["problem"] = "broken_files"
        return out
    out["proposals"] = read_json(d / "proposals" / "yamabiyori.json")
    out["mountains"] = read_json(d / "yamabiyori" / "mountains.json")
    out["ok"] = True
    return out


def age_hours(entry, now):
    t = parse_iso((entry or {}).get("data_time"))
    return None if t is None else round((now - t).total_seconds() / 3600, 1)
