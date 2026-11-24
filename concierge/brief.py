"""brief: 質問のための資料(biyori-brief/1)を作る。決定論(同じ棚・同じ引数・同じ --now なら 1 バイトも変わらない)。

- 質問の文は解釈しない(そのまま残すだけ)。いつ・どこ・興味・名指しの山は、エージェントが引数で渡す。
- 候補の選び方は機械的(価値の判断はしない): 対象の日・直線 250km 以内・地域で絞り、日ごとに 2 つの枠で選ぶ。
  主役の枠 = 主役にできる山だけを、点数 → 危険信号の軽さ → 直線距離 → 山の ID の順に上位 brief.top_per_day 件。
  見送りの枠 = 基準点以上で危険信号が「警戒」「危険」の山を、危険の段階の重さ → 点数 → 直線距離 → 山の ID の順に上位 brief.skip_per_day 件。
  名指しの山は枠と別に必ず入れる。
- 答えに書いてよい事実を 1 件ずつ id つき(Y001〜・C1〜・N1〜・L1〜・K001〜・G1〜)で持ち、書いてよい表記(say)を付ける。
  丸めた表記はここで作ったものだけ(AI に丸めさせない)。
- 予報の値の名前と単位は docs/brief-fields.md の表のとおり(ヤマビヨリの README と画面の列名が出典)。"""
import hashlib
import json
import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

from collect.common import SCHEMAS
from collect.yamabiyori import GO_THRESHOLD, HAZARD_HARD, RELIABLE_UP_TO_DAYS

from . import dates as D
from . import shelf as S
from .common import DATA, JST, WEEKDAY_JA, brief_schema_errors, config, dump_json, iso, md_label, parse_iso, read_json, write_text
from .texts import coverage_counts, data_time_label, runs_text

SCHEMA = "biyori-brief/1"
HAZARD_ORDER = ("thunder", "wind", "cold")
HAZARD_JA = {"thunder": "雷", "wind": "強風", "cold": "低体温症"}
LEVEL_RANK = {"注意": 1, "警戒": 2, "警戒以上": 2, "危険": 3}
# 予報の値(棚の提案の evidence[].metric)→ 名前と単位。出典は docs/brief-fields.md。名前の出典のない値は出さない。
VALUE_FIELDS = (
    # metric, 名前, 単位(答えに書く形), 丸めの刻み(約の表記), 出典の場所(短く)
    ("ridge_wind_ms", "稜線風速", "m/s", 1, "mountain_weather_mvp.py 表の列「稜線風速m/s」・README 探索モードの表"),
    ("day_peak_wind_ms", "日中ピークの風速", "m/s", 1, "README「スコアの仕組み」危険信号「稜線の強風(日中ピーク)」"),
    ("cloud_pct", "雲量", "%", 1, "README 探索モード「雲量%(較正/生)」の左「採点に使う較正後の実効雲量」"),
    ("ridge_visibility", "視程(稜線)", "m", None, "mountain_weather_mvp.py 表の列「視程m(稜線)」"),
    ("precip_wet_pct", "雨天割合(活動時間)", "%", 1, "mountain_weather_mvp.py 表の列「雨天割合%(活動時間)」"),
    ("day_total_precip_mm", "降水量(全日)", "mm", 1, "mountain_weather_mvp.py 表の列「降水量mm(全日)」"),
    ("chill", "体感温度(稜線)", "℃", 1, "mountain_weather_mvp.py 表の列「体感温度℃(稜線)」"),
)
LINE_KEYS = ("data_time", "coverage", "lead_time", "attribution", "hazard_note")      # 決まった文の並び(id の順)。危険信号の文はこのあと
UNIT_OUT = {"degC": "℃"}
# 資料に出さない値。cloud_pct_raw・cape は、答えに出さないと利用者が決めた(2026-11-23。docs/brief-fields.md)
NOT_SHOWN = ("cloud_pct_raw", "cape", "precip_wet_hours", "precip_total_hours", "precip_msm_hours", "precip_moist_hours", "precip_prob_hours",
             "precip_total_mm", "day_peak_wind_hour")      # day_peak_wind_hour は日中ピークの風速の「時」として使う


def brief_dir(base):
    return Path(base) / "briefs"


def cards_dir():
    import os
    return Path(os.environ.get("BIYORI_CONCIERGE_CARDS_DIR") or (DATA / "cards"))


# ---- 数の表記 ----
def num(v):
    """12.80 → '12.8'、10.0 → '10'、-0.0 → '0'。"""
    d = Decimal(str(v)).normalize()
    s = format(d, "f")
    return "0" if s in ("-0", "") else s


def round_to(v, step):
    q = (Decimal(str(v)) / Decimal(step)).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal(step)
    return num(q)


def distance_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distance_say(km, c):
    """「直線で約○km」。10km 未満は 1km、それ以上は 5km の刻み(仮置き。config.yaml concierge.brief.distance)。"""
    dc = c["concierge"]["brief"]["distance"]
    step = dc["fine_step_km"] if km < dc["fine_below_km"] else dc["coarse_step_km"]
    r = round_to(km, step)
    if r == "0":
        r = num(step)
    return f"直線で約{r}km"


def day_says(d):
    wd = WEEKDAY_JA[d.weekday()]
    return [md_label(d), f"{d.month}月{d.day}日", f"{d.month}/{d.day}", f"{wd}曜", f"{wd}曜日", f"({wd})"]


# ---- 入力の解決 ----
def _vocab():
    return yaml.safe_load((SCHEMAS / "biyori-vocabulary.yaml").read_text(encoding="utf-8"))


def resolve_interests(words, c):
    """→ (正式な語のリスト, 山以外の語, 知らない語)。語は語彙の key か label。"""
    v = _vocab()["interests"]
    by_label = {x["label"]: k for k, x in v.items()}
    mountain = set(c["concierge"]["brief"]["mountain_interests"])
    ok, other, unknown = [], [], []
    for w in words or []:
        k = w if w in v else by_label.get(w)
        if k is None:
            unknown.append(w)
        elif k in mountain:
            ok.append(k)
        else:
            other.append(k)
    return ok, other, unknown


def resolve_origin(spec, c):
    o = c["origin"]["default"]
    if not spec or spec == o["name"]:
        return {"name": o["name"], "lat": o["lat"], "lon": o["lon"], "source": "config"}, None
    parts = [p.strip() for p in spec.replace("、", ",").split(",")]
    if len(parts) == 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return {"name": f"{num(lat)},{num(lon)}", "lat": lat, "lon": lon, "source": "argument"}, None
        except ValueError:
            pass
    return {"name": o["name"], "lat": o["lat"], "lon": o["lon"], "source": "config"}, spec


def _base_name(name):
    return name.split("(")[0].split("(")[0].strip()


def find_mountain(spec, mountains):
    s = (spec or "").strip()
    for m in mountains:
        if s == m["id"] or s == m["name"]:
            return m
    hits = [m for m in mountains if s and s in (_base_name(m["name"]), m["name"].split("(")[-1].rstrip(")"))]
    return hits[0] if len(hits) == 1 else None


# ---- 事実 ----
def _hazards(p):
    out = []
    for c in p.get("constraints") or []:
        if c.get("kind") != "hazard":
            continue
        if c.get("hazard") in HAZARD_JA:
            out.append({"kind": c["hazard"], "label": HAZARD_JA[c["hazard"]], "level": c.get("level")})
        elif c.get("level") in ("警戒以上", "注意"):              # 簡易行(70点未満): 種類は分からない
            out.append({"kind": None, "label": "危険信号", "level": c["level"]})
    out.sort(key=lambda h: (HAZARD_ORDER.index(h["kind"]) if h["kind"] in HAZARD_ORDER else 9))
    return out


def _values(p):
    ev = {e.get("metric"): e for e in p.get("evidence") or []}
    out = []
    for metric, name, unit, step, _src in VALUE_FIELDS:
        e = ev.get(metric)
        if not e or not isinstance(e.get("value"), (int, float)) or isinstance(e.get("value"), bool):
            continue
        v = e["value"]
        say = [f"{num(v)} {unit}"]
        if metric == "ridge_visibility":
            say.append(f"約{round_to(v / 1000, 1)} km")
        elif step:
            r = round_to(v, step)
            if r != num(v):
                say.append(f"約{r} {unit}")
        item = {"key": metric, "name": name, "value": v, "unit": unit, "say": say}
        if metric == "day_peak_wind_ms" and isinstance((ev.get("day_peak_wind_hour") or {}).get("value"), int):
            h = ev["day_peak_wind_hour"]["value"]
            item["hour"] = h
            item["say"] = list(dict.fromkeys(item["say"] + [f"{h}時", f"{h:02d}時"]))
        out.append(item)
    return out


HAZARD_NOTE = "危険信号は、点数とは別に出る警告です。"      # 山ごとの危険信号の文には付けず、答えに 1 回入れる(verify が置く)


def _hazard_line(f):
    vals = {v["key"]: v for v in f["values"]}
    parts = []
    for h in f["hazards"]:
        if h["kind"] is None:
            continue
        if h["kind"] == "wind" and "day_peak_wind_ms" in vals:
            hr = vals["day_peak_wind_ms"].get("hour")
            parts.append(f"強風{h['level']}({str(hr) + '時に' if hr is not None else ''}{num(vals['day_peak_wind_ms']['value'])} m/s)")
        elif h["kind"] == "cold" and "chill" in vals:
            parts.append(f"低体温症{h['level']}(体感 {num(vals['chill']['value'])}℃)")
        else:
            parts.append(f"{h['label']}{h['level']}")
    head = f"{f['label']}の{f['name']}は"
    if parts:
        return f"{head}、危険信号が出ています: {'・'.join(parts)}。"
    lv = f["hazards"][0]["level"]
    return f"{head}、危険信号({lv}。種類は今回の予報に含まれていません)が出ています。"


def _skip_line(frame):
    """見送りの枠の山(1 日ぶん。枠の並びのまま)→ まとめの文。危険信号の中身(種類と段階の組)が同じ山どうしをまとめる。数字は入れない。"""
    groups = {}
    for f in frame:
        key = "・".join(h["level"] if h["kind"] is None else f"{h['label']}{h['level']}" for h in f["hazards"])
        groups.setdefault(key, []).append(f["name"])
    return f"{frame[0]['label']}は、" + "、".join(f"{'・'.join(names)}に{hz}" for hz, names in groups.items()) + "の危険信号が出ています。"


def main_key(f):
    """主役の枠の並び: 点数の高い順 → 危険信号の軽い順(なし → 注意。同じ段階なら数の少ない順)→ 直線距離の近い順 → 山の ID の順。"""
    return (-f["score"], LEVEL_RANK.get(f["hazard_level"], 0), len(f["hazards"]), f["distance_km"], f["mountain_id"])


def skip_key(f):
    """見送りの枠の並び: 危険の段階の重い順(危険 → 警戒。山のいちばん重い段階で比べ、同じならその段階の危険信号の数の多い順)
    → 点数の高い順 → 直線距離の近い順 → 山の ID の順。控えの文の見送りの並びも同じ。"""
    worst = LEVEL_RANK.get(f["hazard_level"], 0)
    n = sum(1 for h in f["hazards"] if LEVEL_RANK.get(h["level"], 0) == worst)
    return (-worst, -n, -f["score"], f["distance_km"], f["mountain_id"])


def _fact(p, mtn, origin, data_day, c, *, named, selected_by=None):
    d = date.fromisoformat(p["time_window"]["start"][:10])
    sc = p["suitability"]["score"]
    km = distance_km(origin["lat"], origin["lon"], mtn["lat"], mtn["lon"])
    score_only = not p.get("evidence")
    hz = _hazards(p)
    worst = max((LEVEL_RANK.get(h["level"], 0) for h in hz), default=0)
    lead = (d - data_day).days if data_day else None
    ng = []
    if sc["value"] < GO_THRESHOLD:
        ng.append("below_threshold")
    if any(h["level"] in HAZARD_HARD or h["level"] == "警戒以上" for h in hz):
        ng.append("hazard_hard")
    if score_only and "below_threshold" not in ng:
        ng.append("score_only")
    f = {"id": None, "kind": "mountain_day", "mountain_id": mtn["id"], "name": mtn["name"], "elevation_m": mtn["elevation_m"],
         "region": mtn.get("region"), "access": mtn.get("access"), "date": d.isoformat(), "weekday": WEEKDAY_JA[d.weekday()],
         "label": md_label(d), "score": sc["value"], "threshold": GO_THRESHOLD,
         "rank": None, "rank_ties": None,
         "detail_level": "score_only" if score_only else "full", "hazards": hz,
         "hazard_level": {0: None, 1: "注意", 2: "警戒", 3: "危険"}[worst], "main_ok": not ng, "main_ng": ng,
         "distance_km": round(km, 1), "distance_say": distance_say(km, c), "lead_days": lead,
         "reliable": lead is not None and lead <= RELIABLE_UP_TO_DAYS, "named": named, "selected_by": selected_by,
         "values": [] if score_only else _values(p)}
    say = [mtn["name"], f"{num(sc['value'])}点", f"基準の{num(GO_THRESHOLD)}点", f"{num(GO_THRESHOLD)}点",
           f"標高{num(mtn['elevation_m'])}m", f"{num(mtn['elevation_m'])}m", f["distance_say"], f["distance_say"].replace("直線で", "")]
    r = round_to(sc["value"], 1)
    if r != num(sc["value"]):
        say.append(f"約{r}点")
    if _base_name(mtn["name"]) != mtn["name"]:
        say.append(_base_name(mtn["name"]))
    if lead is not None:
        say.append(f"{lead}日先")
    say += day_says(d)
    for h in hz:
        say += [f"{h['label']}{h['level']}", f"{h['label']}:{h['level']}", f"{h['label']}の{h['level']}"]
    for v in f["values"]:
        say += v["say"]
    f["say"] = list(dict.fromkeys(say))
    return f


def rank_say(f):
    """その日の順位の書いてよい表記。同点があるときは、同点があると分かる形だけ。"""
    if not f["rank"]:
        return []
    if f["rank_ties"] > 1:
        return [f"{f['rank']}位(同点 {f['rank_ties']} 座)"]
    return [f"{f['rank']}位", f"{f['rank']}番目"]


def _set_ranks(above):
    """基準点以上の山(その日の全部)に、その日の順位 rank(同点は同じ順位)と、その順位の山の数 rank_ties を付け、main_key の順に並べる。"""
    above.sort(key=main_key)
    for f in above:
        f["rank"] = 1 + sum(1 for g in above if g["score"] > f["score"])
        f["rank_ties"] = sum(1 for g in above if g["score"] == f["score"])
        f["say"] = list(dict.fromkeys(f["say"] + rank_say(f)))


def _comparisons(facts, origin):
    """日ごとに、主役の枠の山の中で「比べた結果」の事実を作る(稜線の風がいちばん弱い山・出発地からいちばん近い山だけ。仮置き)。
    枠の山が 2 座に満たない日、値のない山がある日、いちばんの山が 2 つ以上ある日は作らない(言い切れないため)。"""
    out = []
    for d in sorted({f["date"] for f in facts}):
        frame = [f for f in facts if f["date"] == d and f["selected_by"] == "top"]
        if len(frame) < 2:
            continue
        winds = {f["id"]: next((v["value"] for v in f["values"] if v["key"] == "ridge_wind_ms"), None) for f in frame}
        near = {f["id"]: f["distance_km"] for f in frame}
        kinds = (("ridge_wind_min", winds, ["おすすめの候補の中で稜線の風がいちばん弱い"]),
                 ("nearest", near, [f"おすすめの候補の中で{origin['name']}からいちばん近い", "おすすめの候補の中で出発地からいちばん近い"]))
        for kind, vals, say in kinds:
            if any(v is None for v in vals.values()):
                continue
            best = [f for f in frame if vals[f["id"]] == min(vals.values())]
            if len(best) != 1:
                continue
            f = best[0]
            out.append({"id": f"C{len(out) + 1}", "kind": kind, "date": d, "label": f["label"], "fact": f["id"],
                        "mountain_id": f["mountain_id"], "name": f["name"], "among": [x["id"] for x in frame], "say": say})
    return out


def _named_gaps(facts, c, start):
    """日ごとに、名指しの山の組(2 座ずつ)の、日中ピークの風速の差の事実を作る。値のない山がある組は作らない。
    差が config.yaml の small_wind_diff_ms(仮の値)以下の組だけ「差はわずか」と書いてよい。"""
    limit = Decimal(str(c["concierge"]["brief"]["small_wind_diff_ms"]))
    out = []
    for d in sorted({f["date"] for f in facts if f["named"]}):
        fs = [f for f in facts if f["date"] == d and f["named"]]
        winds = [(f, next((v["value"] for v in f["values"] if v["key"] == "day_peak_wind_ms"), None)) for f in fs]
        winds = [(f, v) for f, v in winds if v is not None]
        for i, (a, va) in enumerate(winds):
            for b, vb in winds[i + 1:]:
                diff = abs(Decimal(str(va)) - Decimal(str(vb)))
                small = diff <= limit
                wind_level = {x["kind"]: x["level"] for x in a["hazards"]}.get("wind"), {x["kind"]: x["level"] for x in b["hazards"]}.get("wind")
                out.append({"id": f"C{start + len(out) + 1}", "kind": "peak_wind_gap", "date": d, "label": a["label"], "fact": a["id"],
                            "mountain_id": a["mountain_id"], "mountains": [a["mountain_id"], b["mountain_id"]],
                            "name": f"{a['name']}・{b['name']}", "among": [a["id"], b["id"]], "diff": float(diff), "small": small,
                            "hazard_differs": wind_level[0] != wind_level[1],
                            "say": [f"日中ピークの風速の差は {num(diff)} m/s"] + (["差はわずか"] if small else [])})
    return out


def _hazard_count(d, above, skip_frame):
    """その日の、基準点以上で危険信号が「警戒」「危険」の山の件数(山のいちばん重い段階で数える)。見送りの枠の山も枠の外の山も数えた全体 all と、枠の外だけの outside。
    書いてよい言い方は全体の件数だけ(枠の外の件数は書き手が見るだけ。答えに挙げた山の数は枠の数と同じとは限らないため)。"""
    def count(fs):
        w = sum(1 for f in fs if f["hazard_level"] == "警戒")
        g = sum(1 for f in fs if f["hazard_level"] == "危険")
        return {"total": w + g, "warning": w, "danger": g}
    hard = [f for f in above if "hazard_hard" in f["main_ng"]]
    inside = {f["mountain_id"] for f in skip_frame}
    a, out = count(hard), count([f for f in hard if f["mountain_id"] not in inside])
    return {"id": None, "kind": "hazard_count", "date": d.isoformat(), "label": md_label(d), "weekday": WEEKDAY_JA[d.weekday()],
            "above": len(above), "all": a, "outside": out,
            "say": [f"危険信号が警戒以上の山は {a['total']} 座", f"このうち危険は {a['danger']} 座", f"危険信号が危険の山は {a['danger']} 座",
                    f"危険信号が警戒の山は {a['warning']} 座", f"基準の{num(GO_THRESHOLD)}点以上の山は {len(above)} 座"]}


def _load_cards(fact_mids):
    out = []
    d = cards_dir()
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.yaml")):
        try:
            k = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(k, dict) or not all(k.get(x) for x in ("id", "targets", "text", "source", "checked")):
            continue
        mids = set((k.get("targets") or {}).get("mountains") or [])
        if mids & fact_mids:
            out.append({"card_id": str(k["id"]), "mountains": sorted(mids & fact_mids), "kinds": (k["targets"].get("kinds") or []),
                        "text": str(k["text"]).strip(), "source": {"name": k["source"].get("name"), "url": k["source"].get("url")},
                        "checked": str(k["checked"]), "say": [str(x) for x in (k.get("say") or [])]})
    out.sort(key=lambda x: x["card_id"])
    return out


RULES = [
    "答えの形: 結論(1〜2文)→ いつ時点の予報か([L…] をそのまま)→ おすすめ(行くなら)3 つまで(理由は数字で。注意)→ 見送る山(まとめの文と件数)→ 危険信号の注記 → 分からないこと → 出典([L…] をそのまま)。見送りを聞かれたら、見送る山を先に、「行くなら」をあとに書く。",
    "数字・日付・曜日・山の名前・危険信号を書いた文の終わりに、根拠の事実の印 [Y…] を付ける。書いてよい表記は事実の「書いてよい表記」だけ(自分で丸めない)。",
    "決まった文 [L…] は一字一句そのまま写し、終わりに印を付ける。",
    "天気の語(晴れ・雲・風・雨・雪・霧・見通し など)を書く文には、必ず事実の印を付ける。",
    "山の難しさ・装備・積雪や凍結・ルート・所要時間は書かない。聞かれたら「足りないもの」[G…] を使って、「この予報からは判断できません」の形で書く([G…] の印だけでは通らない)。",
    "「いちばん」「最も」などで風・距離・点数を比べる文は、比べた結果 [C…] か、順位が 1 位の事実だけで書く。[C…] は「候補の中で」と書き、その山の事実の印 [Y…] も付ける。ほかの比べ方はしない(数字だけを書く)。",
    "「どれも」「全部」「すべて」「どの山も」と危険信号を 1 文に書かない(山の名前を並べて「A・B・C は、どれも強風危険」と書くのは、並べた山の全部に印を付け、全部に本当に当てはまるときだけよい)。日ごとの件数は、危険信号の件数 [N…] の「書いてよい言い方」で書く(資料に載っている山は枠の中だけなので、全部のことは件数でしか言えない)。",
    "「ほとんど」「大半」「半分以上」「多くの山」「ほかの山も」「高い山ほど」などの割合・ぼかした言い方と危険信号を 1 文に書かない。件数の文を写す。",
    "見送る山の危険信号は、日ごとの「見送りのまとめ」の決まった文を写して書く(続けて、件数の文)。山ごとの危険信号の文は、風速・体感の数字を書きたい山だけ。おすすめにした山の危険信号の文は、まとめの文があっても必ず要る。",
    "危険信号の注記の決まった文は、verify が正しい位置(最後の危険信号の文・件数の文のあと。足りないものの文の前)に 1 回だけ置く。下書きに書かなくてよい(書いても 1 回に直る)。",
    "名指しの山どうしの差(資料の「名指しの山どうしの差」[C…])に「差はわずか」とあるときは、危険信号の有無が分かれていても「差はわずかです」と書ける(その [C…] と両方の山の [Y…] の印を付ける)。「差はわずか」は、この印があるときだけ書く。",
    "2 座以上を名指しで比べる答えでは、番号を付けるなら並べる山の全部に付ける(1 座だけに「1.」「①」を付けない)。",
    "同点のある順位は「1位(同点 5 座)」のように、同点があると分かる形で書く。",
    "おすすめは事実の「主役にできる」山だけ。危険信号のある山をすすめるときは、その危険信号の決まった文を必ず入れる。",
    "最後の行に [おすすめ] と、すすめた事実の id(なければ「なし」)を書く。",
    "質問・提案(「〜しますか」「〜しましょうか」「?」)、内部の言葉、作業の説明、英語のメモを書かない。宿や山小屋の名前を書かない。",
]


def build(*, question, when, region=None, interest=None, origin=None, mountains=None, now, base):
    """→ 資料の dict(id つき)。"""
    c = config()
    bc = c["concierge"]["brief"]
    W = D.resolve(when, now.astimezone(JST).date())
    target = [date.fromisoformat(x["date"]) for x in W["days"]]
    org, origin_unknown = resolve_origin(origin, c)
    ints, other_ints, unknown_ints = resolve_interests(interest, c)
    sh = S.load(base)
    gaps, lines, facts = [], {}, []
    excluded, counts_ = [], []
    max_km = c["origin"]["max_straight_line_km"]

    def gap(kind, text, say=()):
        gaps.append({"id": None, "kind": kind, "text": text, "say": list(say)})

    shelf_info = {"available": sh["ok"], "problem": sh["problem"]}
    named_specs = list(dict.fromkeys(mountains or []))
    region_specs = list(dict.fromkeys(region or []))
    if sh["ok"]:
        e, m = sh["entry"], sh["manifest"]
        mlist = sh["mountains"]["mountains"]
        by_id = {x["id"]: x for x in mlist}
        regions = sorted({x["region"] for x in mlist if x.get("region")})
        regions_ok = [r for r in region_specs if r in regions]
        for r in region_specs:
            if r not in regions:
                gap("unknown_region", f"「{r}」という地域は、山の予報の地域({'・'.join(regions)})にありません。")
        dt = parse_iso(e.get("data_time"))
        data_day = dt.astimezone(JST).date() if dt else None
        age = S.age_hours(e, now)
        stale_h = c["collect"]["stale_after_hours"]
        stale = age is not None and age >= stale_h
        shelf_info.update(data_time=e.get("data_time"), status=e.get("status"), version=e.get("version"),
                          coverage=e.get("coverage"), model_runs=e.get("model_runs"), age_hours=age, stale=stale)
        lab = data_time_label(e)
        if stale:
            lines["data_time"] = (f"山の予報は {lab} 時点のもので、{int(age)} 時間前の古い予報です"
                                  f"({runs_text(e.get('model_runs'))})。")
        else:
            lines["data_time"] = f"山の予報は {lab} 時点のものです({runs_text(e.get('model_runs'))})。"
        if e.get("status") == "kept_previous":
            lines["data_time"] += "最新の取得がうまくいかなかったため、前の回の予報を使っています。"
        total, pool, fetched = coverage_counts(e)
        if e.get("status") == "incomplete" or (pool is not None and fetched is not None and fetched < pool):
            lines["coverage"] = f"山は、ヤマビヨリの {total} 座のうち {fetched} 座だけを調べた予報です(調べられなかった山があります)。"
        elif fetched is not None and fetched == total and len({s for s in named_specs}) >= 2:      # 山を名指しで比べる質問で、全部そろっているとき(短く)
            lines["coverage"] = f"ヤマビヨリの {total} 座すべての予報がそろっています。"
        else:
            lines["coverage"] = f"山は、ヤマビヨリの {total} 座のうち {fetched} 座を調べた予報です。"
        lines["attribution"] = (f"気象データ: Weather data by Open-Meteo.com(CC BY 4.0)。元の予報は気象庁 MSM と ECMWF IFS で、"
                                f"ヤマビヨリ {e.get('version')} が山頂の標高に合わせて計算した値です。")
        props = sh["proposals"]["proposals"]
        by_day = {}
        for p in props:
            mid = ((p.get("place") or {}).get("site_ref") or "").replace("yamabiyori:", "")
            if mid not in by_id or not (p.get("suitability") or {}).get("score"):
                continue
            by_day.setdefault(p["time_window"]["start"][:10], {})[mid] = p
        # 名指しの山
        named = []
        for spec in named_specs:
            mt = find_mountain(spec, mlist)
            if mt is None:
                gap("named_not_in_list", f"「{spec}」は、ヤマビヨリの {len(mlist)} 座に入っていないため、山の予報がありません。",
                    [f"{len(mlist)}座"])
                continue
            km = distance_km(org["lat"], org["lon"], mt["lat"], mt["lon"])
            if km > max_km:
                gap("named_out_of_range", f"{mt['name']}は、出発地({org['name']})から直線 {max_km}km より遠いため、候補に入れていません。",
                    [f"{max_km}km", mt["name"]])
                continue
            named.append(mt["id"])
        no_day = []
        for d in target:
            ds = d.isoformat()
            dayp = by_day.get(ds)
            if not dayp:
                no_day.append(d)
                continue
            ex = {"out_of_range": 0, "region": 0, "no_forecast": 0, "below_threshold": 0, "score_only": 0,
                  "outside_top": 0, "outside_skip": 0}
            pool_ = []
            for mt in mlist:
                p = dayp.get(mt["id"])
                if p is None:
                    ex["no_forecast"] += 1
                    continue
                if distance_km(org["lat"], org["lon"], mt["lat"], mt["lon"]) > max_km:
                    ex["out_of_range"] += 1
                    continue
                if regions_ok and mt.get("region") not in regions_ok:
                    ex["region"] += 1
                    continue
                pool_.append((mt, p))
            all_facts = [_fact(p, mt, org, data_day, c, named=mt["id"] in named) for mt, p in pool_]
            above = [f for f in all_facts if f["score"] >= GO_THRESHOLD]
            _set_ranks(above)                                                   # main_key の順に並ぶ
            ex["below_threshold"] = len(pool_) - len(above)
            mains_ = [f for f in above if f["main_ok"]]
            hard = sorted([f for f in above if "hazard_hard" in f["main_ng"]], key=skip_key)
            ex["score_only"] = len(above) - len(mains_) - len(hard)
            top, skip = mains_[:bc["top_per_day"]], hard[:bc["skip_per_day"]]
            for f in top:
                f["selected_by"] = "top"
            for f in skip:
                f["selected_by"] = "skip"
            if above:
                counts_.append(_hazard_count(d, above, skip))
            day_facts = top + skip
            out_top, out_skip = mains_[len(top):], hard[len(skip):]
            ex["outside_top"], ex["outside_skip"] = len(out_top), len(out_skip)
            by_mid = {f["mountain_id"]: f for f in all_facts}
            picked = {f["mountain_id"] for f in day_facts}
            for mid in named:
                if mid in picked:
                    continue
                p = dayp.get(mid)
                if p is None:
                    gap("named_no_forecast", f"{md_label(d)}の{by_id[mid]['name']}の予報はありません。", day_says(d)[:1] + [by_id[mid]["name"]])
                    continue
                f = by_mid.get(mid) or _fact(p, by_id[mid], org, data_day, c, named=True)      # 地域の外の名指しの山は順位なし
                f["selected_by"] = "named"
                day_facts.append(f)
            facts += day_facts
            if not above:
                gap("no_mountain_above", f"{md_label(d)}は、基準の {num(GO_THRESHOLD)} 点以上の山がありませんでした。",
                    [md_label(d), f"{num(GO_THRESHOLD)}点"])
            excluded.append({"date": ds, "counts": ex,
                             "outside_top_names": [f["name"] for f in out_top if f["mountain_id"] not in named],
                             "outside_skip_names": [f["name"] for f in out_skip if f["mountain_id"] not in named]})
        if no_day:
            labs = "・".join(md_label(d) for d in no_day)
            gap("day_not_in_forecast", f"{labs}の山の予報は、今回の予報の範囲にありません。", [md_label(d) for d in no_day])
        far = sorted({f["date"] for f in facts if f["lead_days"] is not None and f["lead_days"] > RELIABLE_UP_TO_DAYS})
        if far:
            parts = "、".join(f"{md_label(date.fromisoformat(x))}は {(date.fromisoformat(x) - data_day).days} 日先" for x in far)
            lines["lead_time"] = (f"{parts}の予報です。ヤマビヨリが山頂の値として信用してよいとしているのは "
                                  f"{RELIABLE_UP_TO_DAYS} 日先までなので、傾向として読んでください。")
    else:
        gap("shelf_unavailable", "山の予報は今回使えませんでした。")
        for spec in named_specs:
            gap("named_no_forecast", f"「{spec}」の山の予報は今回使えませんでした。")
    if origin_unknown:
        gap("unknown_origin", f"出発地「{origin_unknown}」の場所が分からないため、{org['name']}からの直線距離で答えます。", [org["name"]])
    gap("no_safety_info", "山の難しさ・必要な装備・積雪や凍結・ルートの状態・所要時間は、この予報からは判断できません。")
    if other_ints:
        v = _vocab()["interests"]
        gap("interest_not_mountain", f"「{'・'.join(v[k]['label'] for k in other_ints)}」の情報はまだ使えないため、今回は山の予報だけで答えます。")
    for w in unknown_ints:
        gap("unknown_interest", f"「{w}」に合わせて山を選ぶ情報はありません。")
    gap("no_stars_creatures", "星空と、花・紅葉・野鳥の情報は、まだ使えません。")

    # id を振る
    for i, f in enumerate(facts, 1):
        f["id"] = f"Y{i:03d}"
    for i, g in enumerate(gaps, 1):
        g["id"] = f"G{i}"
    for i, n in enumerate(counts_, 1):
        n["id"] = f"N{i}"
    cards = _load_cards({f["mountain_id"] for f in facts})
    for i, k in enumerate(cards, 1):
        k["id"] = f"K{i:03d}"
    comparisons = _comparisons(facts, org)
    named_gaps = _named_gaps(facts, c, len(comparisons))
    L = []
    if any(f["hazards"] for f in facts):
        lines["hazard_note"] = HAZARD_NOTE
    for key in LINE_KEYS:
        if key in lines:
            L.append({"key": key, "fact": None, "text": lines[key]})
    for f in facts:
        if f["hazards"]:
            L.append({"key": "hazards", "fact": f["id"], "text": _hazard_line(f)})
    for ds in sorted({f["date"] for f in facts}):                  # 見送りのまとめの文(日ごとに 1 つ。番号は山ごとの文のあと)
        frame = [f for f in facts if f["date"] == ds and f["selected_by"] == "skip"]
        if frame:
            L.append({"key": "skips", "fact": None, "text": _skip_line(frame), "date": ds, "facts": [f["id"] for f in frame]})
    for i, l_ in enumerate(L, 1):
        l_["id"] = f"L{i}"
    lines_out = {key: None for key in LINE_KEYS} | {"hazards": [], "skips": []}
    for l_ in L:
        item = {"id": l_["id"], "text": l_["text"]} | ({"fact": l_["fact"]} if l_["fact"] else {})
        if l_["key"] == "hazards":
            lines_out["hazards"].append(item)
        elif l_["key"] == "skips":
            lines_out["skips"].append(item | {"date": l_["date"], "facts": l_["facts"]})
        else:
            lines_out[l_["key"]] = item
    mains = sorted([f for f in facts if f["main_ok"]], key=lambda f: (f["date"], main_key(f)))
    plans = [{"id": f"P{i}", "date": f["date"], "main": {"kind": "mountain", "fact": f["id"]}, "adds": []}
             for i, f in enumerate(mains, 1)]
    doc = {"schema": SCHEMA, "id": None, "question": question, "now": iso(now),
           "when": {"spec": W["spec"], "rule": W["rule"], "days": W["days"], "today": W["today"]},
           "origin": {"name": org["name"], "lat": org["lat"], "lon": org["lon"], "source": org["source"]},
           "filters": {"region": region_specs, "interest": list(interest or []), "interest_resolved": ints, "mountains": named_specs},
           "shelf": shelf_info, "facts": facts, "comparisons": comparisons, "named_gaps": named_gaps, "hazard_counts": counts_, "candidates": excluded, "lines": lines_out, "plans": plans,
           "cards": cards, "gaps": gaps, "rules": RULES,
           "mountain_index": [{"id": m["id"], "name": m["name"]} for m in (sh["mountains"] or {}).get("mountains", [])] if sh["ok"] else [],
           "limits": {"max_chars": c["answer"]["max_chars"], "reliable_up_to_days": RELIABLE_UP_TO_DAYS,
                      "top_per_day": bc["top_per_day"], "skip_per_day": bc["skip_per_day"], "max_straight_line_km": max_km}}
    h = hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    doc["id"] = f"b{now.astimezone(JST).strftime('%Y%m%d-%H%M%S')}-{h}"
    errs = brief_schema_errors(doc)
    if errs:
        raise RuntimeError("資料がスキーマに合わない(コードの不具合): " + "; ".join(errs[:5]))
    return doc


def save(doc, base):
    d = brief_dir(base)
    jp = write_text(d / f"{doc['id']}.json", dump_json(doc))
    mp = write_text(d / f"{doc['id']}.md", render_md(doc))
    st = d / f"{doc['id']}.verify.json"          # 同じ資料を作り直したら、書き直しの回数を数え直す
    if st.exists():
        st.unlink()
    return jp, mp


def is_current(doc):
    """今のコードで照らせる資料か。順位の意味を変える前(2026-11-23 まで。day_rank がある)の資料は、rank を読み違えるので使わない。"""
    return isinstance(doc, dict) and doc.get("schema") == SCHEMA and "hazard_counts" in doc and all("rank_ties" in f and "day_rank" not in f for f in doc.get("facts") or [])


def load(bid, base):
    if not bid or "/" in bid or "\\" in bid or ".." in bid:
        return None
    return read_json(brief_dir(base) / f"{bid}.json")


# ---- 人が読む Markdown ----
def render_md(b):
    out = [f"# 資料 {b['id']}", "", "## 質問", "", f"> {b['question']}", "",
           f"- 今: {b['now']} / 対象の日: {'・'.join(d['label'] for d in b['when']['days'])}({b['when']['spec']})",
           f"- 出発地: {b['origin']['name']}(直線距離の基準)"]
    if b["filters"]["region"] or b["filters"]["interest"] or b["filters"]["mountains"]:
        out.append(f"- 絞り込み: 地域 {b['filters']['region'] or 'なし'} / 興味 {b['filters']['interest'] or 'なし'} / 名指しの山 {b['filters']['mountains'] or 'なし'}")
    out += ["", "## 決まった文(一字一句そのまま写し、印を付ける)", ""]
    L = b["lines"]
    for key in LINE_KEYS:
        if L[key]:
            out.append(f"- [{L[key]['id']}]" + ("(危険信号の注記。危険信号の文を 1 つでも写すと、verify が正しい位置に 1 回だけ置く。下書きに書かなくてよい)" if key == "hazard_note" else "") + f" {L[key]['text']}")
    for h in L["hazards"]:
        out.append(f"- [{h['id']}](危険信号・{h['fact']}) {h['text']}")
    for x in L.get("skips") or []:
        out.append(f"- [{x['id']}](見送りのまとめ・{'・'.join(x['facts'])}。見送る山はこの文を写し、山ごとの危険信号の文は並べない) {x['text']}")
    out += ["", "## 候補(日ごと)", "",
            "(書き手への注: 「雲量」は、ヤマビヨリが採点に使う実効雲量(較正後)の値。答えには「雲量」とだけ書く)", ""]
    for day in b["when"]["days"]:
        fs = [f for f in b["facts"] if f["date"] == day["date"]]
        out.append(f"### {day['label']}")
        out.append("")
        if not fs:
            out += ["(候補なし)", ""]
        for f in fs:
            tag = "主役にできる" if f["main_ok"] else "主役にできない(" + "・".join(
                {"below_threshold": "基準点未満", "hazard_hard": "危険信号が警戒以上", "score_only": "点数だけ"}[x] for x in f["main_ng"]) + ")"
            hz = "・".join(f"{h['label']}{h['level']}" for h in f["hazards"]) or "なし"
            out.append(f"- **[{f['id']}] {f['name']}**({f['region']}・標高 {num(f['elevation_m'])}m・{f['access']}・{f['distance_say']})"
                       f" {num(f['score'])} 点(基準 {num(f['threshold'])} 点){'・' + rank_say(f)[0] if f['rank'] else ''}"
                       f"・{f['lead_days']} 日先{'(信用してよい範囲の外)' if not f['reliable'] else ''}・{tag}"
                       + ("・名指し" if f["named"] else "") + ("・見送りの枠" if f["selected_by"] == "skip" else ""))
            out.append(f"  - 危険信号: {hz}")
            for v in f["values"]:
                out.append(f"  - {v['name']}: {v['say'][0]}" + (f"(約の表記: {'、'.join(v['say'][1:])})" if len(v["say"]) > 1 else ""))
            out.append(f"  - 書いてよい表記: {' / '.join(f['say'])}")
        out.append("")
    if b["candidates"]:
        out += ["### 外した山(理由ごとの件数)", ""]
        for x in b["candidates"]:
            c = x["counts"]
            out.append(f"- {x['date']}: 範囲外 {c['out_of_range']}・地域の外 {c['region']}・予報なし {c['no_forecast']}・基準点未満 "
                       f"{c['below_threshold']}・点数だけ {c['score_only']}・主役の枠の外 {c['outside_top']}・見送りの枠の外 {c['outside_skip']}")
            for key, ja in (("outside_top_names", "主役の枠の外"), ("outside_skip_names", "見送りの枠の外")):
                if x[key]:
                    out.append(f"  - {ja}: {'、'.join(x[key])}")
        out.append("")
    if b["hazard_counts"]:
        out += ["### 危険信号の件数(日ごと。基準点以上の山の全部。枠の外の山も数えた数)", ""]
        for x in b["hazard_counts"]:
            a, o = x["all"], x["outside"]
            out.append(f"- [{x['id']}] {x['label']}: 基準点以上 {x['above']} 座のうち、警戒以上 {a['total']} 座(警戒 {a['warning']}・危険 {a['danger']})。"
                       f"見送りの枠の外 {o['total']} 座(警戒 {o['warning']}・危険 {o['danger']}。書き手が見るだけ)")
            out.append(f"  - 書いてよい言い方: {' / '.join(x['say'])}")
        out.append("")
    if b["comparisons"]:
        out += ["### 比べた結果(主役の枠の山の中)", ""]
        for x in b["comparisons"]:
            out.append(f"- [{x['id']}] {x['label']}・{x['name']}({x['fact']}): {' / '.join(x['say'])}")
        out.append("")
    if b.get("named_gaps"):
        out += ["### 名指しの山どうしの差(日中ピークの風速)", ""]
        for x in b["named_gaps"]:
            note = "。危険信号の強風の段階は違う" if x["hazard_differs"] else ""
            out.append(f"- [{x['id']}] {x['label']}・{x['name']}({'・'.join(x['among'])}): {' / '.join(x['say'])}{note}")
        out.append("")
    out += ["## 組み合わせ(主役になれる案)", ""]
    out += [f"- {p['id']}: {p['date']} 主役 {p['main']['fact']}" for p in b["plans"]] or ["(なし。おすすめにできる山はありません)"]
    out += ["", "## 知識カード", ""]
    out += [f"- [{k['id']}] {k['text']}(出典: {k['source']['name']}、{k['checked']} 確認)" for k in b["cards"]] or ["(なし)"]
    out += ["", "## 足りないもの", ""]
    out += [f"- [{g['id']}] {g['text']}" for g in b["gaps"]]
    out += ["", "## 書くときの決まり", ""]
    out += [f"- {r}" for r in b["rules"]]
    out += [f"- 字数は {b['limits']['max_chars']} 字まで。"]
    return "\n".join(out) + "\n"
