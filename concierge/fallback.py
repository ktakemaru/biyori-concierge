"""控えの文: 照合に 3 回通らなかったときに出す、資料だけから作る事実の文(飾らない)。
印つきの下書きとして組み立て、verify と同じ検査に通してから出す(テストで必ず通ることを確かめる)。
並びは指示書 6.5 の答えの形: 結論 → いつ時点(data_time・coverage)→ おすすめ 3 つまで(日ごとの上位。主役にできる山だけ)と事実
→ 注意(危険信号・先の予報)→ 見送り・足りないもの → 出典(attribution)。"""
from .brief import skip_key
from .common import NL

MAX_PICKS = 3
MAX_SKIP = 2
MAX_NAMED_SKIP = 4      # 名指しの山の見送りの文の数の上限(長い範囲で名指しが多いとき)。仮置き


def picks(brief):
    """日ごとの上位(組み合わせ plans の並び = 主役の枠の並び)から、主役にできる山を日をまたいで順に 3 つまで。"""
    facts = {f["id"]: f for f in brief["facts"]}
    by_day = {}
    for p in brief["plans"]:
        by_day.setdefault(p["date"], []).append(facts[p["main"]["fact"]])
    for v in by_day.values():                       # 名指しで地域の外(順位なし)の山は、その日の順位つきの山のあと
        v.sort(key=lambda f: f["rank"] is None)
    out, i = [], 0
    days = sorted(by_day)
    while len(out) < MAX_PICKS and any(i < len(by_day[d]) for d in days):
        for d in days:
            if i < len(by_day[d]) and len(out) < MAX_PICKS:
                out.append(by_day[d][i])
        i += 1
    return out


def _fact_sentences(f):
    first = (f"{f['label']}の{f['name']}(標高{_n(f['elevation_m'])}m・{f['distance_say']})は"
             f"{_n(f['score'])}点で、基準の{_n(f['threshold'])}点を超えています。[{f['id']}]")
    vals = [v for v in f["values"] if v["key"] in ("ridge_wind_ms", "cloud_pct", "precip_wet_pct", "chill")]
    if not vals:
        return [first]
    body = "、".join(f"{v['name']}は{v['say'][0]}" for v in vals)
    return [first, f"{body}の見込みです。[{f['id']}]"]


def _n(v):
    from .brief import num
    return num(v)


def draft(brief, compact=False):
    """compact=True: 字数の上限を超えたときの短い形(見送り・足りないものの一部を省く)。"""
    L = brief["lines"]
    chosen = picks(brief)
    hz = {h["fact"]: h for h in L["hazards"]}
    gaps = list(brief["gaps"])
    out = []
    if chosen:
        f = chosen[0]
        out.append(f"いちばんのおすすめは、{f['label']}の{f['name']}です。[{f['id']}]")
    elif not brief["shelf"]["available"]:
        g = next(g for g in gaps if g["kind"] == "shelf_unavailable")
        out.append(f"{g['text']}[{g['id']}]")
        gaps.remove(g)
    elif not brief["facts"] and any(g["kind"] == "day_not_in_forecast" for g in gaps):
        g = next(g for g in gaps if g["kind"] == "day_not_in_forecast")
        out.append(f"{g['text']}[{g['id']}]")
        gaps.remove(g)
    else:
        out.append("今回の対象の日には、条件のそろった山はありません。見送るのがよさそうです。")
    for key in ("data_time", "coverage"):
        if L[key]:
            out.append(f"{L[key]['text']}[{L[key]['id']}]")
    out.append("")
    for i, f in enumerate(chosen, 1):
        out.append(f"{i}. " + "".join(_fact_sentences(f)))
        if f["id"] in hz:
            out.append(f"{hz[f['id']]['text']}[{hz[f['id']]['id']}]")
    if L["lead_time"] and any(not f["reliable"] for f in chosen):
        out.append(f"{L['lead_time']['text']}[{L['lead_time']['id']}]")
    skip = [f for f in brief["facts"] if not f["main_ok"] and f["named"]][:MAX_NAMED_SKIP]
    hard = [f for f in brief["facts"] if not f["main_ok"] and not f["named"] and "hazard_hard" in f["main_ng"]]
    skip += sorted(hard, key=skip_key)[:MAX_SKIP]        # 日をまたいで、見送りの枠と同じ並び(危険の段階の重い順)。同じなら日の早い順
    if compact:
        skip, gaps = skip[:1], [g for g in gaps if g["kind"] in ("no_safety_info", "shelf_unavailable", "day_not_in_forecast")]
    if skip:
        out.append("")
    for f in skip:
        why = "基準に届いていません" if "below_threshold" in f["main_ng"] else "危険信号が出ているため、今回は見送りとしています"
        out.append(f"{f['label']}の{f['name']}は{_n(f['score'])}点で、{why}。[{f['id']}]")
        if f["id"] in hz and "below_threshold" not in f["main_ng"]:
            out.append(f"{hz[f['id']]['text']}[{hz[f['id']]['id']}]")
    if L.get("hazard_note") and any(h["text"] in x for h in L["hazards"] for x in out):      # 危険信号の注記は 1 回だけ
        out.append(f"{L['hazard_note']['text']}[{L['hazard_note']['id']}]")
    out.append("")
    for g in gaps:
        out.append(f"{g['text']}[{g['id']}]")
    if L["attribution"]:
        out += ["", f"{L['attribution']['text']}[{L['attribution']['id']}]"]
    out += ["", "[おすすめ] " + (", ".join(f["id"] for f in chosen) or "なし")]
    return NL.join(out) + NL
