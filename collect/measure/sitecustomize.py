"""通信の計測と安全停止の専用フック(通信の動作は変えない)。PYTHONPATH にこのフォルダを足した子プロセスだけで有効。
環境変数: BIYORI_REQ_LOG(JSONLの出力先。無ければ何もしない)、BIYORI_REQ_MAX(既定100)、
          BIYORI_ALLOW_HOSTS(許可ホストのカンマ区切り。起動側が必ず明示する。通信を許さないときは `none`(明示の値)。
          未設定・空文字・`none`(大文字小文字を問わない)・`none` が他のホストと混ざった値は、すべての通信を送信前に拒否する
          (フェール・クローズ。段階11で none/空文字、段階12で未設定も。以前は未設定なら api.open-meteo.com を許可していた)、
          BIYORI_MIN_INTERVAL_S(通信の最小間隔・秒。既定 0.6。直前の通信の開始からこれ未満なら、送る前に待つだけ。待ち以外は何も変えない。
          環境変数は既定より「長くする」方向にだけ効く: 既定以下は無視、数値でない・負・30 秒超は拒否し、いずれも stderr に記録)、
          BIYORI_SUSPEND_GAP_S(スリープ疑いの検出・秒。既定 300 = 仮置き。連続するリクエストの間、または1リクエスト自体が壁時計でこれを超えたら、
          次のリクエストの前に中止 = abort 'suspend_suspected'。取得済みの応答はキャッシュに残るので、続きから再実行できる)。
数える通信: `requests`(Session.request 経由)と `urllib.request`(OpenerDirector.open 経由。Skyfield の自動取得など)。
記録: host / path / 変数の数 / 予報日数 / HTTPステータス / 所要時間 / 応答サイズ(requests のみ) だけ(座標・応答本文は記録しない)。
安全停止(os._exit(75)。リトライさせず、vendor 側の except にも捕まらない):
  1) 件数が上限に達したら、次の送信の前に中止
  2) 許可リスト外のホストへの送信は、送る前に中止
  0) 最初の送信の前に、BIYORI_REQ_LOG(と BIYORI_COUNT_LOG)が絶対パスで書き込めることを確かめる。だめなら通信せずに中止
     (段階10: 子プロセスの作業ディレクトリは runtime なので、相対パスだと記録できないまま通信してしまった)
  3) ステータス 4xx/5xx(429 を含む)なら即中止
     例外(オプトイン。段階9b): BIYORI_HTTP_RETRY_STATUSES(例 "502,503,504")を渡された子プロセスだけ、その一時的なサーバー障害を
     『呼び出し側が再試行する』前提で中止せず、記録に retry_tolerated を付ける。429・500・その他の 4xx/5xx は、設定があっても即中止(対象にできるのは 502/503/504 だけ)。
     連続(BIYORI_HTTP_RETRY_MAX_CONSEC)または実行全体(BIYORI_HTTP_RETRY_MAX_TOTAL)の上限を超えたら中止する。どちらかが未設定・不正ならオプトインなし(従来どおり全部中止)。
非 200 のときだけ、応答本文の先頭 200 文字(制御文字は除去。URL のクエリ文字列は伏せる)を body_head に記録する。
許可リストは環境変数でのみ決まる(既定は全拒否)。コード側で勝手に広げない。"""
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

_LOG = os.environ.get("BIYORI_REQ_LOG")
_COUNT = os.environ.get("BIYORI_COUNT_LOG")      # hub の snapshot 実行が、フックの実数を台帳に残すために渡す(同じ記録の写し。任意)
_MAX = int(os.environ.get("BIYORI_REQ_MAX", "100"))


def _resolve_allow(raw):
    """BIYORI_ALLOW_HOSTS → 許可ホストの集合。未設定(None)・空文字・none・none と他の値の混在は空集合(全拒否。段階12で未設定も全拒否に)。
    空文字は環境によっては『未設定』と区別されないことがあるため、通信を許さないときは none を明示して渡す(snapshotter はそうする)。"""
    if raw is None:
        return set()
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    return set() if not hosts or "none" in hosts else hosts


_ALLOW = _resolve_allow(os.environ.get("BIYORI_ALLOW_HOSTS"))
_BASE_MIN_INTERVAL = 0.6     # 安全弁: 1分あたりの call 上限(600)を超えない最短(約5.4 call/リクエストで 0.54 秒)
_MAX_MIN_INTERVAL = 30.0     # 環境変数の上限(これを超える値は誤りとして拒否)。仮置き


def _resolve_min_interval(raw, base=_BASE_MIN_INTERVAL, cap=_MAX_MIN_INTERVAL):
    """BIYORI_MIN_INTERVAL_S は、既定(base)より「長くする」方向にだけ効く。→ (採用する秒, ログの文 または None)。
    未設定は base・ログなし。数値でない・nan/inf・負・cap 超は拒否して base。base 以下(短くする指定)は無視して base。"""
    if raw is None:
        return base, None
    try:
        v = float(raw)
    except ValueError:
        return base, f"BIYORI_MIN_INTERVAL_S={raw!r} は数値でないため拒否し、既定 {base:g} 秒を使う"
    if v != v or v in (float("inf"), float("-inf")) or v < 0 or v > cap:
        return base, f"BIYORI_MIN_INTERVAL_S={raw!r} は範囲外(0〜{cap:g} 秒)のため拒否し、既定 {base:g} 秒を使う"
    if v <= base:
        return base, f"BIYORI_MIN_INTERVAL_S={raw!r} は既定 {base:g} 秒以下(短くする指定は無視する)。既定 {base:g} 秒を使う"
    return v, f"BIYORI_MIN_INTERVAL_S={raw!r} を採用(最小間隔を既定 {base:g} 秒から {v:g} 秒に長くする)"


_MIN_INTERVAL, _interval_note = _resolve_min_interval(os.environ.get("BIYORI_MIN_INTERVAL_S"))
if _interval_note:          # 環境変数があるときだけ出す(自宅の実行=変数なしの出力は変わらない)
    sys.stderr.write(f"[biyori-measure] {_interval_note}\n")
_RETRYABLE = {502, 503, 504}           # オプトインできる状態コードの全体(これ以外は設定があっても即中止。429 を含まない)
_BODY_HEAD_MAX = 200


def _resolve_http_retry(statuses_raw, consec_raw, total_raw):
    """→ (許容する状態コードの集合, 連続の上限, 全体の上限, ログの文 または None)。3 つとも正しく揃ったときだけ有効。揃わなければ空集合(従来どおり全部中止)。"""
    if statuses_raw is None and consec_raw is None and total_raw is None:
        return frozenset(), 0, 0, None
    try:
        sts = {int(x) for x in str(statuses_raw).split(",") if x.strip()}
        consec, total = int(consec_raw), int(total_raw)
    except (TypeError, ValueError):
        return frozenset(), 0, 0, "BIYORI_HTTP_RETRY_* が不正のため、HTTP 再試行の許容は無効(全非 200 で中止)"
    if consec < 1 or total < 1:
        return frozenset(), 0, 0, "BIYORI_HTTP_RETRY_MAX_* が 1 未満のため、HTTP 再試行の許容は無効(全非 200 で中止)"
    ok = sts & _RETRYABLE
    note = f"HTTP 再試行の許容を有効化: 状態コード {sorted(ok)}、連続 {consec} 回・全体 {total} 回まで(それ以外の非 200 は即中止)"
    if sts - ok:
        note += f"。{sorted(sts - ok)} は対象にできないため無視した"
    return frozenset(ok), consec, total, note


_HTTP_RETRY, _HTTP_CONSEC_MAX, _HTTP_TOTAL_MAX, _http_note = _resolve_http_retry(
    os.environ.get("BIYORI_HTTP_RETRY_STATUSES"), os.environ.get("BIYORI_HTTP_RETRY_MAX_CONSEC"), os.environ.get("BIYORI_HTTP_RETRY_MAX_TOTAL"))
if _http_note:
    sys.stderr.write(f"[biyori-measure] {_http_note}\n")
_http_consec = 0           # 連続して許容した件数(200 台・300 台の応答で 0 に戻る)
_http_total = 0            # 実行全体で許容した件数
_last_start = None
_GAP = float(os.environ.get("BIYORI_SUSPEND_GAP_S", "300"))
_last_end_wall = None      # 直前のリクエストが終わった壁時計の時刻
_cur_start_wall = None     # 今のリクエストを始めた壁時計の時刻
_long_request_s = None     # 1リクエスト自体が _GAP を超えたときの所要秒(壁時計)
_count = 0


def _gap_check(wall=time.time):
    """壁時計の飛び(スリープの疑い)の検査。空き(前のリクエストの終了から今まで)、または前のリクエスト自体の所要が _GAP 秒を超えていたら、送る前に中止する。
    戻り値: (中止すべき理由, 追加情報) または None。実際の中止は呼び出し側(_before)が行う(テストできるよう分けてある)。"""
    if _long_request_s is not None:
        return f"suspend_suspected: 直前のリクエストが壁時計で {_long_request_s:.0f} 秒かかった(> {_GAP:.0f} 秒)", {"gap_kind": "long_request", "gap_s": round(_long_request_s, 1)}
    if _last_end_wall is not None:
        gap = wall() - _last_end_wall
        if gap > _GAP:
            return f"suspend_suspected: リクエストの間に壁時計で {gap:.0f} 秒の空き(> {_GAP:.0f} 秒)", {"gap_kind": "between_requests", "gap_s": round(gap, 1)}
    return None


def _mark_start(wall=time.time):
    global _cur_start_wall
    _cur_start_wall = wall()


def _mark_end(wall=time.time):
    """リクエスト(成功・失敗とも)の終了。壁時計の所要が _GAP を超えていれば、次のリクエストの前に中止するための印を残す。"""
    global _last_end_wall, _long_request_s
    _last_end_wall = wall()
    if _cur_start_wall is not None and _last_end_wall - _cur_start_wall > _GAP:
        _long_request_s = _last_end_wall - _cur_start_wall


def _pace(now=time.monotonic, sleep=time.sleep):
    """直前の通信の開始から _MIN_INTERVAL 秒未満なら、その分だけ待つ(待つだけ。通信の中身は変えない)。ベンダー側の待ち時間にも触れない。"""
    global _last_start
    if _last_start is not None:
        wait = _MIN_INTERVAL - (now() - _last_start)
        if wait > 0:
            sleep(wait)
    _last_start = now()


def _body_head(raw, url=None, limit=_BODY_HEAD_MAX):
    """非 200 の応答本文の先頭 limit 文字。bytes でも str でも可(非 UTF-8 は置換)。改行・タブは空白、その他の制御文字は除去。URL のクエリ文字列が本文に出ていれば伏せる。"""
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    q = urlsplit(url).query if url else ""
    if q:
        text = text.replace(q, "<query>")
    for ws in ("\r", "\n", "\t"):                       # 改行・タブは空白に
        text = text.replace(ws, " ")
    return "".join(ch for ch in text if ch >= " " and ch != "\x7f")[:limit]          # 残りの制御文字は除去


def _judge_http(status):
    """非 200(>= 400)の扱い。→ 中止の理由 または None(許容)。許容するのはオプトイン済みの 502/503/504 で、連続・全体の上限内のときだけ。"""
    global _http_consec, _http_total
    if status in _HTTP_RETRY:
        if _http_consec + 1 > _HTTP_CONSEC_MAX:
            return f"HTTP {status}(再試行の連続の上限 {_HTTP_CONSEC_MAX} 回を超えた。再試行を使い切った)"
        if _http_total + 1 > _HTTP_TOTAL_MAX:
            return f"HTTP {status}(再試行の実行全体の上限 {_HTTP_TOTAL_MAX} 回を超えた。再試行を使い切った)"
        _http_consec += 1
        _http_total += 1
        return None
    return f"HTTP {status}"


def _write(rec):
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    for path in (_LOG, _COUNT):
        if path:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)


def _nvars(v):
    return len(v.split(",")) if isinstance(v, str) and v else (len(v) if isinstance(v, (list, tuple)) else 0)


def _stop(reason, extra=None, write=True):
    if write:
        try:
            _write(dict({"abort": reason, "count": _count}, **(extra or {})))
        except BaseException:       # 記録に失敗しても必ず止める
            pass
    sys.stderr.write(f"[biyori-measure] 中止: {reason}\n")
    sys.stderr.flush()
    os._exit(75)


_log_checked = False


def _ensure_log_writable():
    """最初の送信の前に1回だけ: 記録先が絶対パスで書き込めることを確かめる。だめなら通信せずに中止(フェール・クローズ)。
    中止の記録は書かない(書けない・相対パスの先に書いてしまうため)。理由は stderr に出る。"""
    global _log_checked
    if _log_checked:
        return
    for name, path in (("BIYORI_REQ_LOG", _LOG), ("BIYORI_COUNT_LOG", _COUNT)):
        if not path:
            continue
        if not os.path.isabs(path):
            _stop(f"{name} が絶対パスでない(通信前に中止): {path}", write=False)
        try:
            with open(path, "a", encoding="utf-8", newline="\n"):
                pass
        except OSError as e:
            _stop(f"{name} に書き込めない(通信前に中止): {e}", write=False)
    _log_checked = True


def _before(method, url, params, via):
    """送信前の検査と記録の下ごしらえ。記録先が書けない・許可外ホスト・上限超過ならここで中止する。"""
    global _count
    _ensure_log_writable()
    u = urlsplit(url)
    host = u.netloc.lower()
    if host.split(":")[0] not in _ALLOW and host not in _ALLOW:
        why = "" if os.environ.get("BIYORI_ALLOW_HOSTS") is not None else "(BIYORI_ALLOW_HOSTS が未設定のため全拒否)"
        _stop(f"許可リスト外のホストへの通信: {host}{why}", {"host": host, "path": u.path, "via": via})
    g = _gap_check()
    if g:
        _stop(g[0], dict(g[1], host=host))
    if _count >= _MAX:
        _stop(f"リクエストが上限 {_MAX} 件に達した")
    _count += 1
    _pace()
    _mark_start()
    p = params or {}
    return {"n": _count, "t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "via": via,
            "method": method.upper(), "host": host, "path": u.path,
            "hourly_vars": _nvars(p.get("hourly")), "daily_vars": _nvars(p.get("daily")),
            "forecast_days": p.get("forecast_days"), "past_days": p.get("past_days")}


def _after(rec, status, t0, nbytes=None, body=None, url=None):
    global _http_consec
    _mark_end()
    rec.update(status=status, elapsed_s=round(time.perf_counter() - t0, 3), wall_s=round(time.time() - _cur_start_wall, 1), bytes=nbytes)
    stop = None
    if status is not None and status >= 400:
        rec["body_head"] = _body_head(body, url)         # 非 200 のときだけ(200 の本文は記録しない)
        stop = _judge_http(status)
        if stop is None:
            rec["retry_tolerated"] = True
    elif status is not None:
        _http_consec = 0
    _write(rec)
    if stop:
        _stop(stop)


if _LOG:
    try:
        import urllib.error
        import urllib.request
        try:
            import requests             # venv によっては無い(例: ハブの venv)。その場合は urllib だけ数える
        except ImportError:
            requests = None

        _orig_req = requests.sessions.Session.request if requests else None

        def _wrapped_req(self, method, url, *a, **kw):
            rec = _before(method, url, kw.get("params"), "requests")
            t0 = time.perf_counter()
            try:
                resp = _orig_req(self, method, url, *a, **kw)
            except BaseException as e:
                rec.update(status=None, error=type(e).__name__, error_msg=str(e)[:200], elapsed_s=round(time.perf_counter() - t0, 3), wall_s=round(time.time() - _cur_start_wall, 1))
                _mark_end()
                _write(rec)
                raise
            _after(rec, resp.status_code, t0, len(resp.content) if resp.raw is not None and not kw.get('stream') else None,
                   body=(resp.content[:4 * _BODY_HEAD_MAX] if resp.status_code >= 400 and not kw.get('stream') else None), url=url)
            return resp

        if requests:
            requests.sessions.Session.request = _wrapped_req

        _orig_open = urllib.request.OpenerDirector.open

        def _wrapped_open(self, fullurl, data=None, timeout=urllib.request.socket._GLOBAL_DEFAULT_TIMEOUT):
            url = fullurl if isinstance(fullurl, str) else fullurl.full_url
            method = "POST" if data is not None else (getattr(fullurl, "get_method", lambda: "GET")())
            rec = _before(method, url, None, "urllib")
            t0 = time.perf_counter()
            try:
                resp = _orig_open(self, fullurl, data, timeout)
            except urllib.error.HTTPError as e:      # urllib は 4xx/5xx を例外にする
                body = None
                try:                                # 本文を読んだら、呼び出し側が同じ本文を読めるよう戻す
                    data = e.file.read()                # e.read() は経由しない(読み取り関数が元のファイルに束縛されて残り、戻した本文を読めなくなる)
                    e.fp = e.file = io.BytesIO(data)
                    body = data[:4 * _BODY_HEAD_MAX]
                except Exception:
                    pass
                _after(rec, e.code, t0, body=body, url=url)
                raise
            except BaseException as e:
                rec.update(status=None, error=type(e).__name__, error_msg=str(e)[:200], elapsed_s=round(time.perf_counter() - t0, 3), wall_s=round(time.time() - _cur_start_wall, 1))
                _mark_end()
                _write(rec)
                raise
            cl = resp.headers.get("Content-Length") if getattr(resp, "headers", None) else None
            _after(rec, getattr(resp, "status", None) or resp.getcode(), t0, int(cl) if cl and cl.isdigit() else None)
            return resp

        urllib.request.OpenerDirector.open = _wrapped_open
        if _COUNT:                  # フックが有効だった印(空のファイルを作る)。キャッシュヒットだけで通信が 0 件でも『0 件を数えた』と台帳に残せる(5f)
            open(_COUNT, "a", encoding="utf-8").close()
    except Exception as e:      # 計測が設定できないまま実通信させないため、止める
        sys.stderr.write(f"[biyori-measure] フックの設定に失敗: {e}\n")
        os._exit(76)
