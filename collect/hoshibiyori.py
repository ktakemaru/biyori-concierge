"""ホシビヨリ(星空)の取得の部品と、共通の形(biyori-proposal/1)への変換。対応表は docs/hoshibiyori-mapping.md。

- 取得: GitHub から取り出した ktakemaru/hoshibiyori(main)の `explore_hoshibiyori.py --json-out` を、計測フックつきの子プロセスで
  2 回(星空・星座モード → 天の川モード)実行する(collect/run.py の run_hoshibiyori)。ホシビヨリのコードは書き換えない・import しない・写さない。
  順番を変えない: `--nights` は「その回に取った分と期限内の保存だけ」を読む。先に星空・星座モードで全地点の予報を取り、
  天の川モードには同じ HOSHIBIYORI_DATA_DIR の保存を使わせる(実測: 2 回目の通信は 0 回)。
- 変換: convert() は純粋関数(通信・ファイル読みなし)。同じ入力・同じ now なら同じ出力。"""
import json
from datetime import date, timedelta
from itertools import islice
from pathlib import Path

from jsonschema import Draft202012Validator

from .common import JST, iso

AGENT = "hoshibiyori"
SCHEMA_IN = "hoshibiyori-explore/1"
REPO = "ktakemaru/hoshibiyori"
# 実行する順(変えない。上の説明)
MODES = ("stars", "milkyway")
NATIVE_PATH = {m: f"hoshibiyori/{m}.json" for m in MODES}
# README.md(1.2.0)「直近約3日は気象庁MSM(約5km格子)、それ以降はECMWF IFS」
RELIABLE_UP_TO_DAYS = 3
SOURCE = "hoshibiyori (Open-Meteo)"
SOURCE_STATIC = "hoshibiyori (NASA Black Marble)"
# 点数の尺度の名前。ホシビヨリに名前の定義は無く、biyori-hub の対応表と同じ名前にした。式が違うので、互いに比べられない
SCALE = {"final": "hoshibiyori-final-score", "outlook": "hoshibiyori-outlook-score"}
KNOWN_LIMITS = ["スコアは近日中(finals)と見込み(outlooks)で式が違い、絶対値を比べられない",
                "光害の ALR は日本で未較正の相対指数",
                "雲量は全天の平均で、方角ごとの雲は分からない"]


def nights_from(start_day, n):
    """取得を始めた日(日本時間の date)から n 夜(夜の始まりの日付)。"""
    return [(start_day + timedelta(days=i)).isoformat() for i in range(int(n))]


def command(python, checkout, mode, nights, json_out):
    """引数の配列(シェルなし)。"""
    return [str(python), "-X", "utf8", str(Path(checkout) / "explore_hoshibiyori.py"), "--target", mode,
            "--nights", ",".join(nights), "--json-out", str(json_out)]


def load_schema(checkout):
    """取り出した版の出力のスキーマ(hoshibiyori-explore/1)。読めなければ ValueError。"""
    p = Path(checkout) / "schemas" / "hoshibiyori-explore.schema.json"
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(s)
    except Exception as e:
        raise ValueError(f"ホシビヨリの出力のスキーマを読めない: {type(e).__name__}") from e
    return s


def output_problems(native, schema, mode, nights):
    """出力の検査(想定と違えば、その回の星は使わない)。→ 問題の文のリスト。"""
    if not isinstance(native, dict):
        return ["JSON の最上位が object でない"]
    if native.get("schema") != SCHEMA_IN:
        return [f"schema が {SCHEMA_IN!r} でない: {native.get('schema')!r}"]
    errs = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:200]}"
            for e in islice(Draft202012Validator(schema).iter_errors(native), 5)]
    if errs:
        return errs
    out = []
    if native["target"] != mode:
        out.append(f"target が {mode!r} でない: {native['target']!r}")
    got = [r["night_date"] for r in native.get("requested_nights") or []]
    if got != list(nights):
        out.append(f"requested_nights の夜が、渡した夜と違う(渡した {len(nights)} 夜、出力 {len(got)} 夜)")
    return out


def mode_info(native):
    """モードごとの記録に残す、出力の中の取得の集計(無いときは全部 None)。"""
    f = (native or {}).get("fetch") or {}
    return {"fetch_status": f.get("status"), "api_calls": f.get("api_calls"), "cache_hits": f.get("cache_hits"),
            "total_cells": f.get("total_cells"), "failed_cells": f.get("failed_cells"),
            "generated_at": (native or {}).get("generated_at")}


# ---------------------------------------------------------------- 変換(純粋)
def ranks(native):
    """候補(finals・outlooks)の順位 → {(夜, site_id): (順位, 種類 final/outlook, スコア)}。候補の夜(上位の夜)にしか無い。"""
    out = {}
    for kind, key in (("final", "finals"), ("outlook", "outlooks")):
        for x in native.get(key) or []:
            if x.get("site_id") is not None:
                out[(x["night_date"], x["site_id"])] = (x["rank"], kind, x.get("score"))
    return out


def _ev(metric, value, unit, valid, source=SOURCE, source_type="forecast"):
    return {"metric": metric, "value": value, "unit": unit, "valid_time": valid, "source": source, "source_type": source_type}


def _proposal(mode, night, s, site, rank, lead):
    """rank = 候補の夜の順位 (順位, 種類, スコア)(ranks())。無ければ、その夜の中の順位 night_rank(新しい出力だけ)を順位の欄に使う。
    2 つは番号の意味が違う(夜をまたいだ通しの番号 / その夜の中の番号)ので、どちらかを details.rank_kind に書く(final・outlook / night)。
    night_rank の無い出力(1.2.0)では、今までと同じ(順位なし = null)。山の点数と比べられる形にはしない(score は rank のスコアだけ)。"""
    d = night["night_date"]
    if s["clear_start"] and s["clear_end"]:
        tw = {"start": s["clear_start"], "end": s["clear_end"], "kind": "clear_window"}
    else:
        tw = {"start": s["window_start"], "end": s["window_end"]}      # 種類の語が契約に無いので付けない
    score = None
    if rank and rank[2] is not None:
        score = {"value": rank[2], "scale": SCALE[rank[1]], "go_threshold": None}
    ev = [_ev("clear_hours", s["clear_hours"], "h", d), _ev("mean_obstruction", s["mean_obstruction"], "%", d),
          _ev("forecast_regime", night["forecast_regime"], None, d),
          _ev("moon_free_hours", night["moon_free_hours"], "h", d, source_type="model_derived"),
          _ev("alr", s["alr"], None, d, SOURCE_STATIC, "static_reference"),
          _ev("alr_rank_pct", s["alr_rank_pct"], "%", d, SOURCE_STATIC, "static_reference"),
          _ev("rank", rank[0] if rank else s.get("night_rank"), None, d, source_type="model_derived")]
    cons = []
    if site["requires_lift_access"]:
        cons.append({"kind": "access", "text": "リフト要の地点(運行は確かめていない)", "hard": False})
    limits = list(KNOWN_LIMITS)
    if night["forecast_regime"] == "ECMWF":
        limits.append("forecast_regime が ECMWF の夜の雲量は目安")
    return {"id": f"{AGENT}:{mode}:{d}:{s['site_id']}", "title": f"{site['label']} {d} の夜",
            "place": {"name": site["label"], "lat": site["lat"], "lon": site["lon"], "elevation_m": None, "region": site["municipality"],
                      "location_precision": "exact", "site_ref": f"{AGENT}:{s['site_id']}"},
            "time_window": tw,
            "suitability": {"band": "go" if night["forecast_regime"] == "MSM" else "maybe", "score": score},
            "evidence": ev, "constraints": cons,
            "uncertainty": {"lead_days": lead, "reliable_up_to_days": RELIABLE_UP_TO_DAYS,
                            "confidence": {"value": None, "scale": None, "method": "none", "validated": False}, "known_limits": limits},
            "native_ref": {"format": SCHEMA_IN, "path": NATIVE_PATH[mode]},
            "details": {"mode": mode, "night_date": d, "site_id": s["site_id"], "group": s["group"],
                        "rank_kind": rank[1] if rank else ("night" if s.get("night_rank") is not None else None),
                        "window_start": s["window_start"], "window_end": s["window_end"]}}


def convert(natives, *, now, fetched_at, agent_version, agent_commit, model_runs=None, request_id="shelf"):
    """2 つのモードの出力 {mode: native} → biyori-proposal/1。1 件は「モード・地点・夜」。
    入れるのは、月の無い時間帯で調べた夜(window_kind = moon_free)に条件を通った(status = passed)地点だけ。site_id の無い地点は入れない。"""
    if now.tzinfo is None or fetched_at.tzinfo is None:
        raise ValueError("now・fetched_at にオフセットが必要")
    today = now.astimezone(JST).date()
    warnings, proposals = ["確信度は出力されないため null", "標高は出力に無いため null"], []
    partial = []
    for mode in MODES:
        native = natives[mode]
        sites = {x["site_id"]: x for x in native["site_index"] if x["site_id"] is not None}
        rk = ranks(native)
        no_id = no_window = moon = 0
        for night in native.get("requested_nights") or []:
            passed = [s for s in night["sites"] if s["status"] == "passed"]
            if night["window_kind"] != "moon_free":
                moon += len(passed)
                continue
            lead = (date.fromisoformat(night["night_date"]) - today).days
            for s in passed:
                if s["site_id"] is None or s["site_id"] not in sites:
                    no_id += 1
                elif not ((s["clear_start"] and s["clear_end"]) or (s["window_start"] and s["window_end"])):
                    no_window += 1
                else:
                    proposals.append(_proposal(mode, night, s, sites[s["site_id"]], rk.get((night["night_date"], s["site_id"])), lead))
        if moon:
            warnings.append(f"{mode}: 月の無い時間帯で調べていない夜(暗い時間帯ぜんぶで調べた夜)の地点 {moon} 件は提案にしない")
        if no_id:
            warnings.append(f"{mode}: site_id の無い地点 {no_id} 件は提案にしない(名前だけで突き合わせない)")
        if no_window:
            warnings.append(f"{mode}: 時間帯の無い地点 {no_window} 件は提案にしない")
        if native["fetch"]["status"] == "partial":
            partial.append(mode)
            warnings.append(f"{mode}: 取得できなかったセル {native['fetch']['failed_cells']}/{native['fetch']['total_cells']}")
    data_as_of = [{"source": "Open-Meteo (hoshibiyori)", "source_type": "forecast", "run_time": None, "fetched_at": iso(fetched_at)}]
    for model, r in (model_runs or {}).items():
        data_as_of.append({"source": f"Open-Meteo {model}", "source_type": "forecast", "run_time": (r or {}).get("init"), "fetched_at": iso(fetched_at)})
    out = {"schema": "biyori-proposal/1", "request_id": request_id,
           "agent": {"id": AGENT, "version": agent_version or "unknown", "commit": agent_commit},
           "status": "partial" if partial else "ok", "generated_at": iso(now), "data_as_of": data_as_of, "proposals": proposals,
           "diagnostics": {"api_calls": None, "cache_hit": None, "runtime_s": None, "fetch_finished_at": iso(fetched_at), "warnings": warnings},
           "details": {"modes": {m: {"generated_at": natives[m]["generated_at"], "finals": len(natives[m]["finals"]),
                                     "outlooks": len(natives[m]["outlooks"])} for m in MODES}, "model_runs": model_runs or {}}}
    if partial:
        out["status_reason"] = "fetch_incomplete"
    return out
