"""ヤマビヨリ(山)の取得と、共通の形(biyori-proposal/1)への変換。

- 取得: GitHub から取り出した ktakemaru/yamabiyori(main)の `mountain_weather_mvp.py --json-out` を、計測フックつきの子プロセスで1回だけ実行する。
  ヤマビヨリのコードは書き換えない・写さない。山の一覧は `mountain_weather_core.MOUNTAINS` を ast で読むだけ(実行しない)。
- 変換: convert() は純粋関数(通信・ファイル読みなし)。同じ入力・同じ now なら同じ出力。
  元は biyori-hub adapters/yamabiyori_adapter.py の convert()(docs/ported-from-hub.md)。対応表は docs/yamabiyori-mapping.md。"""
import ast
import json
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from .common import JST, iso

AGENT = "yamabiyori"
SCHEMA_IN = "yamabiyori-report-data/1"
MOUNTAINS_SCHEMA = "biyori-mountains/1"
SCALE = "yamabiyori-0-100"
# mountain_weather_mvp.py:63 MIN_SCORE_THRESHOLD = 70.0 ・ README.md「行ける」の目安 70点
GO_THRESHOLD = 70.0
# README.md「信用してよいのは3日前まで」(hub docs/yamabiyori-mapping.md の出典の行)
RELIABLE_UP_TO_DAYS = 3
TRIP_START_OFFSET_HOURS = -1      # mountain_weather_mvp.py:89
ACTIVITY_END_GRACE_MINUTES = 30   # mountain_weather_mvp.py:149
SOURCE = "yamabiyori (Open-Meteo)"
EVIDENCE_COLUMNS = (
    ("ridge_wind_ms", "m/s"), ("cape", "J/kg"), ("cloud_pct", "%"), ("cloud_pct_raw", "%"),
    ("ridge_visibility", "m"), ("precip_wet_pct", "%"), ("precip_wet_hours", "h"),
    ("precip_total_hours", "h"), ("precip_msm_hours", "h"), ("precip_moist_hours", "h"),
    ("precip_prob_hours", "h"), ("precip_total_mm", "mm"), ("chill", "degC"),
    ("day_peak_wind_ms", "m/s"), ("day_peak_wind_hour", "hour_of_day"),
    ("day_total_precip_mm", "mm"),
)
HAZARD_LABEL = {"thunder": "雷", "wind": "強風", "cold": "低体温症"}
# mountain_weather_core.py HAZARD_LEVELS = ((0,"-"),(40,"注意"),(80,"警戒"),(100.0001,"危険"))
HAZARD_HARD = ("警戒", "危険")
KNOWN_LIMITS = [
    "点数・確信度の閾値や換算は yamabiyori 側で暫定・未検証の部分がある(README「精度と限界」)",
    "信用してよいのは3日前まで(README)",
]
NAME_RE = re.compile(r"^(?P<name>.+)\((?P<elev>\d+)m\)$")
ROW_REQUIRED = ("mountain", "score")


# ---------------------------------------------------------------- 取り出した版を読むだけ
def load_mountains(checkout):
    """mountain_weather_core.py の MOUNTAINS を ast で読む(実行しない)。id は並び順の 1 始まり mNNN
    (イキモノビヨリ data/sites.yaml の site_ref と同じ付け方)。"""
    src = (Path(checkout) / "mountain_weather_core.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "MOUNTAINS" for t in node.targets):
            raw = ast.literal_eval(node.value)
            return [dict({"id": f"m{i + 1:03d}"}, **{k: m.get(k) for k in ("name", "lat", "lon", "elevation_m", "region", "access")})
                    for i, m in enumerate(raw)]
    raise ValueError("mountain_weather_core.py に MOUNTAINS が見つからない")


def load_version(checkout):
    p = Path(checkout) / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def git_commit(checkout):
    """取り出した commit(40 桁)。git でない・読めないときは None。"""
    try:
        r = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    h = r.stdout.strip()
    return h if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", h) else None


def mountains_doc(mountains, commit, version):
    return {"schema": MOUNTAINS_SCHEMA, "agent": AGENT,
            "source": {"repo": "ktakemaru/yamabiyori", "commit": commit, "version": version,
                       "file": "mountain_weather_core.py", "variable": "MOUNTAINS"},
            "id_rule": "id = MOUNTAINS の並び順の 1 始まり(m001〜)。イキモノビヨリの site_ref(yamabiyori:mNNN)と同じ",
            "count": len(mountains), "mountains": mountains}


def command(python, checkout, json_out, limit=None):
    """引数の配列(シェルなし)。--limit は確認のときだけ。"""
    argv = [str(python), "-X", "utf8", str(Path(checkout) / "mountain_weather_mvp.py"), "--json-out", str(json_out)]
    if limit is not None:
        argv += ["--limit", str(int(limit))]
    return argv


def output_problems(native):
    """出力の形の検査(想定と違えば、その回の山は使わない)。→ 問題の文のリスト。"""
    if not isinstance(native, dict):
        return ["JSON の最上位が object でない"]
    probs = []
    if native.get("schema") != SCHEMA_IN:
        probs.append(f"schema が {SCHEMA_IN!r} でない: {native.get('schema')!r}")
    if native.get("mode") != "explore":
        probs.append(f"mode が 'explore' でない: {native.get('mode')!r}")
    days = native.get("days")
    if not isinstance(days, list) or not days:
        probs.append("days がない・空")
        return probs
    for i, d in enumerate(days):
        if not isinstance(d, dict) or not isinstance(d.get("date"), str) or not isinstance(d.get("rows"), list) \
                or not isinstance(d.get("all"), list):
            probs.append(f"days[{i}] に date・rows・all がない")
            continue
        for j, r in enumerate(d["rows"] + d["all"]):
            if not isinstance(r, dict) or any(k not in r for k in ROW_REQUIRED):
                probs.append(f"days[{i}] の行 {j} に {ROW_REQUIRED} がない")
                break
    return probs


def load_sun_times(cache_dir, mountains):
    """ヤマビヨリのキャッシュ(ecmwf_ifs025_{lat:.4f}_{lon:.4f}_15d.json の daily.sunrise/sunset)を読むだけ。
    元は biyori-hub adapters/yamabiyori_suntimes.py。→ {"lat,lon": {date: {"sunrise", "sunset"}}}"""
    from datetime import timezone
    out = {}
    for m in mountains:
        lat, lon = m["lat"], m["lon"]
        f = Path(cache_dir) / f"ecmwf_ifs025_{lat:.4f}_{lon:.4f}_15d.json"
        try:
            d = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
        except (OSError, ValueError):
            d = None
        if not isinstance(d, dict):
            continue
        daily, off = d.get("daily") or {}, d.get("utc_offset_seconds")
        if not isinstance(off, int) or not daily.get("sunrise") or not daily.get("sunset"):
            continue
        tz = timezone(timedelta(seconds=off))
        days = {}
        for t, sr, ss in zip(daily.get("time", []), daily["sunrise"], daily["sunset"]):
            if sr and ss:
                days[t] = {"sunrise": datetime.fromisoformat(sr).replace(tzinfo=tz).isoformat(timespec="minutes"),
                           "sunset": datetime.fromisoformat(ss).replace(tzinfo=tz).isoformat(timespec="minutes")}
        if days:
            out[f"{lat:.4f},{lon:.4f}"] = days
    return out


# ---------------------------------------------------------------- 変換(純粋)
def _iso_day(d, plus_days=0):
    y, m, dd = map(int, d.split("-"))
    return f"{(date(y, m, dd) + timedelta(days=plus_days)).isoformat()}T00:00:00+09:00"


def band(score):
    """70点以上=go(mountain_weather_mvp.py `r["score"] >= MIN_SCORE_THRESHOLD`。ちょうど70は go)。未満は no。
    no は「ヤマビヨリの基準(70点)未満」の意味で「行ってはいけない」ではない。score が None なら None。"""
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return "go" if score >= GO_THRESHOLD else "no"


def _constraints_from_class(hazard_class):
    """簡易行(all[])は hazard_class だけ(report_data.py hazard_class): warning=警戒/危険を含む → hard。"""
    if hazard_class == "warning":
        return [{"kind": "hazard", "text": "危険信号:警戒以上(種別はネイティブの簡易行にない)", "hard": True, "level": "警戒以上"}]
    if hazard_class == "caution":
        return [{"kind": "hazard", "text": "危険信号:注意(種別はネイティブの簡易行にない)", "hard": False, "level": "注意"}]
    return []


def _constraints(hazards):
    out = []
    for key, label in HAZARD_LABEL.items():
        level = (hazards or {}).get(key, "-")
        if level not in ("-", None):
            out.append({"kind": "hazard", "hazard": key, "level": level, "text": f"{label}:{level}",
                        "hard": level in HAZARD_HARD})
    return out


def _evidence(row, date_str):
    vt = _iso_day(date_str)
    return [{"metric": k, "value": row.get(k), "unit": unit, "valid_time": vt, "source": SOURCE, "source_type": "forecast"}
            for k, unit in EVIDENCE_COLUMNS]


def _find_mountain(mountains, name, elev):
    hits = [m for m in mountains if m["name"] == name and m["elevation_m"] == elev]
    return hits[0] if len(hits) == 1 else None


def _time_window(date_str, mtn, sun_times):
    """日の出・日没があれば activity_window(日の出−1h 〜 日没+30分)。なければ calendar_day(暦日で代用。粗い値)。"""
    sun = ((sun_times or {}).get(f"{mtn['lat']:.4f},{mtn['lon']:.4f}") or {}).get(date_str)
    if sun:
        start = datetime.fromisoformat(sun["sunrise"]) + timedelta(hours=TRIP_START_OFFSET_HOURS)
        end = datetime.fromisoformat(sun["sunset"]) + timedelta(minutes=ACTIVITY_END_GRACE_MINUTES)
        return {"start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"), "kind": "activity_window"}
    return {"start": _iso_day(date_str), "end": _iso_day(date_str, 1), "kind": "calendar_day"}


def _proposal(*, date_str, label, mtn, row, native_path, lead_days, score_only, sun_times):
    score = row.get("score")
    limits = list(KNOWN_LIMITS)
    if band(score) == "no":
        limits.append("band=no は yamabiyori の go 基準(70点)未満の意味。行ってはいけない、ではない")
    return {
        "id": f"yamabiyori:explore:{date_str}:{mtn['id']}",
        "title": f"{mtn['name']} {label}",
        "place": {"name": mtn["name"], "lat": mtn["lat"], "lon": mtn["lon"], "elevation_m": mtn["elevation_m"],
                  "region": mtn.get("region"), "location_precision": "exact", "site_ref": f"yamabiyori:{mtn['id']}"},
        "time_window": _time_window(date_str, mtn, sun_times),
        "suitability": {"band": band(score), "score": {"value": score, "scale": SCALE, "go_threshold": GO_THRESHOLD}},
        "evidence": [] if score_only else _evidence(row, date_str),
        "constraints": _constraints_from_class(row.get("hazard_class")) if score_only else _constraints(row.get("hazards")),
        "uncertainty": {"lead_days": lead_days, "reliable_up_to_days": RELIABLE_UP_TO_DAYS,
                        "confidence": {"value": None, "scale": None, "method": "none", "validated": False},
                        "known_limits": limits},
        "native_ref": {"format": SCHEMA_IN, "path": native_path},
        "details": {"native_row": row, "date": date_str, "mountain_id": mtn["id"], "access": mtn.get("access"),
                    "detail_level": "score_only" if score_only else "full"},
    }


def convert(native, *, now, fetched_at, native_path, agent_version, agent_commit, mountains, model_runs=None,
            sun_times=None, request_id="shelf"):
    """explore の出力(yamabiyori-report-data/1)→ biyori-proposal/1。
    now: 変換の時刻(オフセットつき。lead_days の基準)。fetched_at: 取得が終わった時刻(オフセットつき)。"""
    probs = output_problems(native)
    if probs:
        raise ValueError("; ".join(probs))
    if now.tzinfo is None or fetched_at.tzinfo is None:
        raise ValueError("now・fetched_at にオフセットが必要")
    today = now.astimezone(JST).date()
    warnings = ["確信度は explore では出力されないため null"]
    proposals, dropped, below = [], 0, 0
    for day in native["days"]:
        rows = day["rows"]
        in_rows = {r.get("mountain") for r in rows}
        simple = [a for a in day["all"] if a.get("mountain") not in in_rows]
        y, m_, d_ = map(int, day["date"].split("-"))
        lead = (date(y, m_, d_) - today).days
        for row in rows + simple:
            score_only = row not in rows
            m = NAME_RE.match(row.get("mountain") or "")
            mtn = _find_mountain(mountains, m["name"], int(m["elev"])) if m else None
            if mtn is None or band(row.get("score")) is None:
                dropped += 1
                warnings.append(f"{day['date']} {row.get('mountain')}: 座標またはスコアを確定できず除外")
                continue
            proposals.append(_proposal(date_str=day["date"], label=day.get("label") or day["date"], mtn=mtn, row=row,
                                       native_path=native_path, lead_days=lead, score_only=score_only, sun_times=sun_times))
            below += score_only
    if below:
        warnings.append(f"{below} 件は70点未満でネイティブが簡易行(mountain/region/score/hazard_class)しか出さないため、"
                        "evidence は空(details.detail_level=score_only)")
    n_cal = sum(p["time_window"]["kind"] == "calendar_day" for p in proposals)
    if n_cal:
        warnings.append(f"time_window が calendar_day(暦日で代用)の提案が {n_cal} 件: 日の出・日没を取れなかった(粗い値)")
    pool, fetched = native.get("pool_size"), native.get("fetched")
    partial_fetch = isinstance(pool, int) and isinstance(fetched, int) and fetched < pool
    if partial_fetch:
        warnings.append(f"ヤマビヨリが {pool} 座のうち {fetched} 座しか取得できなかった(取得できなかった山は候補にない)")
    data_as_of = [{"source": "Open-Meteo (yamabiyori)", "source_type": "forecast", "run_time": None, "fetched_at": iso(fetched_at)}]
    for model, r in (model_runs or {}).items():
        data_as_of.append({"source": f"Open-Meteo {model}", "source_type": "forecast",
                           "run_time": (r or {}).get("init"), "fetched_at": iso(fetched_at)})
    out = {
        "schema": "biyori-proposal/1",
        "request_id": request_id,
        "agent": {"id": AGENT, "version": agent_version or "unknown", "commit": agent_commit},
        "status": "partial" if (dropped or partial_fetch) else "ok",
        "generated_at": iso(now),
        "data_as_of": data_as_of,
        "proposals": proposals,
        "diagnostics": {"api_calls": None, "cache_hit": None, "runtime_s": None, "fetch_finished_at": iso(fetched_at),
                        "warnings": warnings},
        "details": {"native_generated": native.get("generated"), "native_mode": native.get("mode"),
                    "pool_size": pool, "fetched": fetched, "model_runs": model_runs or {}},
    }
    if dropped:
        out["status_reason"] = "unresolved_place_or_score"
    elif partial_fetch:
        out["status_reason"] = "partial_fetch"
    return out
