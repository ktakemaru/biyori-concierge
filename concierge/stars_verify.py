"""星の文の照合(verify から呼ぶ。資料に星の部分があるときだけ)。決定論・通信なし。検査のコード名は docs/answer-checks.md「星の答え」。
語の一覧は concierge/data/verify.yaml の stars(仮置き)。"""
import re
from datetime import date

from . import stars as ST

SITE = "\ue003"             # 星の地点の名前の置き換え(山の名前の置き換えとは別の字)
TIME = re.compile(r"(翌)?\s*(?<![\d.])(\d{1,2}):(\d{2})(?!\d)")


class Index:
    """資料の星の部分から作った索引(Ctx.star)。"""

    def __init__(self, brief, norm):
        st = brief["stars"]
        self.doc, self.norm = st, norm
        self.facts = {f["id"]: f for f in st["facts"]}
        self.counts = {t["id"]: t for t in st["counts"]}
        self.labels = sorted(((norm(x["label"]), x["id"]) for x in st["index"]), key=lambda x: -len(x[0]))
        self.names = sorted({norm(x["name"]) for x in st["index"]}, key=lambda x: -len(x))
        self.in_brief = {f["site_id"] for f in st["facts"]}

    def mask(self, t):
        """地点の名前(市町村つき)を置き換える。→ (置き換えた文, 出てきた site_id の集合)。"""
        found = set()
        for n, sid in self.labels:
            if n in t:
                found.add(sid)
                t = t.replace(n, SITE)
        return t, found

    def texts(self, mid, kind, x, marked_y):
        """印の事実の、書いてよい表記(allowed に足す)。山からの距離は、その山の印もあるときだけ。"""
        if kind == "S":
            return x["say"] + [s for n in x["near"] if n["fact"] in marked_y for s in n["say"]]
        return x["say"] + ST.night_says(date.fromisoformat(x["date"])) + [x["label"]]


def _has(t, words):
    return [w for w in words if w in t]


def is_star_sentence(t, ids, R):
    return any(i[0] in "ST" for i in ids) or bool(_has(t, R["topic"]))


def sentence_errors(X, s, t, sites, ids, mk):
    """1 文の検査。t は地点の名前を置き換えたあとの文、sites は文にあった地点。mk(コード, 詳しく, 直し方) で足す。"""
    I, R = X.star, X.R["stars"]
    ss = [I.facts[i] for i in ids if i in I.facts]
    ts = [I.counts[i] for i in ids if i in I.counts]
    others = [X.ids[i] for i in ids if i in X.ids and X.ids[i][0] in "GL"]
    exempt = any(w in t for w in R["object_exempt"])
    # 地点の名前
    for sid in sorted(sites - {f["site_id"] for f in ss}):
        if sid in I.in_brief:
            mk("site_unmarked", "印の事実にない星の地点を書いている", "その地点の事実の印 [S…] を付ける")
        else:
            mk("site_not_in_brief", "資料にない星の地点を書いている", "資料にある地点だけを書く")
    star = is_star_sentence(t, ids, R) or bool(sites)
    if star:
        rest = X.mask_names(t)[0]
        for n in I.names:
            if len(n) >= R["bare_name_min"] and n in rest and n not in R["bare_name_ok"] and n not in X.question:
                mk("site_label", f"星の地点「{n}」を、見分けられる形で書いていない", "「書いてよい表記」の形(市町村つき)で書く")
                rest = rest.replace(n, " ")
        for m in re.finditer(R["place_re"], rest):
            w = m.group(0)
            if w not in R["place_common"] and w not in X.question:
                mk("unknown_site", f"資料にない場所の名前らしい語「{w}」", "資料にある地点だけを書く")
    # 夜の表記
    for f in ss + ts:
        if not any(n in t for n in ST.night_says(date.fromisoformat(f["date"]))):
            mk("night_label", f"星の夜の書き方「{ST.night_says(date.fromisoformat(f['date']))[1]}」がない",
               f"「{f['label']}」か「{ST.night_says(date.fromisoformat(f['date']))[1]}」と書く")
            break
    if star:
        for rx in R["bad_night"]:
            m = re.search(rx, t)
            if m:
                right = (ss + ts)[0]["label"] if ss + ts else "28日(土)の夜"
                mk("night_label", f"星の夜を「{m.group(0)}」と書いている", f"夜の始まりの日で「{right}」と書く")
                break
    # 時刻と「翌」
    if ss:
        ok = {(bool(m.group(1)), int(m.group(2)), int(m.group(3))) for f in ss for x in f["say"] for m in TIME.finditer(x)}
        for m in TIME.finditer(t):
            k = (bool(m.group(1)), int(m.group(2)), int(m.group(3)))
            if k not in ok and (not k[0], k[1], k[2]) in ok:
                mk("night_time", f"時刻「{m.group(0).strip()}」の「翌」が{'余分' if k[0] else '無い'}",
                   f"「{'' if k[0] else '翌'}{k[1]}:{k[2]:02d}」と書く(夜中の 0 時を過ぎた時刻だけに「翌」を付ける)")
    # 状態・件数の言い方
    cond = _has(t, R["condition"])
    if cond and ids and not (ss or ts or others):
        mk("star_unmarked", f"星の条件の話「{cond[0]}」に、星の事実の印 [S…]・[T…] がない", "星の事実の印を付ける(山の印では書けない)")
    if cond and not ids:
        mk("star_unmarked", f"印のない文に、星の条件の話「{cond[0]}」", "星の事実の印を付けて書く")
    if ts and any(i[0] == "N" for i in ids) or (re.search(r"\d\s*地点", t) and re.search(r"\d\s*座", t)):
        mk("counts_mixed", "山の件数と星の件数を 1 つの文に書いている", "文を分ける")
    says_ne = bool(re.search(R["not_examined_re"], t))
    says_np = bool(re.search(R["not_passed_re"], t))
    for x in ts:
        if says_ne and x["state"] != "not_examined" and not any("調べていない" in y for y in x["say"]):
            mk("star_state", f"{x['label']}は調べてあるのに、調べていないと書いている", "星の件数 [T…] の言い方で書く")
        if says_np and x["state"] == "not_examined":
            mk("star_state", f"{x['label']}は調べていないのに、条件を通らなかったと書いている", "足りないもの [G…] の文で書く")
        if says_np and x["state"] == "passed":
            mk("star_state", f"{x['label']}は条件を通った地点があるのに、無いと書いている", "星の件数 [T…] の言い方で書く")
    if ss and (says_ne or says_np):
        mk("star_state", "条件を通った地点の文に、条件を通らなかった・調べていないと書いている", "条件を通った地点として書く")
    # 比べる文
    if (ss or ts) and _has(_cut(t, X.R["compare"]["ok"]), X.R["compare"]["superlatives"]):
        mk("star_superlative", "星の地点・夜を、最上級の語で比べている", "比べずに、時間帯と距離の数字だけを書く")
    if star and re.search(R["score_re"], t):
        mk("score_across_biyori", "山の点数と星の話を 1 文に書いている", "文を分け、山の点数と星を比べない")
    # 山からの距離
    tn = t
    for w, mid in X.names:
        tn = tn.replace(w, f"\x02{mid}\x03")
    for m in re.finditer(r"\x02(m\d{3})\x03から(?:の)?(?:直線(?:距離)?で?)?\s*(約\s*\d+\s*km)", tn):
        good = {I.norm(x).replace(" ", "").replace("直線で", "") for f in ss for n in f["near"] if n["mountain_id"] == m.group(1) for x in n["say"]}
        if ss and m.group(2).replace(" ", "") not in good:
            mk("star_distance", "山から星の地点までの距離が、案の組の距離と合わない", "星の事実にある「○○から直線で約○km」だけを書く")
    # 見えるもの
    if not exempt:
        m = re.search(R["object_re"], t)
        if m:
            mk("star_object", f"資料にない星・天体の名前「{m.group(0)}」", "どの星や惑星が見えるかは書かない")
        elif "天の川" in t and not (I.doc["mode"] == "milkyway" and (ss or ts)):
            mk("star_object", "天の川のことを書いている(今回の星の結果は天の川モードではない、または星の印がない)", "天の川のことは書かない")


def _cut(s, words):
    for w in words:
        s = s.replace(w, " ")
    return s


def whole_errors(X, body, sents, present, picks, mre, mk, assert_words):
    """答え全体の検査: 必ず写す決まった文・おすすめ・時刻の順・古い星の言い切り。"""
    I, L = X.star, X.b["lines"]
    used = {i for s in sents for i in s["ids"]}
    for key in ("star_data_time", "star_mode", "star_attribution"):
        if L[key] and L[key]["id"] not in present:
            mk(None, "line_missing", f"決まった文 {key}([{L[key]['id']}])がない", f"[{L[key]['id']}] の文をそのまま写す")
    ec = [x for i, x in list(I.facts.items()) + list(I.counts.items()) if i in used | set(picks) and x["regime"] == "ECMWF"]
    if ec and L["star_regime"] and L["star_regime"]["id"] not in present:
        mk(None, "line_missing", f"ECMWF の夜({ec[0]['label']})を書いているのに、確かさの文([{L['star_regime']['id']}])がない", f"[{L['star_regime']['id']}] の文をそのまま写す")
    for x in L["star_lifts"]:
        if x["fact"] in used | set(picks) and x["id"] not in present:
            mk(None, "line_missing", f"リフト要の地点を書いているのに、運行の文([{x['id']}])がない", f"[{x['id']}] の文をそのまま写す")
    for g in X.b["gaps"]:
        if g["kind"] == "star_not_examined" and g["text"] not in body:
            mk(None, "star_gap_missing", f"聞かれた夜の雲の予報が調べられていないことが書いていない([{g['id']}])", f"[{g['id']}] の文をそのまま写す")
    if len(X.b["when"]["days"]) <= X.R["stars"]["skip_required_days"]:
        for x in L["star_skips"]:
            if x["id"] not in present:
                mk(None, "line_missing", f"星の見送りの文([{x['id']}])がない", f"[{x['id']}] の文をそのまま写す")
    plan_facts = {p["main"]["fact"] for p in X.b["plans"]} | {a["fact"] for p in X.b["plans"] for a in p["adds"]}
    for pid in picks:
        f = I.facts.get(pid)
        if f and not f["main_ok"]:
            mk(None, "pick_not_allowed", f"{f['name']}({f['label']})はおすすめにできない地点", "条件を通った地点だけをすすめる")
        elif f and pid not in plan_facts:
            mk(None, "pick_not_in_plans", f"{pid} が一日の流れの案にない", "資料の案にある地点だけをすすめる")
    # 時刻の順(朝〜日中の山 → 夜の星): 1 行目(結論)を除いて、同じ行の中・案の組の中で、山が先
    lines = {}
    for s in sents:
        lines.setdefault(s["line"], []).append(s)
    nos = sorted(lines)
    first = next((n for n in nos if any(i[0] in "YS" for s in lines[n] for i in s["ids"])), None)
    for n in nos:
        if n == first:
            continue
        ys = [k for k, s in enumerate(lines[n]) if any(i[0] == "Y" for i in s["ids"])]
        st = [k for k, s in enumerate(lines[n]) if any(i in I.facts for i in s["ids"])]
        if ys and st and min(st) < min(ys):
            mk(lines[n][min(st)], "flow_order", "夜の星を、朝〜日中の山より先に書いている", "時刻の順(朝〜日中の山 → 夜の星)に書く")
    marks = [(n, i) for n in nos for s in lines[n] for i in s["ids"]]
    pairs = {}                                   # すすめた星 → 案で組になる、すすめた山
    for p in X.b["plans"]:
        fr = {x["kind"]: x["fact"] for x in p["frames"]}
        if fr["mountain"] in picks and fr["stars"] in picks:
            pairs.setdefault(fr["stars"], []).append(fr["mountain"])
    for sfact, ys in pairs.items():
        at_y = [k for y in ys for k in [next((k for k, (_, i) in enumerate(marks) if i == y), None)] if k is not None]
        at_s = next((k for k, (n, i) in enumerate(marks) if i == sfact and n != first), None)      # 結論の行では、星を先に言ってよい
        if at_y and at_s is not None and at_s < min(at_y):
            mk(None, "flow_order", f"案({'・'.join(ys)} と {sfact})の夜の星を、朝〜日中の山より先に書いている", "時刻の順(朝〜日中の山 → 夜の星)に書く")
            break
    if I.doc["stale"]:
        for s in sents:
            if any(i in I.facts for i in s["ids"]) and _has(_cut(X.star.norm(s["clean"]), X.R["stale"]["ok"]), assert_words):
                mk(s, "stale_assertion", "星の予報が古いのに、言い切ってすすめている", "「古い予報では、○○が候補です」の形で書く")
