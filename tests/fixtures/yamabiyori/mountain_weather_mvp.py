"""テスト用の偽のヤマビヨリ(本物ではない)。通信しない。記録済みの explore.json(ヤマビヨリ tests/fixtures/report/explore.json の写し)を
--json-out に書くだけ。FAKE_YAMA で失敗の形を真似る:
  ok(既定) / exit2 / bad_schema / no_output / net(通信を試みる → 計測フックが許可外で止める) / 429(フックの 429 の記録を真似て 75 で終わる)
  tz(TZ 環境変数を出力の generated に入れる。子プロセスの環境の確認用)
  partial(3 座のうち最後の 1 座を取れなかった形。fetched=2 で、その山の行を落とす) / no_counts(pool_size・fetched がない)
取り直しのテスト: FAKE_YAMA_PLAN="partial:9,ok:3" と FAKE_YAMA_STATE=<ファイル> で、呼ばれた回ごとに形を変え、
  その回の通信の記録(status 200)を指定の件数だけ BIYORI_REQ_LOG に書く(実際には通信しない)。
429 を通す設定のテスト(2026-11-22): rl<k>ok / rl<k>partial(429 を k 回受けてから ok / partial の出力。
  BIYORI_HTTP_429_MAX_TOTAL を超えた 429 では、フックと同じく中止の記録を書いて 75 で終わる)。
  FAKE_YAMA_429_BODY="本文|本文|…" があれば、i 回目の 429 の記録に計測フックと同じ body_head を付ける(2026-11-23)。"""
import argparse
import json
import os
import re
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
if os.environ.get("FAKE_YAMA_PLAN"):
    state = Path(os.environ["FAKE_YAMA_STATE"])
    k = int(state.read_text()) if state.is_file() else 0
    state.write_text(str(k + 1))
    plan = os.environ["FAKE_YAMA_PLAN"].split(",")
    mode, nrec = plan[min(k, len(plan) - 1)].split(":")
    with open(os.environ["BIYORI_REQ_LOG"], "a", encoding="utf-8") as f:
        for i in range(int(nrec)):
            f.write(json.dumps({"n": i + 1, "host": "api.open-meteo.com", "path": "/v1/forecast", "status": 200,
                                "hourly_vars": 49, "daily_vars": 0, "forecast_days": 15}) + "\n")
rl = re.fullmatch(r"rl(\d+)(ok|partial)", mode)
if rl:
    # 429 を k 回受けたあと、ok か partial の出力を書く(1 分の上限で待って取り直した形)。計測フックと同じ数え方で、
    # BIYORI_HTTP_429_MAX_TOTAL(無ければ 0)回までは通した印 rate_limit_tolerated を付け、超えたら中止の記録を書いて 75 で終わる。
    limit = int(os.environ.get("BIYORI_HTTP_429_MAX_TOTAL") or 0)
    with open(os.environ["BIYORI_REQ_LOG"], "a", encoding="utf-8") as f:
        for i in range(int(rl.group(1))):
            rec = {"n": 1000 + i, "host": "api.open-meteo.com", "path": "/v1/forecast", "status": 429, "hourly_vars": 49}
            bodies = os.environ.get("FAKE_YAMA_429_BODY")
            if bodies:
                bodies = bodies.split("|")
                rec["body_head"] = bodies[min(i, len(bodies) - 1)]
            if i < limit:
                f.write(json.dumps(dict(rec, rate_limit_tolerated=True)) + "\n")
                continue
            f.write(json.dumps(rec) + "\n")
            why = f"HTTP 429(429 を通す回数の上限 {limit} 回を超えた)" if limit else "HTTP 429"
            f.write(json.dumps({"abort": why, "count": 1000 + i}) + "\n")
            f.close()
            os._exit(75)
    mode = rl.group(2)
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
if mode == "partial":
    names = []
    for d in native["days"]:
        for r in d["all"]:
            if r["mountain"] not in names:
                names.append(r["mountain"])
    drop = names[-1]
    for d in native["days"]:
        d["all"] = [r for r in d["all"] if r["mountain"] != drop]
        d["rows"] = [r for r in d["rows"] if r["mountain"] != drop]
    native["fetched"] = native["pool_size"] - 1
if mode == "no_counts":
    native.pop("pool_size")
    native.pop("fetched")
if mode != "no_output":
    Path(a.json_out).write_text(json.dumps(native, ensure_ascii=False), encoding="utf-8")
sys.exit(0)
