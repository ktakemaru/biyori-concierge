"""テスト用の偽のヤマビヨリ(本物ではない)。通信しない。記録済みの explore.json(ヤマビヨリ tests/fixtures/report/explore.json の写し)を
--json-out に書くだけ。FAKE_YAMA で失敗の形を真似る:
  ok(既定) / exit2 / bad_schema / no_output / net(通信を試みる → 計測フックが許可外で止める) / 429(フックの 429 の記録を真似て 75 で終わる)
  tz(TZ 環境変数を出力の generated に入れる。子プロセスの環境の確認用)"""
import argparse
import json
import os
import socket
import sys
from pathlib import Path


def _no_network(*a, **k):
    raise OSError("test: ソケットは禁止")


socket.socket.connect = _no_network
socket.create_connection = _no_network
socket.getaddrinfo = _no_network

ap = argparse.ArgumentParser()
ap.add_argument("--json-out")
ap.add_argument("--limit", type=int)
a = ap.parse_args()
mode = os.environ.get("FAKE_YAMA", "ok")
here = Path(__file__).resolve().parent
native = json.loads((here / "explore.json").read_text(encoding="utf-8"))
if mode == "exit2":
    print("すべての山で予報の取得に失敗しました。")
    sys.exit(2)
if mode == "net":
    import urllib.request
    try:
        urllib.request.urlopen("https://blocked.example.invalid/x", timeout=1)
    except OSError:
        pass
    print("hook_did_not_stop")
    sys.exit(0)
if mode == "429":
    log = os.environ["BIYORI_REQ_LOG"]
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"n": 1, "host": "api.open-meteo.com", "path": "/v1/forecast", "status": 429, "hourly_vars": 12}) + "\n")
        f.write(json.dumps({"abort": "HTTP 429", "count": 1}) + "\n")
    os._exit(75)
if mode == "bad_schema":
    native["schema"] = "yamabiyori-report-data/2"
if mode == "tz":
    native["generated"] = os.environ.get("TZ")
if mode != "no_output":
    Path(a.json_out).write_text(json.dumps(native, ensure_ascii=False), encoding="utf-8")
sys.exit(0)
