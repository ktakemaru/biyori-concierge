"""「今週末」「来週末」「明日」「YYYY-MM-DD」「範囲」を決定論で日付にする(LLM に日付計算をさせない)。規則は docs/dates.md。
元は biyori-hub hub/core/dates.py(commit 97e678c)の weekend()・_day_label()・_range()(docs/ported-from-hub.md)。
import 先をこのパッケージに直し、来週末・明日・日付・範囲を足した。tonight・days は使わないので写していない。"""
from datetime import date, datetime, timedelta

from .common import JST, WEEKDAY_JA, iso

MAX_RANGE_DAYS = 31      # 範囲の長さの上限(日)。誤入力で長い範囲を作らないための安全弁。仮置き


def _day_label(d):
    return {"date": d.isoformat(), "weekday": WEEKDAY_JA[d.weekday()],
            "label": f"{d.month}月{d.day}日({WEEKDAY_JA[d.weekday()]})"}


def _range(start_day, end_day):
    """start_day の 00:00 JST から end_day の 23:59 JST まで(両端の日を含む)。"""
    start = datetime(start_day.year, start_day.month, start_day.day, 0, 0, tzinfo=JST)
    end = datetime(end_day.year, end_day.month, end_day.day, 23, 59, tzinfo=JST)
    days, d = [], start_day
    while d <= end_day:
        days.append(_day_label(d))
        d += timedelta(days=1)
    return {"time_range": {"start": iso(start), "end": iso(end)}, "days": days}


def weekend(today):
    """土曜 → 当日の土〜日 / 日曜 → 当日の日のみ / 平日(月〜金) → 次の土〜日。(hub と同じ)"""
    wd = today.weekday()
    if wd == 5:
        sat = today
        out = _range(sat, sat + timedelta(days=1))
    elif wd == 6:
        out = _range(today, today)
    else:
        sat = today + timedelta(days=5 - wd)
        out = _range(sat, sat + timedelta(days=1))
    out["rule"] = "weekend"
    return out


def next_weekend(today):
    """「今週末」の次の土〜日(今日が日曜なら、次の土〜日)。"""
    if today.weekday() == 6:                      # 日曜: 今週末は今日だけ。来週末は次の土〜日
        s = today + timedelta(days=6)
    else:                                         # 月〜土: 今週末の土曜の 7 日後
        s = date.fromisoformat(weekend(today)["days"][0]["date"]) + timedelta(days=7)
    out = _range(s, s + timedelta(days=1))
    out["rule"] = "next_weekend"
    return out


def resolve(when, today):
    """when(文字列)→ {rule, spec, time_range, days, today}。読めなければ ValueError。"""
    if isinstance(today, str):
        today = date.fromisoformat(today)
    w = (when or "今週末").strip()
    if w in ("今週末", "週末", "weekend"):
        r = weekend(today)
    elif w in ("来週末", "next_weekend"):
        r = next_weekend(today)
    elif w in ("明日", "tomorrow"):
        r = _range(today + timedelta(days=1), today + timedelta(days=1))
        r["rule"] = "tomorrow"
    elif ".." in w:
        a, b = (x.strip() for x in w.split("..", 1))
        s, e = date.fromisoformat(a), date.fromisoformat(b)
        if e < s:
            raise ValueError(f"範囲の終わりが始まりより前: {w}")
        if (e - s).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f"範囲が長すぎる({MAX_RANGE_DAYS} 日まで): {w}")
        r = _range(s, e)
        r["rule"] = "range"
    else:
        try:
            d = date.fromisoformat(w)
        except ValueError:
            raise ValueError(f"日付として読めない: {w}(今週末・来週末・明日・YYYY-MM-DD・YYYY-MM-DD..YYYY-MM-DD)") from None
        r = _range(d, d)
        r["rule"] = "date"
    r["spec"] = w
    r["today"] = {"date": today.isoformat(), "weekday": WEEKDAY_JA[today.weekday()]}
    return r
