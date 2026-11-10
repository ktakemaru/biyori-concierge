"""子プロセスとして動く: api.open-meteo.com の IP アドレスごとに、応答するかを調べる(診断。collect/diag.py が計測フックつきで起動する)。
標準ライブラリだけ。取得するのは meta.json(jma_msm)だけ。

- 名前解決で得た IP アドレス(IPv4・IPv6)それぞれに、新しい TCP・TLS の接続を張って meta.json を GET する。これを 1 回と数え、IP ごとに per_ip 回。
  順番は IP を順に回す(1 回目を全 IP、2 回目を全 IP…)。時刻による違いが特定の IP に偏らないようにするため。
- 回と回のあいだは interval_s 秒以上あける(始まりから次の始まりまで)。打ち切りは timeout_s 秒(TCP の接続・TLS・応答待ち・受信の各段階ごと)。
- 回数の上限: max_requests(計測フックも同じ上限で止める)。時間の上限: total_timeout_s(超えたら次の回を始めない)。
- 通信は urllib(OpenerDirector.open)を通すので、計測フックが数え・許可ホストを検査し・4xx/5xx(429 を含む)なら即中止する。
  接続先の IP だけを固定し、TLS の名前(SNI)と証明書の検査・Host は api.open-meteo.com のまま。
- 失敗した段階を記録する: tcp(TCP の接続)/ tls(TLS の途中)/ request(リクエストの送信)/ response(応答待ち)/ body(本文の受信)/ check(中身が JSON でない)。

  python -X utf8 collect/diag_probe.py --out <file> --per-ip 10 --interval 1 --timeout 10 --max-requests 100 --max-ips 8 --total-timeout 900
"""
import argparse
import functools
import http.client
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HOST = "api.open-meteo.com"
PATH = "/data/jma_msm/static/meta.json"
URL = f"https://{HOST}{PATH}"
SCHEMA = "biyori-diag-ip/1"


def resolve(host=HOST, getaddrinfo=None):
    """→ [{"ip", "family"}](重複なし・名前解決の順)。"""
    getaddrinfo = getaddrinfo or socket.getaddrinfo
    out, seen = [], set()
    for fam, _, _, _, sa in getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        ip = sa[0]
        if ip in seen:
            continue
        seen.add(ip)
        out.append({"ip": ip, "family": "IPv6" if fam == socket.AF_INET6 else "IPv4"})
    return out


class PinnedConnection(http.client.HTTPSConnection):
    """接続先の IP だけを固定する HTTPS の接続。段階ごとの時刻を probe(dict)に書く。"""

    def __init__(self, host, *, ip, probe, context, **kw):
        super().__init__(host, context=context, **kw)
        self._ip, self._probe, self._ctx = ip, probe, context

    def connect(self):
        p = self._probe
        p["stage"] = "tcp"
        t = time.perf_counter()
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        p["tcp_s"] = round(time.perf_counter() - t, 3)
        p["stage"] = "tls"
        t = time.perf_counter()
        try:
            self.sock = self._ctx.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise
        p["tls_s"] = round(time.perf_counter() - t, 3)
        p["stage"] = "request"

    def getresponse(self):
        p = self._probe
        p["stage"] = "response"
        t = time.perf_counter()
        r = super().getresponse()
        p["wait_s"] = round(time.perf_counter() - t, 3)
        p["stage"] = "body"
        return r


class PinnedHandler(urllib.request.HTTPSHandler):
    def __init__(self, ip, probe, context):
        super().__init__(context=context)
        self._ip, self._probe, self._ctx = ip, probe, context

    def https_open(self, req):
        return self.do_open(functools.partial(PinnedConnection, ip=self._ip, probe=self._probe), req, context=self._ctx)


def _reason(e):
    r = getattr(e, "reason", None)
    return type(r).__name__ if isinstance(r, BaseException) else None


def probe_once(ip, timeout_s, context=None):
    """1 回: 新しい接続で meta.json を GET。→ 記録(dict)。例外は記録にして返す(4xx/5xx は計測フックがその前に中止する)。"""
    p = {"ip": ip, "stage": None}
    ctx = context or ssl.create_default_context()
    t0 = time.perf_counter()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PinnedHandler(ip, p, ctx))
        with opener.open(URL, timeout=timeout_s) as r:
            body = r.read()
            p["status"], p["bytes"] = r.status, len(body)
        p["stage"] = "check"
        json.loads(body.decode("utf-8"))
        p["ok"], p["stage"] = True, "done"
    except (OSError, ValueError, http.client.HTTPException) as e:
        p["ok"] = False
        p["error"] = type(e).__name__
        if _reason(e):
            p["error_reason"] = _reason(e)
        p["error_msg"] = str(e)[:200]
    p["failed_stage"] = None if p["ok"] else p["stage"]
    p.pop("stage")
    p["total_s"] = round(time.perf_counter() - t0, 3)
    return p


def plan(ips, per_ip, max_total):
    """IP を順に回す順番 → [(ip, 何回目)]。max_total で打ち切る。"""
    order = [(x["ip"], i) for i in range(1, per_ip + 1) for x in ips]
    return order[:max_total]


def run_plan(order, *, interval_s, total_timeout_s, probe, sleep=time.sleep, clock=time.monotonic):
    """→ (記録のリスト, やめた理由 または None)。始まりから次の始まりまで interval_s 秒以上あける。時間の上限を超えたら次を始めない。"""
    results, start, last = [], clock(), None
    for ip, i in order:
        if clock() - start >= total_timeout_s:
            return results, "time_budget"
        if last is not None:
            wait = interval_s - (clock() - last)
            if wait > 0:
                sleep(wait)
        if clock() - start >= total_timeout_s:          # 待ったあとにも確かめる(上限を過ぎてから始めない)
            return results, "time_budget"
        last = clock()
        r = probe(ip)
        r.update(i=i, t_s=round(last - start, 1))
        results.append(r)
    return results, None


def _q(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return {"min": xs[0], "median": xs[len(xs) // 2] if len(xs) % 2 else round((xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2, 3), "max": xs[-1]}


def summarize(ips, results):
    """IP ごとの成功・失敗の数、失敗の段階・種類、所要時間(成功した回の TLS・応答待ち・合計)。"""
    out = []
    for x in ips:
        rs = [r for r in results if r["ip"] == x["ip"]]
        ok = [r for r in rs if r["ok"]]
        stages, errors = {}, {}
        for r in rs:
            if not r["ok"]:
                stages[r["failed_stage"]] = stages.get(r["failed_stage"], 0) + 1
                e = r["error"] + (f"({r['error_reason']})" if r.get("error_reason") else "")
                errors[e] = errors.get(e, 0) + 1
        out.append({"ip": x["ip"], "family": x["family"], "tries": len(rs), "ok": len(ok), "failed": len(rs) - len(ok),
                    "failed_stage": dict(sorted(stages.items())), "errors": dict(sorted(errors.items())),
                    "tls_s": _q([r.get("tls_s") for r in ok]), "wait_s": _q([r.get("wait_s") for r in ok]),
                    "total_s_ok": _q([r["total_s"] for r in ok]), "total_s_failed": _q([r["total_s"] for r in rs if not r["ok"]])})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-ip", type=int, required=True)
    ap.add_argument("--interval", type=float, required=True)
    ap.add_argument("--timeout", type=float, required=True)
    ap.add_argument("--max-requests", type=int, required=True)
    ap.add_argument("--max-ips", type=int, required=True)
    ap.add_argument("--total-timeout", type=float, required=True)
    ap.add_argument("--ips", help="テスト用: 名前解決をせず、このカンマ区切りの IP を使う")
    a = ap.parse_args(argv)
    doc = {"schema": SCHEMA, "host": HOST, "path": PATH,
           "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "settings": {"per_ip": a.per_ip, "interval_s": a.interval, "timeout_s": a.timeout, "max_requests": a.max_requests,
                        "max_ips": a.max_ips, "total_timeout_s": a.total_timeout},
           "resolved": [], "ips_used": [], "results": [], "stop": None, "resolve_error": None}
    try:
        ips = [{"ip": x, "family": "IPv6" if ":" in x else "IPv4"} for x in a.ips.split(",")] if a.ips else resolve()
    except OSError as e:
        ips = []
        doc["resolve_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    doc["resolved"] = ips
    used = ips[:a.max_ips]
    doc["ips_used"] = used
    order = plan(used, a.per_ip, a.max_requests)
    if len(order) < len(used) * a.per_ip:
        doc["stop"] = "request_budget"
    results, stop = run_plan(order, interval_s=max(1.0, a.interval), total_timeout_s=a.total_timeout,
                             probe=lambda ip: probe_once(ip, a.timeout))
    doc["results"] = results
    doc["stop"] = stop or doc["stop"]
    doc["summary"] = summarize(used, results)
    doc["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
