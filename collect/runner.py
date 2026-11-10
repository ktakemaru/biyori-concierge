"""子プロセスを計測フックつきで起動し、通信の記録を読む(指示書 5.2)。

- 起動はシェルを介さず引数の配列で、`-X utf8` を付ける(呼び出し側が argv に入れる。ここで検査する)。
- フック(collect/measure/sitecustomize.py)を PYTHONPATH で必ず付ける。許可ホスト・上限・記録先は環境変数で渡す。
- 記録先は絶対パス(フックは相対パスなら通信前に止まる)。
- 429 はフックが即中止する(終了コード 75)。ここでは再試行しない。"""
import math
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .common import EXIT_HOOK_ABORT, MEASURE_DIR, config, iso, now_jst

# 子プロセスに引き継がない環境変数(計測フックの設定は毎回ここで作り直す。親の値を漏らさない)
_DROP_PREFIXES = ("BIYORI_",)
_DROP_KEYS = {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "GITHUB_TOKEN"}
_TAIL = 4000


@dataclass
class ChildResult:
    returncode: int | None
    started_at: object
    finished_at: object
    runtime_s: float
    records: list = field(default_factory=list)
    abort: str | None = None
    blocked_host: str | None = None
    timed_out: bool = False
    stdout_tail: str = ""
    stderr_tail: str = ""

    @property
    def rate_limited(self):
        return any(r.get("status") == 429 for r in self.records)

    @property
    def hook_aborted(self):
        return self.abort is not None or self.returncode == EXIT_HOOK_ABORT


def hook_env(req_log, max_requests, allow, base=None, extra=None):
    """子プロセスの環境。親の BIYORI_*・PYTHONPATH は捨て、フックの設定をここで決める。
    allow が空なら 'none'(フックは全拒否)。TZ は Asia/Tokyo(ヤマビヨリは date.today() で対象の日を決めるため。
    Actions のマシンは UTC なので、付けないと朝 4:27 の実行で日付が 1 日ずれる)。"""
    req_log = Path(req_log)
    if not req_log.is_absolute():
        raise ValueError(f"記録先は絶対パスにする: {req_log}")
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if k not in _DROP_KEYS and not k.startswith(_DROP_PREFIXES)}
    env.update({
        "PYTHONPATH": str(MEASURE_DIR),
        "BIYORI_REQ_LOG": str(req_log),
        "BIYORI_REQ_MAX": str(int(max_requests)),
        "BIYORI_ALLOW_HOSTS": ",".join(allow) if allow else "none",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "TZ": "Asia/Tokyo",
    })
    env.update(extra or {})
    return env


def check_argv(argv):
    if not isinstance(argv, (list, tuple)) or not all(isinstance(a, str) for a in argv):
        raise TypeError("argv は文字列の配列にする(シェルを介さない)")
    if list(argv[1:3]) != ["-X", "utf8"]:
        raise ValueError("子プロセスには -X utf8 を付ける(argv[1:3] == ['-X', 'utf8'])")


def read_request_log(path):
    """フックの JSONL → (通信の記録, 中止の記録 dict または None)。壊れた行は飛ばす。"""
    import json
    recs, abort = [], None
    p = Path(path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            if "abort" in r:
                abort = r
            else:
                recs.append(r)
    return recs, abort


def run_hooked(argv, *, cwd, req_log, max_requests, allow, timeout_s, extra_env=None, base_env=None):
    """計測フックつきで1回だけ起動する(再試行しない)。"""
    check_argv(argv)
    req_log = Path(req_log)
    req_log.parent.mkdir(parents=True, exist_ok=True)
    env = hook_env(req_log, max_requests, allow, base=base_env, extra=extra_env)
    started = now_jst()
    t0 = time.perf_counter()
    timed_out = False
    try:
        r = subprocess.run(list(argv), cwd=str(cwd), env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout_s, check=False, shell=False)
        rc, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        timed_out, rc = True, None
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
    runtime = round(time.perf_counter() - t0, 1)
    recs, ab = read_request_log(req_log)
    blocked = ab.get("host") if ab and "許可リスト外" in str(ab.get("abort")) else None
    return ChildResult(returncode=rc, started_at=started, finished_at=now_jst(), runtime_s=runtime,
                       records=recs, abort=ab["abort"] if ab else None, blocked_host=blocked, timed_out=timed_out,
                       stdout_tail=out[-_TAIL:], stderr_tail=err[-_TAIL:])


# ------------------------------------------------------------------ 集計(座標・本文は入れない)
def estimated_calls(rec, cfg=None):
    """1 リクエストの call の推定(公式の式は未確認。config.yaml の estimated_calls)。メタデータは 0。"""
    c = (cfg or config())["estimated_calls"]
    if "/static/meta.json" in (rec.get("path") or ""):
        return 0.0
    nvars = (rec.get("hourly_vars") or 0) + (rec.get("daily_vars") or 0)
    days = None
    if isinstance(rec.get("forecast_days"), (int, str)) or isinstance(rec.get("past_days"), (int, str)):
        try:
            days = int(rec.get("forecast_days") or 0) + int(rec.get("past_days") or 0)
        except (TypeError, ValueError):
            days = None
    v = max(1.0, nvars / c["variables_per_call"])
    d = max(1.0, days / c["days_per_call"]) if days else 1.0
    return v * d


def summarize(records, abort=None):
    by_host, by_status, by_error = {}, {}, {}
    calls = 0.0
    for r in records:
        h = r.get("host") or "unknown"
        by_host[h] = by_host.get(h, 0) + 1
        s = "error" if r.get("status") is None else str(r["status"])
        by_status[s] = by_status.get(s, 0) + 1
        if r.get("status") is None:             # 失敗の種類(フックが記録した例外の名前。記録がなければ unknown)
            e = str(r.get("error") or "unknown")[:60]
            by_error[e] = by_error.get(e, 0) + 1
        calls += estimated_calls(r)
    return {"requests": len(records), "by_host": dict(sorted(by_host.items())),
            "by_status": dict(sorted(by_status.items())),
            "by_error": dict(sorted(by_error.items())),
            "estimated_calls": math.ceil(calls) if records else 0,
            "aborted": abort}


def child_summary(res: ChildResult):
    s = summarize(res.records, res.abort)
    s.update(started_at=iso(res.started_at), finished_at=iso(res.finished_at), runtime_s=res.runtime_s,
             returncode=res.returncode, timed_out=res.timed_out, rate_limited=res.rate_limited,
             blocked_host=res.blocked_host)
    return s
