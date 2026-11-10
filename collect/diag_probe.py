"""子プロセスとして動く: api.open-meteo.com の IP アドレスごとに、応答するかを調べる(診断。collect/diag.py が計測フックつきで起動する)。
標準ライブラリだけ。取得するのは meta.json(jma_msm)だけ。

確かめたい見立て(未確認の仮説): 「新しい接続を始めるときに一定の割合で止まる。接続を使い回せば失敗が減る」。
そのため、IP アドレスごとに 2 つの方式を比べる:
- new(新しい接続): 1 回ごとに新しい TCP・TLS の接続を張って meta.json を GET する(ヤマビヨリの requests.get と同じ形)。
- reuse(接続の使い回し): IP ごとに 1 本の接続を張り、その接続で GET を続ける。切れたら(失敗・相手が閉じた)次の回に張り直す。
  どの回で接続を張った(張り直した)か、そのとき失敗したかを記録する。
順番: 1 回目を全 IP、2 回目を全 IP…と回し、IP ごとに new と reuse を交互に行う(奇数回は new が先、偶数回は reuse が先)。
時刻による違いが、特定の IP や方式に偏らないようにするため。

- 回と回のあいだは interval_s 秒以上あける(始まりから次の始まりまで。1 未満は 1)。打ち切りは timeout_s 秒(TCP の接続・TLS・応答待ち・受信の各段階ごと)。
- 回数の上限: max_requests(計測フックも同じ上限で止める)。時間の上限: total_timeout_s(超えたら次の回を始めない)。
- 通信はどちらの方式も urllib(OpenerDirector.open)を通すので、計測フックが数え・許可ホストを検査し・4xx/5xx(429 を含む)なら即中止する。
  接続先の IP だけを固定し、TLS の名前(SNI)と証明書の検査・Host は api.open-meteo.com のまま。
- 失敗した段階を記録する: tcp(TCP の接続)/ tls(TLS の途中)/ request(リクエストの送信)/ response(応答待ち)/ body(本文の受信)/ check(中身が JSON でない)。

  python -X utf8 collect/diag_probe.py --out <file> --per-ip 30 --interval 1 --timeout 10 --max-requests 300 --max-ips 8 --total-timeout 1800
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
SCHEMA = "biyori-diag-ip/2"
MODES = ("new", "reuse")


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
    """接続先の IP だけを固定する HTTPS の接続。段階ごとの時刻を probe(dict。回ごとに差し替える)に書く。"""

    def __init__(self, host, *, ip, probe, context, **kw):
        super().__init__(host, context=context, **kw)
        self._ip, self.probe, self._ctx = ip, probe, context

    def connect(self):
        p = self.probe
        p["connected"] = True                 # この回で新しい接続を張った
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
        p = self.probe
        p["stage"] = "response"
        t = time.perf_counter()
        r = super().getresponse()
        p["wait_s"] = round(time.perf_counter() - t, 3)
        p["stage"] = "body"
        return r


class PinnedHandler(urllib.request.HTTPSHandler):
    """new: urllib のふつうの開き方(1 回ごとに新しい接続。Connection: close)。"""

    def __init__(self, ip, probe, context):
        super().__init__(context=context)
        self._ip, self._probe, self._ctx = ip, probe, context

    def https_open(self, req):
        return self.do_open(functools.partial(PinnedConnection, ip=self._ip, probe=self._probe), req, context=self._ctx)


class ReuseHandler(urllib.request.HTTPSHandler):
    """reuse: 1 本の接続を持ち続け、回ごとにその接続で GET する(Connection: close を付けない)。
    urllib の do_open は 1 回ごとに接続を閉じるので、ここでは do_open を使わず同じ手順(ヘッダの組み立て・request・getresponse)を行う。
    失敗したら接続を閉じる(次の回に http.client が張り直す)。相手が閉じた(Connection: close)ときも次の回に張り直す。"""

    def __init__(self, ip, context):
        super().__init__(context=context)
        self._ip, self._ctx, self.conn, self.probe = ip, context, None, None

    def https_open(self, req):
        if self.conn is None:
            self.conn = PinnedConnection(req.host, ip=self._ip, probe=self.probe, context=self._ctx, timeout=req.timeout)
        h = self.conn
        h.probe = self.probe
        headers = dict(req.unredirected_hdrs)
        headers.update(req.headers)
        headers = {name.title(): val for name, val in headers.items()}
        try:
            try:
                h.request(req.get_method(), req.selector, req.data, headers)
            except OSError as err:
                raise urllib.error.URLError(err)
            r = h.getresponse()
        except BaseException:
            h.close()
            raise
        r.url = req.get_full_url()
        r.msg = r.reason
        return r

    def close(self):
        if self.conn is not None:
            self.conn.close()


def _reason(e):
    r = getattr(e, "reason", None)
    return type(r).__name__ if isinstance(r, BaseException) else None


def fetch(opener, p, timeout_s, on_error=None):
    """opener で meta.json を 1 回取る。結果を p(dict)に書いて返す。"""
    t0 = time.perf_counter()
    try:
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
        if on_error:
            on_error()
    p["failed_stage"] = None if p["ok"] else p.get("stage")
    p.pop("stage", None)
    p["total_s"] = round(time.perf_counter() - t0, 3)
    return p


def probe_once(ip, timeout_s, context=None):
    """new: 新しい接続で 1 回。→ 記録(dict)。4xx/5xx は計測フックがその前に中止する。"""
    p = {"ip": ip, "mode": "new", "connected": False, "stage": None}
    ctx = context or ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PinnedHandler(ip, p, ctx))
    return fetch(opener, p, timeout_s)


class Reuser:
    """reuse: IP ごとに 1 本の接続を使い回す。"""

    def __init__(self, ip, context=None):
        self.ip = ip
        self.handler = ReuseHandler(ip, context or ssl.create_default_context())
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), self.handler)
        self.connects = 0

    def once(self, timeout_s):
        p = {"ip": self.ip, "mode": "reuse", "connected": False, "stage": "request"}
        self.handler.probe = p
        fetch(self.opener, p, timeout_s, on_error=self.handler.close)
        if p["connected"]:
            self.connects += 1
            p["reconnect"] = self.connects > 1           # 2 本目以降 = 張り直し
        return p

    def close(self):
        self.handler.close()


def plan(ips, per_ip, max_total):
    """→ [(方式, ip, 何回目)]。1 回目を全 IP、2 回目を全 IP…。IP ごとに new と reuse を交互(奇数回は new が先)。max_total で打ち切る。"""
    order = []
    for i in range(1, per_ip + 1):
        for x in ips:
            pair = MODES if i % 2 else MODES[::-1]
            order += [(m, x["ip"], i) for m in pair]
    return order[:max_total]


def run_plan(order, *, interval_s, total_timeout_s, probe, sleep=time.sleep, clock=time.monotonic):
    """→ (記録のリスト, やめた理由 または None)。probe(方式, ip) → 記録。始まりから次の始まりまで interval_s 秒以上あける。
    時間の上限を超えたら次を始めない(待つ前と待ったあとの両方で確かめる)。"""
    results, start, last = [], clock(), None
    for mode, ip, i in order:
        if clock() - start >= total_timeout_s:
            return results, "time_budget"
        if last is not None:
            wait = interval_s - (clock() - last)
            if wait > 0:
                sleep(wait)
        if clock() - start >= total_timeout_s:
            return results, "time_budget"
        last = clock()
        r = probe(mode, ip)
        r.update(i=i, t_s=round(last - start, 1))
        results.append(r)
    return results, None


def _q(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    med = xs[n // 2] if n % 2 else round((xs[n // 2 - 1] + xs[n // 2]) / 2, 3)
    return {"min": xs[0], "median": med, "max": xs[-1]}


def summarize(ips, results):
    """IP ごと・方式ごと: 成功・失敗の数、失敗した段階・種類、新しい接続を張った回とそのうちの失敗、
    張らなかった回(使い回し)とそのうちの失敗、張り直しの回数とそのときの失敗、所要時間(成功した回)。"""
    out = []
    for x in ips:
        for mode in MODES:
            rs = [r for r in results if r["ip"] == x["ip"] and r.get("mode", "new") == mode]
            ok = [r for r in rs if r["ok"]]
            stages, errors = {}, {}
            for r in rs:
                if not r["ok"]:
                    stages[r["failed_stage"]] = stages.get(r["failed_stage"], 0) + 1
                    e = r["error"] + (f"({r['error_reason']})" if r.get("error_reason") else "")
                    errors[e] = errors.get(e, 0) + 1
            conn = [r for r in rs if r.get("connected")]
            kept = [r for r in rs if not r.get("connected")]
            re_ = [r for r in rs if r.get("reconnect")]
            out.append({"ip": x["ip"], "family": x["family"], "mode": mode, "tries": len(rs), "ok": len(ok), "failed": len(rs) - len(ok),
                        "failed_stage": dict(sorted(stages.items(), key=str)), "errors": dict(sorted(errors.items())),
                        "new_conn": len(conn), "new_conn_failed": sum(not r["ok"] for r in conn),
                        "kept_conn": len(kept), "kept_conn_failed": sum(not r["ok"] for r in kept),
                        "reconnects": len(re_), "reconnect_failed": sum(not r["ok"] for r in re_),
                        "tls_s": _q([r.get("tls_s") for r in ok]), "wait_s": _q([r.get("wait_s") for r in ok]),
                        "total_s_ok": _q([r["total_s"] for r in ok]), "total_s_failed": _q([r["total_s"] for r in rs if not r["ok"]])})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-ip", type=int, required=True, help="IP ごと・方式ごとの回数")
    ap.add_argument("--interval", type=float, required=True)
    ap.add_argument("--timeout", type=float, required=True)
    ap.add_argument("--max-requests", type=int, required=True)
    ap.add_argument("--max-ips", type=int, required=True)
    ap.add_argument("--total-timeout", type=float, required=True)
    ap.add_argument("--ips", help="テスト用: 名前解決をせず、このカンマ区切りの IP を使う")
    a = ap.parse_args(argv)
    doc = {"schema": SCHEMA, "host": HOST, "path": PATH, "modes": list(MODES),
           "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "settings": {"per_ip": a.per_ip, "interval_s": max(1.0, a.interval), "timeout_s": a.timeout, "max_requests": a.max_requests,
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
    if len(order) < len(used) * a.per_ip * len(MODES):
        doc["stop"] = "request_budget"
    reusers = {x["ip"]: Reuser(x["ip"]) for x in used}

    def probe(mode, ip):
        return probe_once(ip, a.timeout) if mode == "new" else reusers[ip].once(a.timeout)
    try:
        results, stop = run_plan(order, interval_s=max(1.0, a.interval), total_timeout_s=a.total_timeout, probe=probe)
    finally:
        for r in reusers.values():
            r.close()
    doc["results"] = results
    doc["stop"] = stop or doc["stop"]
    doc["summary"] = summarize(used, results)
    doc["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
