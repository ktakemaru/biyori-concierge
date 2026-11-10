"""子プロセスとして動く: Open-Meteo のメタデータ(/data/<model>/static/meta.json)を読んで、そのまま JSON に保存する。
計測フックつきで起動される(collect/runner.py)。標準ライブラリだけ。再試行しない(4xx/5xx はフックが中止する)。
手本: yamabiyori-backtest backtest/collect_forecast_snapshot.py の fetch_metadata(参照のみ。コードは写していない)。

  python -X utf8 collect/meta_fetch.py --out <file> --models jma_msm,ecmwf_ifs025
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone

META_URL = "https://api.open-meteo.com/data/{model}/static/meta.json"
KEEP = ("last_run_initialisation_time", "last_run_availability_time", "last_run_modification_time",
        "update_interval_seconds", "temporal_resolution_seconds", "data_end_time")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--models", required=True)
    a = ap.parse_args(argv)
    out = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "models": {}}
    for model in [m for m in a.models.split(",") if m]:
        try:
            with urllib.request.urlopen(META_URL.format(model=model), timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
            out["models"][model] = {k: d.get(k) for k in KEEP}
        except (OSError, ValueError) as e:
            out["models"][model] = {"error": type(e).__name__}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
