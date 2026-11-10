"""子プロセスとして動く: Open-Meteo のメタデータ(/data/<model>/static/meta.json)を読んで、そのまま JSON に保存する。
計測フックつきで起動される(collect/runner.py)。標準ライブラリだけ。
読み取りに失敗したモデルだけ、RETRY_WAIT_S 秒あけて 1 回だけ読み直す(通信は計測フックの下のまま。回数もフックが数える)。
4xx/5xx(HTTPError)は読み直さない(フックが即中止する。フックの外で動かしたときも読み直さない)。
失敗の種類は例外の名前で残す(error)。URLError のように中の原因を持つ例外は、その名前も残す(error_reason)。
手本: yamabiyori-backtest backtest/collect_forecast_snapshot.py の fetch_metadata(参照のみ。コードは写していない)。

  python -X utf8 collect/meta_fetch.py --out <file> --models jma_msm,ecmwf_ifs025
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

META_URL = "https://api.open-meteo.com/data/{model}/static/meta.json"
KEEP = ("last_run_initialisation_time", "last_run_availability_time", "last_run_modification_time",
        "update_interval_seconds", "temporal_resolution_seconds", "data_end_time")
RETRY_WAIT_S = 5.0      # 読み直す前に待つ秒。仮置き(「数秒」。Open-Meteo の推奨値は未確認)


def failure(e):
    """例外 → 記録する失敗の種類(例外の名前だけ。本文・URL は入れない)。"""
    f = {"error": type(e).__name__}
    reason = getattr(e, "reason", None)
    if isinstance(reason, BaseException):
        f["error_reason"] = type(reason).__name__
    if isinstance(e, urllib.error.HTTPError):
        f["status"] = e.code
    return f


def fetch_one(model, opener=urllib.request.urlopen):
    try:
        with opener(META_URL.format(model=model), timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        return {k: d.get(k) for k in KEEP}
    except (OSError, ValueError) as e:
        return failure(e)


def fetch_all(models, opener=urllib.request.urlopen, sleep=time.sleep, wait_s=RETRY_WAIT_S):
    """→ {model: 値 または 失敗}。失敗したモデルだけ、wait_s 秒あけて 1 回だけ読み直す(4xx/5xx は読み直さない)。
    読み直したモデルには attempts=2 と、1 回目の失敗(first_error)を付ける。"""
    out = {m: fetch_one(m, opener) for m in models}
    again = [m for m, v in out.items() if "error" in v and "status" not in v]
    if again:
        sleep(wait_s)
        for m in again:
            first = out[m]
            v = fetch_one(m, opener)
            v.update(attempts=2, first_error=first["error"])
            if "error_reason" in first:
                v["first_error_reason"] = first["error_reason"]
            out[m] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--models", required=True)
    a = ap.parse_args(argv)
    out = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "models": fetch_all([m for m in a.models.split(",") if m])}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
