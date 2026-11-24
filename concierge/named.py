"""山を名指しした質問(brief --mountain)の答え方の判定。控えの文(fallback)・照合(verify)・Stop フックの 3 つが使う。決定論・通信なし。
利用者の決定 2026-11-25: 名指しの山を答えの主役にする。名指しでない山は並べない(例外の 1 文だけ)。決まりの一覧は docs/answer-checks.md。
資料に項目は足さない(filters.mountains・facts[].named・gaps から出す)。"""
import re

from .brief import LEVEL_RANK, find_mountain

GAP_KINDS = ("named_not_in_list", "named_out_of_range", "named_no_forecast")


def is_named(brief):
    """山を名指しした質問か(棚が使えない回は、今までどおりの答え方)。"""
    return bool(brief["shelf"].get("available") and brief["filters"].get("mountains"))


def facts(brief, day=None):
    """名指しの山の事実(日を渡せばその日だけ)。資料の並びのまま。"""
    return [f for f in brief["facts"] if f["named"] and (day is None or f["date"] == day)]


def gaps(brief):
    """名指しの山の予報が無いことを言う「足りないもの」。"""
    return [g for g in brief["gaps"] if g["kind"] in GAP_KINDS]


def resolve(brief):
    """→ (名指しの山の ID の集合, 答えに出ていなければならない [(山の ID か None, 名指しの文字列)])。
    事実も「予報が無い」の文も無い山(対象の日の予報が範囲に無いときなど)は、必ず出すものに入れない。"""
    ids, need = set(), []
    with_facts = {f["mountain_id"] for f in facts(brief)}
    texts = [g["text"] for g in gaps(brief)]
    for spec in brief["filters"]["mountains"]:
        m = find_mountain(spec, brief.get("mountain_index") or [])
        if m is None:
            if any(f"「{spec}」" in t for t in texts):
                need.append((None, spec))
            continue
        if m["id"] not in ids and (m["id"] in with_facts or any(m["name"] in t for t in texts)):
            need.append((m["id"], m["name"]))
        ids.add(m["id"])
    return ids, need


def winners(fs):
    """名指しの山(1 日ぶん)の中で、すすめる山(主役にできる山のうち、点数がいちばん高く、危険信号の段階がいちばん軽い山)。
    2 座以上なら「差がつかない」。空なら、すすめられる山がない。距離・山の ID・危険信号の数では決めない。"""
    ok = [f for f in fs if f["main_ok"]]

    def key(f):
        return (-f["score"], LEVEL_RANK.get(f["hazard_level"], 0))
    return [f for f in ok if key(f) == min(map(key, ok))]


def calm_others(brief, day):
    """例外の 1 文で触れてよい山(その日の、危険信号の無い、主役にできる名指しでない山)。資料の並び。
    名指しの山のうち予報のあるもの全部に危険信号が出ている日だけ(無ければ空)。"""
    mine = facts(brief, day)
    if not mine or not all(f["hazards"] for f in mine):
        return []
    return [f for f in brief["facts"] if f["date"] == day and not f["named"] and f["main_ok"] and not f["hazards"]]


def _forms(X):
    """山の名前の書き方 → その書き方の山の ID の集合(長い順)。同じ書き方の山が 2 つあることがある。"""
    out = {}
    for n, mid in X.names:
        out.setdefault(n, set()).add(mid)
    return sorted(out.items(), key=lambda x: -len(x[0]))


def _mentions(text, forms):
    """文に出てくる山 → [ID の集合](書き方ごと)。長い名前から取り除きながら探す。"""
    out = []
    for n, mids in forms:
        if n in text:
            out.append(mids)
            text = text.replace(n, " ")
    return out


def errors(X, text, sentences, norm):
    """名指しの決まりに合わない所 → [(文 or None, コード, 詳しく)]。text は印の無い文(決まった文も入ったまま)。Stop フックも使う。"""
    b = X.b
    if not is_named(b):
        return []
    R = X.R["named"]
    ids, need = resolve(b)
    ok = ids | X.q_mountains                                  # 質問に書かれた山は、名前を出してよい
    forms = _forms(X)
    unlisted = [norm(name) for mid, name in need if mid is None]
    out, others, last_named, seen = [], [], -1, set()
    for i, s in enumerate(sentences(text)):
        t = norm(s["clean"])
        for name in unlisted:                                 # 76 座に無い名指し(「大山(鳥取)」など)を、似た名前の山と読まない
            t = t.replace(name, " ")
        found = _mentions(t, forms)
        seen.update(*found)
        if any(m & ids for m in found):
            last_named = i
        other = [m for m in found if not m & ok]
        if other:
            others.append((i, s, other, any(m & ids for m in found)))
    used = False
    for i, s, other, mixed in others:
        if not used and not mixed and i > last_named and _calm_sentence(X, s, other, norm, R):
            used = True                                       # 例外は 1 文だけ
            continue
        out.append((s, "named_other", "名指しでない山を書いている"))
    whole = norm(text)
    for mid, name in need:
        if (mid is not None and mid not in seen) or (mid is None and norm(name) not in whole):
            out.append((None, "named_missing", f"名指しの山「{name}」が答えに出ていない"))
    return out


def _calm_sentence(X, s, other, norm, R):
    """例外の 1 文か: 名指しでない山 1 座だけの「危険信号は出ていません」で、その日の事実と合う(名指しの山の全部に危険信号が出ている日)。"""
    t = norm(s["clean"])
    if len(other) != 1 or not re.search(R["calm_re"], t):
        return False
    tk = X.tokens(X.mask_names(t)[0])
    if tk["nums"] or tk["times"] or any(w in t for w in R["calm_not"]):      # ほかのこと(点数・風など)を書き足さない
        return False
    days = [d["date"] for d in X.b["when"]["days"]]
    if tk["dates"] or tk["wds"]:
        days = [d["date"] for d in X.b["when"]["days"]
                if (int(d["date"][5:7]), int(d["date"][8:])) in tk["dates"] or (not tk["dates"] and d["weekday"] in tk["wds"])]
    return bool(days) and all(any(f["mountain_id"] in other[0] for f in calm_others(X.b, d)) for d in days)


FIX = {"named_missing": "名指しの山は 1 座ずつ全部書く(予報が無い山は、足りないもの [G…] の文で最初に伝える)",
       "named_other": "名指しでない山の名前を消す(名指しの山の全部に危険信号が出ている日だけ、最後に 1 文「なお、この日は○○には危険信号が出ていません。」と書ける。"
                      "見送りのまとめの文は、名指しでない山が入るので写さない)"}

RULES = [
    "答えの形(山を名指しした質問): 最初の文で、名指しの山の中からどれをすすめるか(または、差がつかないこと)を書く → いつ時点の予報か([L…] をそのまま)"
    "→ 名指しの山を 1 座ずつ、同じ項目(点数・危険信号・風・体感・雲の様子)で書く → 名指しの山どうしの違いを 1〜2 文(風の差がわずかなら「差はわずか」)"
    "→ 危険信号の注記 → 分からないこと → 出典([L…] をそのまま)。予報が古いときは、data_time の文を先に置く。",
    "名指しでない山は書かない(見送りのまとめの文も使わない。見送る名指しの山は、山ごとの危険信号の文を写す)。例外は、名指しの山の全部に危険信号が出ていて、同じ日に危険信号の無い山があるときだけ。"
    "名指しの山の話のあと、最後に 1 文「なお、この日は○○には危険信号が出ていません。」(1 座だけ。その山の [Y…] を付ける。点数などは書かない)。",
    "すすめる山は、主役にできる名指しの山のうち、点数がいちばん高く、危険信号の段階がいちばん軽い山。それも同じなら「差がつきません」と書く(距離や並び順で決めない)。主役にできる山が無ければ、見送りと書く。",
    "名指しの山が「点数だけ」(値の無い山)のときは、「点数が低く、くわしい値はありません」と書き、点数と、分かる範囲のこと(危険信号の段階)だけを書く。",
    "名指しの山の予報が無いとき(足りないもの [G…] の「76 座に入っていない」「250km より遠い」「予報はありません」)は、そのことを最初に書き、残りの山だけで答える。残りが 1 座なら、比べずに、その山の説明にする。",
]
