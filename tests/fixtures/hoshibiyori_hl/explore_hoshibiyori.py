"""テスト用の偽のホシビヨリ(本物ではない)。通信しない。実物の出力から地点を減らした stars.json・milkyway.json(作り方は
tests/make_stars_fixture.py)を --json-out に書くだけ。FAKE_HOSHI で失敗の形を真似る。

FAKE_HOSHI="stars=ok,milkyway=exit2" のようにモードごとに書く(書いていないモードは ok):
  ok / exit2(JSON を書かない) / bad_schema(schema の文字列が違う) / broken(スキーマの必須項目が無い) / no_output / sleep(時間切れ用)
  other_nights(頼まれた夜と違う) / partial(取得できなかったセルがある) / null_id(1 地点の site_id が null)
  net(通信を試みる → 計測フックが許可外で止める) / rl<k>ok・rl<k>partial(429 を k 回受けてから出力。フックと同じ数え方)
FAKE_HOSHI_REQ="3,0" は、星空・天の川の順の通信の記録(status 200)の件数。FAKE_HOSHI_LOG=<ファイル> に、渡された引数と HOSHIBIYORI_DATA_DIR を残す。"""
import argparse
import json
import os
import re
import socket
import sys
import time
from pathlib import Path


def _no_network(*a, **k):
    raise OSError("test: ソケットは禁止")


socket.socket.connect = _no_network
socket.create_connection = _no_network
socket.getaddrinfo = _no_network

ap = argparse.ArgumentParser()
ap.add_argument("--target", required=True)
ap.add_argument("--nights", required=True)
ap.add_argument("--json-out", required=True)
a = ap.parse_args()
here = Path(__file__).resolve().parent
plan = dict(x.split("=") for x in os.environ.get("FAKE_HOSHI", "").split(",") if x)
mode = plan.get(a.target, "ok")
if os.environ.get("FAKE_HOSHI_LOG"):
    with open(os.environ["FAKE_HOSHI_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"target": a.target, "nights": a.nights, "data_dir": os.environ.get("HOSHIBIYORI_DATA_DIR"),
                            "tz": os.environ.get("TZ"), "max_429": os.environ.get("BIYORI_HTTP_429_MAX_TOTAL"),
                            "req_max": os.environ.get("BIYORI_REQ_MAX")}) + "\n")
if os.environ.get("FAKE_HOSHI_REQ"):
    n = int(os.environ["FAKE_HOSHI_REQ"].split(",")[0 if a.target == "stars" else 1])
    with open(os.environ["BIYORI_REQ_LOG"], "a", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"n": i + 1, "host": "api.open-meteo.com", "path": "/v1/forecast", "status": 200, "hourly_vars": 33}) + "\n")
rl = re.fullmatch(r"rl(\d+)(ok|partial)", mode)
if rl:
    limit = int(os.environ.get("BIYORI_HTTP_429_MAX_TOTAL") or 0)
    with open(os.environ["BIYORI_REQ_LOG"], "a", encoding="utf-8") as f:
        for i in range(int(rl.group(1))):
            rec = {"n": 1000 + i, "host": "api.open-meteo.com", "path": "/v1/forecast", "status": 429, "hourly_vars": 33,
                   "body_head": "Minutely API request limit exceeded."}
            if i < limit:
                f.write(json.dumps(dict(rec, rate_limit_tolerated=True)) + "\n")
                continue
            f.write(json.dumps(rec) + "\n")
            f.write(json.dumps({"abort": f"HTTP 429(429 を通す回数の上限 {limit} 回を超えた)", "count": 1000 + i}) + "\n")
            f.close()
            os._exit(75)
    mode = rl.group(2)
if mode == "exit2":
    print("[中止] Open-Meteoが429(利用上限)を返したため")
    sys.exit(2)
if mode == "sleep":
    time.sleep(30)
if mode == "net":
    import urllib.request
    try:
        urllib.request.urlopen("https://blocked.example.invalid/x", timeout=1)
    except OSError:
        pass
    print("hook_did_not_stop")
    sys.exit(0)
native = json.loads((here / f"{a.target}.json").read_text(encoding="utf-8"))
if mode == "bad_schema":
    native["schema"] = "hoshibiyori-explore/2"
if mode == "broken":
    native.pop("scanned_nights")
if mode == "other_nights":
    native["requested_nights"] = native["requested_nights"][1:]
if mode == "partial":
    native["fetch"].update(status="partial", failed_cells=3)
if mode == "null_id":
    sid = native["requested_nights"][3]["sites"][0]["site_id"]
    for rec in native["site_index"] + [s for r in native["requested_nights"] for s in r["sites"]] + native["finals"] + native["outlooks"]:
        if rec["site_id"] == sid:
            rec["site_id"] = None
if mode != "no_output":
    Path(a.json_out).write_text(json.dumps(native, ensure_ascii=False), encoding="utf-8")
sys.exit(0)
