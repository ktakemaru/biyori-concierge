"""星(ホシビヨリ)の事実と、一日の流れの案(段階 3 第 2 部)。決定論・通信なし。対応表は docs/hoshibiyori-mapping.md。

星の項目は「星の興味の語を渡された質問」で「星の棚が使える」ときだけ資料に入る(stars_wanted・load)。それ以外の資料は 1 バイトも変わらない。
- 星の事実 [S…] = 「地点と夜」。星の件数 [T…] = 夜ごとの状態と件数。山の印([Y…]・[N…]・[C…])とは別の字。
- 夜の日付は、夜の始まりの日(ホシビヨリの night_date)。「11月28日(土)の夜」と書く(利用者の決定 2026-11-25)。
- 夜の枠に書いてよいのは、晴れ間の時間帯・月の無い時間帯・どちらのモードか。どの星が見えるかは資料に無いので書かせない。"""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from collect.hoshibiyori import ranks

from . import shelf as S
from .common import JST, WEEKDAY_JA, md_label
from .texts import data_time_label, runs_text

# 星の質問とみなす興味の語(schemas/biyori-vocabulary.yaml の note が hoshibiyori の語)
INTERESTS = ("stars", "milky_way", "astrophotography")
REASON_JA = {"cloud_filter": "雲", "light_pollution_filter": "光害", "direction_filter": "方角"}      # ホシビヨリの画面の語
NOT_EXAMINED = "その夜の雲の予報は今回調べられていません。"
FRAMES = (("day_mountain", "朝〜日中(山)", "mountain"), ("day_nature", "日中(生き物)", "nature"), ("night_stars", "夜(星)", "stars"))
LINE_KEYS = ("star_data_time", "star_mode", "star_regime", "star_attribution")      # 決まった文の並び(山の文の番号のあとに続ける)
MODE_FEW = "天の川モードの候補が少ないため、"      # 天の川を聞かれたのに、星空・星座モードの結果で答えるとき
MODE_TEXT = {"stars": "星は、星空・星座モード(銀河中心の高度・地形を条件にしない)で調べた結果です。",
             "milkyway": "星は、天の川モード(対象は天の川銀河中心)で調べた結果です。"}


def wanted(interest_keys):
    return any(k in INTERESTS for k in interest_keys)


# ---------------------------------------------------------------- 表記
def night_label(d):
    return f"{md_label(d)}の夜"


def night_says(d):
    """書いてよい夜の表記: 「11月28日(土)の夜」「28日(土)の夜」。"""
    return [night_label(d), f"{d.day}日({WEEKDAY_JA[d.weekday()]})の夜"]


def clock(iso, night):
    """ISO の時刻 → 「18:40」「翌4:50」(夜の始まりの日の次の日なら「翌」。分より下は切り捨て = ホシビヨリの画面と同じ)。"""
    t = datetime.fromisoformat(iso).astimezone(JST)
    return f"{'翌' if t.date() > night else ''}{t.hour}:{t.minute:02d}"


def hours_say(h):
    """時間 → 書いてよい表記(0.1 刻み。ホシビヨリの画面の「N.N時間」と同じ刻み。丸めたら「約」を付ける)。"""
    d = Decimal(str(h))
    r = d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    s = format(r.normalize(), "f")
    return f"{s} 時間" if r == d else f"約{s} 時間"


def _hours_screen(h):
    """夜ごとの文の時間(画面の「10.9時間」と同じ 0.1 刻み)。"""
    return format(Decimal(str(h)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f")


# ---------------------------------------------------------------- 材料
def choose_mode(natives):
    """どちらのモードの結果を使うか → (モード, 理由)。ホシビヨリと同じ決まり(explore_hoshibiyori.py: 天の川モードの候補
    len(finals) + len(outlooks) が milkyway_few_results より少なければ、星空・星座モードをすすめる)。config.yaml concierge.stars.mode_rule(仮置き)。"""
    n = natives["milkyway"]
    total, few = len(n["finals"]) + len(n["outlooks"]), n["thresholds"]["milkyway_few_results"]
    return ("stars", "milkyway_few") if total < few else ("milkyway", "milkyway_enough")


def _site_fact(s, night, site, d, rank, origin, B, c):
    km = B.distance_km(origin["lat"], origin["lon"], site["lat"], site["lon"])
    ng = []
    if night["window_kind"] != "moon_free":
        ng.append("moon")
    if s["status"] != "passed":
        ng.append("not_examined" if s["status"] == "not_examined" else "not_passed")
    values = []
    for key, name, a, b in (("clear_window", "晴れ間の時間帯", s["clear_start"], s["clear_end"]),
                            ("moon_free_window", "月の無い時間帯", s["window_start"], s["window_end"])):
        if a and b and (key != "moon_free_window" or night["window_kind"] == "moon_free"):
            values.append({"key": key, "name": name, "value": [a, b], "unit": None, "say": [f"{clock(a, d)}〜{clock(b, d)}", clock(a, d), clock(b, d)]})
    if s["clear_hours"]:
        values.append({"key": "clear_hours", "name": "晴れ間の長さ", "value": s["clear_hours"], "unit": "時間", "say": [hours_say(s["clear_hours"])]})
    dist = B.distance_say(km, c)
    say = [site["label"], *night_says(d), *B.day_says(d), dist, dist.replace("直線で", "")]
    for v in values:
        say += v["say"]
    out = {"id": None, "kind": "star_night", "site_id": site["site_id"], "name": site["label"], "group": site["group"], "date": d.isoformat(),
           "weekday": WEEKDAY_JA[d.weekday()], "label": night_label(d), "status": s["status"], "reasons": [REASON_JA[r] for r in s["reasons"]],
           "regime": night["forecast_regime"], "rank": rank, "requires_lift_access": site["requires_lift_access"],
           "lat": site["lat"], "lon": site["lon"], "distance_km": round(km, 1), "distance_say": dist, "main_ok": not ng, "main_ng": ng,
           "selected_by": None, "values": values, "near": [], "say": list(dict.fromkeys(say))}
    if "night_rank" in s:                       # その夜の中の順位(新しい出力だけ。無い出力の資料は 1 バイトも変えない)。答えに書かない(rank と同じ)
        out["night_rank"] = s["night_rank"]
    if "origin" in site:                        # 地点の出どころ(新しい出力だけ。ODbL の表示に使う)
        out["origin"] = site["origin"]
    return out


def site_key(f, km):
    """地点の並び: 主軸の地点を先 → ホシビヨリの候補の夜の順位 rank(無ければあと)→ その夜の中の順位 night_rank(rank が無い地点だけ効く。
    無ければあと)→ 直線距離の近い順 → site_id。night_rank の無い出力(1.2.0)では、今までの並びと同じ(docs/hoshibiyori-mapping.md 2.1)。
    候補の夜で rank がある地点は rank を先に使う(ホシビヨリの画面と同じ並び。MSM の夜の 2 つの並びの食い違いは rank が勝つ。仮置き)。"""
    nr = f.get("night_rank")
    return (f["group"] != "primary", f["rank"] is None, f["rank"] or 0, nr is None, nr or 0, km, f["site_id"])


def _night_fact(d, night, in_range, max_km, origin_name, min_hours, B):
    """夜ごとの状態と件数 [T…]。state: passed / moon(月の無い時間帯で調べていない)/ none_passed(調べたが 250km 以内に通った地点が無い)/ not_examined。"""
    out = {"id": None, "kind": "star_count", "date": d.isoformat(), "weekday": WEEKDAY_JA[d.weekday()], "label": night_label(d), "regime": None,
           "in_range": in_range, "passed": None, "total": None, "line": None}
    lab = night_label(d)
    if night is None or night["window_kind"] == "none" or not night["counts"] or night["counts"]["all"]["cloud_examined"] == 0:
        return dict(out, state="not_examined", say=[])
    a = night["counts"]["all"]
    out.update(regime=night["forecast_regime"], passed=a["passed"], total=a["total"])
    if night["window_kind"] != "moon_free":
        dark = (datetime.fromisoformat(night["dark_end"]) - datetime.fromisoformat(night["dark_start"])).total_seconds() / 3600
        up = _hours_screen(night["moon"]["up_hours"])
        why = "月の無い時間帯が無いため" if not night["moon_free_hours"] else f"月の無い時間帯が {B.num(min_hours)} 時間より短いため"
        out["line"] = f"{lab}は、暗い時間帯 {_hours_screen(dark)} 時間のうち月が出ているのが {up} 時間(基準地点の目安)で、{why}、星は今回は見送りとしています。"
        return dict(out, state="moon", in_range=None, say=[f"暗い時間帯 {_hours_screen(dark)} 時間", f"月が出ているのは {up} 時間"])
    say = [f"出発地({origin_name})から直線 {max_km}km 以内で条件を通った地点は {in_range} 地点", f"条件を通った地点は {in_range} 地点",
           f"調べた {a['total']} 地点のうち条件を通った地点は {a['passed']} 地点"]
    if a["not_examined"]:
        say.append(f"調べていない地点は {a['not_examined']} 地点")
    if in_range:
        return dict(out, state="passed", say=say)
    if a["passed"]:
        out["line"] = f"{lab}は、条件を通った地点が、出発地({origin_name})から直線 {max_km}km 以内にありません。"
    else:
        rs = "・".join(f"{REASON_JA[k]} {a['failed_reasons'][k]} 地点" for k in REASON_JA if a["failed_reasons"].get(k))
        out["line"] = f"{lab}は、調べた {a['total']} 地点の中に条件を通った地点がありません(通らなかった理由は、重なりありで {rs})。"
    return dict(out, state="none_passed", say=say)


def build(sh, target, origin, now, c, B, interests=()):
    """星の部分 → dict(id はまだ無い)。sh は shelf.load_stars の結果(ok)。地点の候補は night_pool に全部、資料に入れるのは facts。"""
    sc = c["concierge"]["stars"]
    max_km = c["origin"]["max_straight_line_km"]
    mode, why = choose_mode(sh["natives"])
    n = sh["natives"][mode]
    sites = {x["site_id"]: x for x in n["site_index"] if x["site_id"] is not None}
    rk = ranks(n)
    nights = {r["night_date"]: r for r in n.get("requested_nights") or []}
    pool, counts, facts = {}, [], []
    for d in target:
        ds = d.isoformat()
        night = nights.get(ds)
        cands = []
        for s in (night or {}).get("sites") or []:
            if s["status"] != "passed" or s["site_id"] not in sites or night["window_kind"] != "moon_free":      # site_id の無い地点は使わない
                continue
            f = _site_fact(s, night, sites[s["site_id"]], d, (rk.get((ds, s["site_id"])) or (None,))[0], origin, B, c)
            if f["distance_km"] <= max_km:
                cands.append(f)
        cands.sort(key=lambda f: site_key(f, f["distance_km"]))
        pool[ds] = cands
        for f in cands[:sc["top_per_night"]]:
            f["selected_by"] = "top"
        facts += cands[:sc["top_per_night"]]
        counts.append(_night_fact(d, night, len(cands), max_km, origin["name"], n["thresholds"]["min_clear_window_hours"], B))
    e = sh["entry"]
    age = S.age_hours(e, now)
    stale = age is not None and age >= c["collect"]["stale_after_hours"]
    lines = {"star_data_time": (f"星の予報は {data_time_label(e)} 時点のもので、{int(age)} 時間前の古い予報です({runs_text(e.get('model_runs'))})。" if stale
                                else f"星の予報は {data_time_label(e)} 時点のものです({runs_text(e.get('model_runs'))})。"),
             "star_mode": (MODE_FEW if mode == "stars" and "milky_way" in interests else "") + MODE_TEXT[mode],
             "star_attribution": (f"星の気象データ: Weather data by Open-Meteo.com(CC BY 4.0)。雲量はホシビヨリ {e.get('version')} が加工した値です。"
                                  "地形は国土地理院 地理院タイル(標高タイル)を加工して作成、光害は NASA Black Marble VNP46A4、"
                                  "地点は © OpenStreetMap contributors(ODbL)、天体位置は JPL DE421 暦(Skyfield経由)です。")}
    ec = [x["label"] for x in counts if x["regime"] == "ECMWF" and x["state"] != "not_examined"]
    if ec:
        lines["star_regime"] = f"{'・'.join(ec)}は、ECMWF の予報だけの夜で、雲量は目安です。"
    return {"mode": mode, "mode_reason": why, "data_time": e.get("data_time"), "age_hours": age, "stale": stale, "version": e.get("version"),
            "status": e.get("status"), "facts": facts, "counts": counts, "lines": lines, "pool": pool,
            "index": [{"id": x["site_id"], "label": x["label"], "name": x["name"]} for x in n["site_index"] if x["site_id"] is not None]}


# ---------------------------------------------------------------- 一日の流れの案
def _attach(star, f, km, yfact, B, c):
    """地点の事実に、その山からの距離(書いてよい表記)を足す。"""
    if any(x["fact"] == yfact["id"] for x in star["near"]):
        return
    dist = B.distance_say(km, c)
    star["near"].append({"fact": yfact["id"], "mountain_id": yfact["mountain_id"], "name": yfact["name"], "distance_km": round(km, 1),
                         "say": [dist, dist.replace("直線で", "")]})


def _frames(y, s):
    return [{"slot": slot, "label": lab, "kind": kind, "fact": {"mountain": y, "stars": s}.get(kind)} for slot, lab, kind in FRAMES]


def _km(B, a_lat, a_lon, b):
    return B.distance_km(a_lat, a_lon, b["lat"], b["lon"])


def day_mountains(star, all_day, coords, B, c):
    """星の地点の近く(直線 combo.near_km 以内)の、同じ日に主役にできる山 → [(山の事実, 距離)](今の山の並び main_key)。"""
    near = c["combo"]["near_km"]
    out = []
    for f in sorted([f for f in all_day if f["main_ok"]], key=B.main_key):
        lat, lon = coords[f["mountain_id"]]
        km = _km(B, lat, lon, star)
        if km <= near:
            out.append((f, km))
    return out


def plan(stars, facts, all_by_day, coords, star_first, B, c):
    """→ (案のリスト(id なし。事実は id でなく事実そのもの), 資料に足す山の事実, 資料に足す星の事実)。
    並び: 日付 → 起点(興味の語に合うほうを先。仮置き)→ 山が起点は今の山の並び / 星が起点は地点の並び。山の点数と星の順位は比べない。"""
    near = c["combo"]["near_km"]
    add_m, add_s, plans = [], [], []
    have_s = {(f["date"], f["site_id"]): f for f in stars["facts"]}
    have_m = {(f["date"], f["mountain_id"]): f for f in facts}

    def put_s(f, by):
        k = (f["date"], f["site_id"])
        if k not in have_s:
            f["selected_by"] = by
            have_s[k] = f
            add_s.append(f)
        return have_s[k]

    for order, f in enumerate(sorted([f for f in facts if f["main_ok"]], key=lambda f: (f["date"], B.main_key(f)))):      # 山が起点の案
        lat, lon = coords[f["mountain_id"]]
        hits = sorted([(site_key(s, km), s, km) for s in stars["pool"].get(f["date"], []) for km in [_km(B, lat, lon, s)] if km <= near], key=lambda x: x[0])
        star = put_s(hits[0][1], "near") if hits else None
        plans.append({"date": f["date"], "kind": "mountain", "order": order, "y": f, "s": star, "km": hits[0][2] if hits else None,
                      "others": max(0, len(hits) - 1)})
    # 星が起点の案: 夜ごとの枠の地点と、その外で「近くに主役にできる山がある」地点の上位(昼の案を付けられるように。どちらも地点の並びのまま)
    near_m = {(s["date"], s["site_id"]): day_mountains(s, all_by_day.get(s["date"], []), coords, B, c) for ds in stars["pool"] for s in stars["pool"][ds]}
    starts = [s for s in stars["facts"] if s["selected_by"] == "top"]
    for ds, cands in stars["pool"].items():
        extra = [s for s in cands if s not in starts and near_m[(ds, s["site_id"])]]
        starts += [put_s(s, "top_with_mountain") for s in extra[:c["concierge"]["stars"]["with_mountain_per_night"]]]
    for order, s in enumerate(starts):
        ms = near_m[(s["date"], s["site_id"])]
        y = None
        if ms:
            y = ms[0][0]
            k = (y["date"], y["mountain_id"])
            if k not in have_m:
                y["selected_by"] = "star"
                have_m[k] = y
                add_m.append(y)
            y = have_m[k]
        plans.append({"date": s["date"], "kind": "stars", "order": order, "y": y, "s": s, "km": ms[0][1] if ms else None, "others": max(0, len(ms) - 1)})
    first = "stars" if star_first else "mountain"
    plans.sort(key=lambda p: (p["date"], p["kind"] != first, p["order"]))
    return plans, add_m, add_s


def finish(stars, plans, start_line, B, c):
    """id を振り、案を資料の形にする → (資料の stars, 決まった文のリスト, 案のリスト)。"""
    facts = sorted(stars["facts"], key=lambda f: (f["date"], site_key(f, f["distance_km"])))
    for i, f in enumerate(facts, 1):
        f["id"] = f"S{i:03d}"
    for i, t in enumerate(stars["counts"], 1):
        t["id"] = f"T{i}"
    out = []
    for i, p in enumerate(plans, 1):
        y, s = p["y"], p["s"]
        if y and s:
            _attach(s, s, p["km"], y, B, c)
        main, add = (y, s) if p["kind"] == "mountain" else (s, y)
        adds = []
        if add:
            adds = [{"kind": "stars" if add is s else "mountain", "fact": add["id"], "distance_km": round(p["km"], 1), "others": p["others"]}]
        out.append({"id": f"P{i}", "date": p["date"], "main": {"kind": p["kind"], "fact": main["id"]}, "adds": adds,
                    "frames": _frames(y["id"] if y else None, s["id"] if s else None)})
    L = [{"key": k, "text": stars["lines"][k]} for k in LINE_KEYS if k in stars["lines"]]
    L += [{"key": "star_lifts", "text": f"{f['label']}の{f['name']}はリフト要の地点で、運行は確かめていません。", "fact": f["id"]}
          for f in facts if f["requires_lift_access"]]
    L += [{"key": "star_skips", "text": t["line"], "fact": t["id"], "date": t["date"]} for t in stars["counts"] if t["line"]]
    for i, x in enumerate(L, start_line):
        x["id"] = f"L{i}"
    doc = {"mode": stars["mode"], "mode_reason": stars["mode_reason"], "data_time": stars["data_time"], "age_hours": stars["age_hours"],
           "stale": stars["stale"], "status": stars["status"], "version": stars["version"], "facts": facts, "counts": stars["counts"],
           "index": stars["index"]}
    return doc, L, out


def lines_out(L):
    out = {k: None for k in LINE_KEYS} | {"star_lifts": [], "star_skips": []}
    for x in L:
        item = {"id": x["id"], "text": x["text"]} | ({"fact": x["fact"]} if x.get("fact") else {})
        if x["key"] in ("star_lifts", "star_skips"):
            out[x["key"]].append(item)
        else:
            out[x["key"]] = item
    return out


def all_lines(brief):
    """資料の星の決まった文の全部(星の無い資料なら空)。"""
    L = brief["lines"]
    return [L[k] for k in LINE_KEYS if L.get(k)] + list(L.get("star_lifts") or []) + list(L.get("star_skips") or [])


RULES = [
    "星の答えの形: 結論(1〜2文)→ 山の時点([L…])→ 星の時点とモード([L…] の決まった文をそのまま)→ おすすめは案ごとに時刻の順(朝〜日中の山 → 夜の星)→ 先の予報・ECMWF の夜・リフト要の決まった文 → 見送り → 注記 → 分からないこと → 出典(山と星)。",
    "案の枠の順番(朝〜日中 → 夜)を変えない。星が主役の質問でも、日中の山 → 夜の星の順に書く。1 つの案に山と星を無理にそろえない(星の付かない案には星を書かない)。",
    "星の地点・時刻・夜を書いた文の終わりに、星の事実の印 [S…] を付ける。地点の名前は「書いてよい表記」の形(市町村つき)で書く。山の名前も書く文には [Y…] も付ける。",
    "星の夜は「11月28日(土)の夜」「28日(土)の夜」と書く([S…]・[T…] を付けた文には必ず入れる)。「28日から29日」「28〜29日」「28日深夜」と書かない。夜中の 0 時を過ぎた時刻は「翌2:30」と書く。",
    "夜に書けるのは、晴れ間の時間帯・晴れ間の長さ・月の無い時間帯・地点・距離・どちらのモードかだけ。どの星・星座・惑星・流星群が見えるかは書かない(資料に無い)。",
    "星の件数と「調べていない」「条件を通った地点が無い」は、星の件数 [T…] の「書いてよい言い方」か、星の見送りの決まった文 [L…] で書く。「調べていない」と「条件を通らなかった」を混ぜない。山の件数([N…])と星の件数([T…])を 1 つの文に書かない。",
    "山の点数と、星の順位・時間を比べない。星の地点どうしを「いちばん」「最も」で比べない。",
    "山から星の地点までの距離は、案にある組だけ「○○から直線で約○km」と書く([Y…] と [S…] の両方を付ける)。所要時間は書かない。",
    "近くに星の地点が無い山のことは、足りないもの [G…] の「直線 20km 以内に、条件を通った星の地点がありません」の文で書く(自分で言い切らない)。",
    "聞かれた夜の雲の予報が調べられていないとき(足りないもの [G…])は、その文を必ず写す。ECMWF の夜・リフト要の地点を書いたら、その決まった文を必ず写す。",
    "[おすすめ] の行には、すすめた山 [Y…] と星 [S…] の id を書く。",
]


def render_md(b):
    """資料の Markdown の星の部分。"""
    st = b["stars"]
    out = ["## 星(地点と夜)", "", f"- モード: {'星空・星座' if st['mode'] == 'stars' else '天の川'}(答えには、決まった文をそのまま写す)", ""]
    for t in st["counts"]:
        ja = {"passed": "条件を通った地点あり", "moon": "月の理由で見送り", "none_passed": "条件を通った地点なし", "not_examined": "調べていない"}[t["state"]]
        out.append(f"### [{t['id']}] {t['label']}: {ja}" + (f"(予報 {t['regime']})" if t["regime"] else ""))
        out.append("")
        if t["say"]:
            out.append(f"- 書いてよい言い方: {' / '.join(t['say'])}")
        for f in [f for f in st["facts"] if f["date"] == t["date"]]:
            out.append(f"- **[{f['id']}] {f['name']}**({'主軸' if f['group'] == 'primary' else '参考'}の地点・{f['distance_say']})"
                       + (f"・順位 {f['rank']}(書かない)" if f["rank"] else "")
                       + (f"・その夜の中の順位 {f['night_rank']}(書かない)" if f.get("night_rank") else "") + ("・リフト要" if f["requires_lift_access"] else ""))
            for v in f["values"]:
                out.append(f"  - {v['name']}: {v['say'][0]}")
            for x in f["near"]:
                out.append(f"  - {x['name']}({x['fact']})から{x['say'][0]}")
            out.append(f"  - 書いてよい表記: {' / '.join(f['say'])}")
        out.append("")
    return out


def render_plans(b):
    facts = {f["id"]: f for f in b["facts"]} | {f["id"]: f for f in b["stars"]["facts"]}
    out = ["## 一日の流れの案(枠は時刻の順。順番を変えない)", ""]
    if not b["plans"]:
        return out + ["(なし。おすすめにできる山も星の地点もありません)"]
    for p in b["plans"]:
        parts = []
        for fr in p["frames"]:
            if fr["fact"]:
                parts.append(f"{fr['label']} {fr['fact']} {facts[fr['fact']]['name']}")
            elif fr["kind"] != "nature":
                parts.append(f"{fr['label']} なし")
        tail = f"(間は直線 {p['adds'][0]['distance_km']}km。ほかに近い候補 {p['adds'][0]['others']} 件)" if p["adds"] else ""
        out.append(f"- {p['id']}: {p['date']}({'山' if p['main']['kind'] == 'mountain' else '星'}が起点) " + " → ".join(parts) + tail)
    return out
