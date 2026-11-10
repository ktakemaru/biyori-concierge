"""予報の回(model_runs)を、取得の前後のメタデータから決める(通信なし。通信は collect/meta_fetch.py の子プロセス)。"""
import sys
from pathlib import Path

from .common import COLLECT, config, epoch_to_utc_iso, read_json
from .runner import run_hooked
from .common import allow_hosts

META_SCRIPT = COLLECT / "meta_fetch.py"


def fetch_meta(python, out_file, req_log, models=None, timeout_s=120):
    """計測フックつきの子プロセスで meta.json を読む。→ (読んだ dict または None, ChildResult)"""
    models = models or config()["collect"]["model_runs"]
    argv = [str(python), "-X", "utf8", str(META_SCRIPT), "--out", str(out_file), "--models", ",".join(models)]
    res = run_hooked(argv, cwd=Path(out_file).parent, req_log=req_log,
                     max_requests=config()["collect"]["meta_max_requests"], allow=allow_hosts("meta"),
                     timeout_s=timeout_s)
    doc = read_json(out_file) if res.returncode == 0 else None
    return doc, res


def _one(m):
    if not isinstance(m, dict) or m.get("error"):
        return None, None
    return (epoch_to_utc_iso(m.get("last_run_initialisation_time")),
            epoch_to_utc_iso(m.get("last_run_availability_time")))


def model_runs(before, after, models=None):
    """取得の前と後のメタデータ → {model: {init, available, same_before_after}}。
    分からない値は None(推測しない)。前後どちらかが読めなければ same_before_after は None。
    回は「後」の値を採る(前後で同じなら同じ。違えば same_before_after=false で、どちらの回か確定しない)。"""
    models = models or config()["collect"]["model_runs"]
    out = {}
    for m in models:
        b_init, b_av = _one(((before or {}).get("models") or {}).get(m))
        a_init, a_av = _one(((after or {}).get("models") or {}).get(m))
        same = None if (b_init is None or a_init is None) else (b_init == a_init)
        out[m] = {"init": a_init if a_init is not None else b_init,
                  "available": a_av if a_init is not None else b_av,
                  "same_before_after": same,
                  "init_before": b_init}
    return out


def python_for_meta():
    return sys.executable
