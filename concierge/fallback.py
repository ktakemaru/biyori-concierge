"""控えの文: 照合に 3 回通らなかったときに出す、資料だけから作る事実の文(飾らない)。
印つきの下書きとして組み立て、verify と同じ検査に通してから出す(テストで必ず通ることを確かめる)。
並びは指示書 6.5 の答えの形: 結論 → いつ時点(data_time・coverage)→ おすすめ 3 つまで(日ごとの上位。主役にできる山だけ)と事実
→ 注意(危険信号・先の予報)→ 見送り(名指しの山と、見送りの枠のまとめの文・件数)→ 危険信号の注記 → 足りないもの → 出典(attribution)。"""
from . import named as N
from .brief import CLOUD_CLEAR_SAY, LEVEL_RANK, main_key, skip_key
from .common import NL

MAX_PICKS = 3
MAX_SKIP_DAYS = 2      # 見送りのまとめの文を書く日の数の上限。仮置き
MAX_NAMED_BLOCKS = 6    # 山を名指しした答えで書く、山と日の組の数の目安(超える日は省き、そのことを書く)。仮置き
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
    clear = []
    if f.get("cloud_clear"):                               # 生の雲量が 0 %: 数字でなく言葉で書く
        vals = [v for v in vals if v["key"] != "cloud_pct"]
        clear = [f"{CLOUD_CLEAR_SAY}です。[{f['id']}]"]
    if not vals:
        return [first] + clear
    body = "、".join(f"{v['name']}は{v['say'][0]}" for v in vals)
    return [first, f"{body}の見込みです。[{f['id']}]"] + clear


def _n(v):
    from .brief import num
    return num(v)


def _skip_days(brief):
    """見送りのまとめの文のうち、書くもの → [(まとめの文, その日の件数の事実か None)]。日の順は、枠の先頭の山が見送りの枠の並びで先の日から(危険の段階の重い順)。"""
    facts = {f["id"]: f for f in brief["facts"]}
    counts = {n["date"]: n for n in brief["hazard_counts"]}
    lines = sorted(brief["lines"].get("skips") or [], key=lambda x: skip_key(facts[x["facts"][0]]))
    return [(x, counts.get(x["date"])) for x in lines]


def _count_sentence(n):
    """件数の文(まとめの文に続けて読む)。"""
    a = n["all"]
    tail = f"で、このうち危険は {a['danger']} 座" if a["danger"] else ""
    return f"この日は、危険信号が警戒以上の山は {a['total']} 座{tail}です。[{n['id']}]"


def _joined(fs):
    return f"{fs[0]['name']}と{fs[1]['name']}" if len(fs) == 2 else "・".join(f["name"] for f in fs)


def _marks(fs):
    return "".join(f"[{f['id']}]" for f in fs)


def _named_verdict(fs, stale):
    """名指しの山(1 日ぶん)の結論の文 → (文, すすめた事実)。"""
    best, lab = N.winners(fs), fs[0]["label"]
    if len(fs) == 1:
        f = fs[0]
        if best and stale:
            return f"古い予報では、{lab}の{f['name']}が候補です。[{f['id']}]", best
        if best:
            return f"{lab}の{f['name']}は、おすすめの候補です。[{f['id']}]", best
        why = "点数が基準に届いていない" if "below_threshold" in f["main_ng"] else "危険信号が出ている"
        return f"{lab}の{f['name']}は、{why}ため、今回は見送りとしています。[{f['id']}]", []
    if not best:
        return f"{lab}は、お尋ねの山の中に、条件のそろった山がありません。{_marks(fs)}見送るのがよさそうです。", []
    head = "古い予報では、お尋ねの山の中では、" if stale else "お尋ねの山の中では、"
    if len(best) == 1:
        return f"{head}{lab}の{best[0]['name']}が{'候補' if stale else 'おすすめ'}です。{_marks(best)}", best
    tail = "が候補で" if stale else "が並び"
    return f"{head}{lab}は{_joined(best)}{tail}、点数と危険信号の段階では差がつきません。{_marks(best)}", best


def _named_block(f, hz, compact):
    """名指しの山 1 座(1 日ぶん): 点数・風・体感・雲の様子・危険信号を、どの山も同じ順で書く。"""
    m = f"[{f['id']}]"
    head = f"{f['label']}の{f['name']}(標高{_n(f['elevation_m'])}m・{f['distance_say']})は{_n(f['score'])}点で、基準の{_n(f['threshold'])}点"
    s = [head + ("に届いていません。" if "below_threshold" in f["main_ng"] else "を超えています。") + m]
    if f["detail_level"] == "score_only":
        s.append(("点数が低く、" if "below_threshold" in f["main_ng"] else "") + f"くわしい値はありません。{m}")
    elif not compact:
        vals = [v for v in f["values"] if v["key"] in ("ridge_wind_ms", "day_peak_wind_ms", "chill") or v["key"] == "cloud_pct" and not f.get("cloud_clear")]
        if vals:
            s.append("、".join(f"{v['name']}は{v['say'][0]}" for v in vals) + f"の見込みです。{m}")
        if f.get("cloud_clear"):
            s.append(f"{CLOUD_CLEAR_SAY}です。{m}")
    if "hazard_hard" in f["main_ng"] and "below_threshold" not in f["main_ng"]:
        s.append(f"危険信号が出ているため、今回は見送りとしています。{m}")
    if f["id"] in hz:
        return "".join(s) + NL + f"{hz[f['id']]['text']}[{hz[f['id']]['id']}]"
    return "".join(s) + f"危険信号は出ていません。{m}"


def _named_difference(brief, day, fs):
    """名指しの山どうしの違い(1〜2 文): 日中ピークの風速の差(3 座以上なら、差のいちばん大きい組)と、値の無い山のこと。"""
    out = []
    gs = [g for g in brief.get("named_gaps") or [] if g["date"] == day and set(g["among"]) <= {f["id"] for f in fs}]
    if gs:
        g = max(gs, key=lambda x: x["diff"])                      # 同じ差なら資料の並びで先の組
        pair = [f for f in fs if f["id"] in g["among"]]
        tail = " で、差はわずかです" if g["small"] else " です"
        out.append(f"{_joined(pair)}では、{g['say'][0]}{tail}。{_marks(pair)}[{g['id']}]")
    lacking = [f for f in fs if f["detail_level"] == "score_only"]
    if lacking and len(fs) > 1:
        who = _joined(lacking) if len(lacking) > 1 else lacking[0]["name"]
        out.append(f"{who}にはくわしい値がないため、風や体感は比べられません。{_marks(lacking)}")
    return "".join(out)


def _named_days(brief, compact):
    """書く日 → (日のリスト, 省いた日があるか)。日が多いときは、名指しの山の条件のよい日から、組の数の目安まで。"""
    fs = N.facts(brief)
    days = sorted({f["date"] for f in fs})

    def key(d):
        best = min((f for f in fs if f["date"] == d), key=main_key)
        return (not any(f["main_ok"] for f in fs if f["date"] == d), -best["score"], LEVEL_RANK.get(best["hazard_level"], 0), d)
    keep, n = [], 0
    for d in sorted(days, key=key):
        k = sum(1 for f in fs if f["date"] == d)
        if keep and (compact or n + k > MAX_NAMED_BLOCKS):
            break
        keep.append(d)
        n += k
    shown = {f["mountain_id"] for f in fs if f["date"] in keep}
    for m in sorted({f["mountain_id"] for f in fs} - shown):      # どの山も 1 回は書く
        keep.append(min(f["date"] for f in fs if f["mountain_id"] == m))
    keep = sorted(set(keep))
    return keep, len(keep) < len(days)


def _draft_named(brief, compact):
    """山を名指しした質問の控えの文(利用者の決定 2026-11-25)。決まりは concierge/named.py。"""
    L, hz = brief["lines"], {h["fact"]: h for h in brief["lines"]["hazards"]}
    stale = bool(brief["shelf"].get("stale"))
    data_time = [f"{L['data_time']['text']}[{L['data_time']['id']}]"] if L["data_time"] else []
    lead_gaps = N.gaps(brief) + [g for g in brief["gaps"] if g["kind"] == "day_not_in_forecast" and not N.facts(brief)]
    gaps = [g for g in brief["gaps"] if g not in lead_gaps and g["kind"] != "no_mountain_above"]
    if compact:
        gaps = [g for g in gaps if g["kind"] in ("no_safety_info", "day_not_in_forecast")]
    out = (data_time if stale else []) + [f"{g['text']}[{g['id']}]" for g in lead_gaps]      # 予報の無い山のことを先に
    days, cut = _named_days(brief, compact)
    by_day = [(d, N.facts(brief, d)) for d in days]
    picks_ = []
    for _, fs in by_day:
        text, best = _named_verdict(fs, stale)
        out.append(text)
        picks_ += best
    out += [] if stale else data_time
    if L["coverage"]:
        out.append(f"{L['coverage']['text']}[{L['coverage']['id']}]")
    shown = [f for _, fs in by_day for f in fs]
    out.append("")
    for i, f in enumerate(shown, 1):
        out.append((f"{i}. " if len(shown) > 1 else "") + _named_block(f, hz, compact))
    diffs = [] if compact else [x for x in (_named_difference(brief, d, fs) for d, fs in by_day) if x]
    if diffs:
        out += [""] + diffs
    if L["lead_time"] and any(not f["reliable"] for f in shown):
        out.append(f"{L['lead_time']['text']}[{L['lead_time']['id']}]")
    if cut:
        out.append("対象の日が多いため、ほかの日は省いています。")
    calm = [f for d, _ in by_day for f in N.calm_others(brief, d)] if len(brief["when"]["days"]) == 1 else []      # 例外の 1 文(日が 1 つのときだけ)
    if calm:
        out += ["", f"なお、{calm[0]['label']}の{calm[0]['name']}には、危険信号が出ていません。[{calm[0]['id']}]"]
    out.append("")
    if L.get("hazard_note") and any(h["text"] in x for h in L["hazards"] for x in out):
        out.append(f"{L['hazard_note']['text']}[{L['hazard_note']['id']}]")
    out += [f"{g['text']}[{g['id']}]" for g in gaps]
    if L.get("refresh"):
        out += ["", f"{L['refresh']['text']}[{L['refresh']['id']}]"]
    if L["attribution"]:
        out += ["", f"{L['attribution']['text']}[{L['attribution']['id']}]"]
    out += ["", "[おすすめ] " + (", ".join(f["id"] for f in picks_) or "なし")]
    return NL.join(out) + NL


def draft(brief, compact=False):
    """compact=True: 字数の上限を超えたときの短い形(見送り・足りないものの一部を省く)。"""
    if N.is_named(brief):
        return _draft_named(brief, compact)
    L = brief["lines"]
    chosen = picks(brief)
    hz = {h["fact"]: h for h in L["hazards"]}
    gaps = list(brief["gaps"])
    out = []
    stale = bool(brief["shelf"].get("stale"))
    if stale:                                              # 予報が古いとき: 最初の文は時点(古さ)。言い切らない
        if L["data_time"]:
            out.append(f"{L['data_time']['text']}[{L['data_time']['id']}]")
    if chosen:
        f = chosen[0]
        if stale:
            out.append(f"古い予報では、{f['label']}の{f['name']}が候補です。[{f['id']}]")
        else:
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
        if L[key] and not (stale and key == "data_time"):
            out.append(f"{L[key]['text']}[{L[key]['id']}]")
    out.append("")
    for i, f in enumerate(chosen, 1):
        out.append((f"{i}. " if len(chosen) > 1 else "") + "".join(_fact_sentences(f)))      # 番号は、並べる山が 2 つ以上のときだけ
        if f["id"] in hz:
            out.append(f"{hz[f['id']]['text']}[{hz[f['id']]['id']}]")
    if L["lead_time"] and any(not f["reliable"] for f in chosen):
        out.append(f"{L['lead_time']['text']}[{L['lead_time']['id']}]")
    skip = [f for f in brief["facts"] if not f["main_ok"] and f["named"]][:MAX_NAMED_SKIP]
    days = _skip_days(brief)[:MAX_SKIP_DAYS]
    if compact:
        skip, days = skip[:1], [] if skip else [(x, None) for x, _ in days[:1]]
        gaps = [g for g in gaps if g["kind"] in ("no_safety_info", "shelf_unavailable", "day_not_in_forecast")]
    if skip or days:
        out.append("")
    said = {i for x, _ in days for i in x["facts"]}      # まとめの文で言う山は、山ごとの危険信号の文を並べない
    for f in skip:
        why = "基準に届いていません" if "below_threshold" in f["main_ng"] else "危険信号が出ているため、今回は見送りとしています"
        out.append(f"{f['label']}の{f['name']}は{_n(f['score'])}点で、{why}。[{f['id']}]")
        if f["id"] in hz and f["id"] not in said and "below_threshold" not in f["main_ng"]:
            out.append(f"{hz[f['id']]['text']}[{hz[f['id']]['id']}]")
    if days:
        out.append("次の山は、今回は見送りとしています。")
    for x, n in days:
        out.append(f"{x['text']}[{x['id']}]" + (_count_sentence(n) if n else ""))
    out.append("")
    if L.get("hazard_note") and any(h["text"] in x for h in L["hazards"] + (L.get("skips") or []) for x in out):      # 危険信号の注記(位置は verify も置き直す)
        out.append(f"{L['hazard_note']['text']}[{L['hazard_note']['id']}]")
    for g in gaps:
        out.append(f"{g['text']}[{g['id']}]")
    if L.get("refresh"):
        out += ["", f"{L['refresh']['text']}[{L['refresh']['id']}]"]
    if L["attribution"]:
        out += ["", f"{L['attribution']['text']}[{L['attribution']['id']}]"]
    out += ["", "[おすすめ] " + (", ".join(f["id"] for f in chosen) or "なし")]
    return NL.join(out) + NL
