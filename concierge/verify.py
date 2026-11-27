"""verify: 下書きを資料と照らす。合格なら送る文(印を取り除いた最終の文)を返す。決定論・通信なし。
考え方はイキモノビヨリ ikimonobiyori/guide_verify.py・docs/guide-mode.md にそろえた(コードは import しない・写さない)。
検査のコード名・何を止めるか・直し方は docs/answer-checks.md。語の一覧と値は concierge/data/verify.yaml(仮置き)。

下書きの形:
- 種類 A の事実を含む文の終わりに根拠の印 [Y003] など(1 文にいくつでも)。決まった文は資料の文をそのまま写して [L1] など。
- 最後の行に「[おすすめ] Y003, Y005」(すすめた事実の id。なければ「[おすすめ] なし」)。送る文からは取り除く。"""
import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .common import NL, config, md_label, verify_rules

LAST_ANSWER = "last_answer.json"      # 置き場の中。verify が出した最後の文(Stop フックが最後のメッセージと比べる)
HZ = "危険信号"
RANK = {"注意": 1, "警戒": 2, "警戒以上": 2, "危険": 3}
PH = ""           # 決まった文を写した部分の置き換え
MT = ""           # 山の名前の置き換え
HOLE = "\ue002"         # 注記を取り除いた跡(place_note)
DATE_RES = (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), re.compile(r"(\d{1,2})月(\d{1,2})日"),
            re.compile(r"(?<![\d.])(\d{1,2})/(\d{1,2})(?![\d/])"))
WD_RES = (re.compile(r"([月火水木金土日])曜日?"), re.compile(r"\(([月火水木金土日])\)"))
TIME_RE = re.compile(r"(?<![\d.])(\d{1,2}):(\d{2})(?!\d)")
URL_RE = re.compile(r"https?://\S+|www\.\S+")


def day_forms(ds):
    """'2026-11-29' → その日を表す書き方(「11月29日(日)」)。"""
    return [md_label(date.fromisoformat(ds))]


def _norm(s):
    s = unicodedata.normalize("NFKC", s or "").replace("°C", "℃")
    return re.sub(r"(?<=\d),(?=\d{3})", "", s)


def _num_re(units):
    alts = "|".join(re.escape(u) for u in sorted(units, key=len, reverse=True))
    return re.compile(r"(約)?\s*([-−]?\d+(?:\.\d+)?)\s*(" + alts + r")?")


class Ctx:
    """資料から作った、照らすための索引。"""

    def __init__(self, brief):
        self.b = brief
        self.R = verify_rules()
        self.num_re = _num_re(self.R["numbers"]["units"])
        self.ids = {}
        for f in brief["facts"]:
            self.ids[f["id"]] = ("Y", f)
        for k in brief["cards"]:
            self.ids[k["id"]] = ("K", k)
        for g in brief["gaps"]:
            self.ids[g["id"]] = ("G", g)
        for x in (brief.get("comparisons") or []) + (brief.get("named_gaps") or []):
            self.ids[x["id"]] = ("C", x)
        for x in brief["hazard_counts"]:
            self.ids[x["id"]] = ("N", x)
        L = brief["lines"]
        self.star = None                         # 星の部分の索引(星の無い資料では None)
        if brief.get("stars"):
            from .stars_verify import Index
            self.star = Index(brief, _norm)
            self.num_re = _num_re(self.R["numbers"]["units"] + self.R["stars"]["units"])
            for f in brief["stars"]["facts"]:
                self.ids[f["id"]] = ("S", f)
            for x in brief["stars"]["counts"]:
                self.ids[x["id"]] = ("T", x)
            for f in self.star.hl.values():          # 見どころ(新しい出力だけ)
                self.ids[f["id"]] = ("M" if f["kind"] == "star_shower" else "H", f)
        self.lines = [x for x in (L["data_time"], L["coverage"], L["lead_time"], L["attribution"], L.get("hazard_note"), L.get("refresh")) if x] + list(L["hazards"]) + list(L.get("skips") or [])
        if self.star:
            from .stars import all_lines
            self.lines += all_lines(brief)
        for x in self.lines:
            self.ids[x["id"]] = ("L", x)
        self.target_days = [date.fromisoformat(d["date"]) for d in brief["when"]["days"]]
        self.target_wd = {d["weekday"] for d in brief["when"]["days"]}
        # 山の名前: 76 座の全部(資料の mountain_index)→ 置き換えの表(長い順)
        self.names = []
        for m in brief.get("mountain_index") or []:
            n = m["name"]
            forms = {n, n.split("(")[0]}
            inner = n[n.find("(") + 1:-1] if "(" in n and n.endswith(")") else ""
            if inner and re.search(r"(山|岳|峰|嶺|頭)$", inner):
                forms.add(inner)
            for x in forms:
                if x:
                    self.names.append((_norm(x), m["id"]))
        self.names.sort(key=lambda x: -len(x[0]))
        self.in_brief = {f["mountain_id"] for f in brief["facts"]}
        names_in_brief = set()
        for c in brief["candidates"]:
            names_in_brief.update(c["outside_top_names"])
            names_in_brief.update(c.get("outside_skip_names") or [])
        for g in brief["gaps"]:
            names_in_brief.update(g["say"])
        self.in_brief |= {mid for n, mid in self.names if n in {_norm(x) for x in names_in_brief}}
        self.question = _norm(brief.get("question") or "")
        self.named_specs = _norm(NL.join(brief["filters"].get("mountains") or []))      # 名指しの文字列(76 座に無い山は「足りないもの」の文で名前を出す)
        self.q_mountains = {mid for n, mid in self.names if n in self.question}

    # -- 表記の解析 --
    def tokens(self, text):
        """→ {dates: {(月,日)}, wds: {曜}, times: {(時,分)}, nums: [(約, 値, 単位, 後ろの文字)], urls}。"""
        t = _norm(text)
        out = {"dates": set(), "wds": set(), "times": set(), "nums": [], "urls": URL_RE.findall(t)}
        t = URL_RE.sub(" ", t)
        for i, rx in enumerate(DATE_RES):
            for m in rx.finditer(t):
                g = m.groups()
                out["dates"].add((int(g[1]), int(g[2])) if i == 0 else (int(g[0]), int(g[1])))
            t = rx.sub(" ", t)
        if "土日" in t:
            out["wds"].update({"土", "日"})
            t = t.replace("土日", " ")
        for rx in WD_RES:
            out["wds"].update(rx.findall(t))
            t = rx.sub(" ", t)
        for m in TIME_RE.finditer(t):
            out["times"].add((int(m.group(1)), int(m.group(2))))
        t = TIME_RE.sub(" ", t)
        for m in self.num_re.finditer(t):
            try:
                v = Decimal(m.group(2).replace("−", "-"))
            except InvalidOperation:
                continue
            after = t[m.end():m.end() + 3]
            out["nums"].append((bool(m.group(1)), v, m.group(3), after))
        return out

    def allowed(self, marks):
        """印の事実の「書いてよい表記」から、書いてよい数・日付・曜日・時刻・山を集める。"""
        a = {"dates": set(), "wds": set(), "times": set(), "nums": set(), "values": set(), "mountains": set(), "hazards": set()}
        texts = []
        for mid in marks:
            kind, x = self.ids[mid]
            if kind in ("S", "T", "H", "M"):
                texts += self.star.texts(mid, kind, x, {m for m in marks if m[0] == "Y"})
            elif kind == "Y":
                texts += x["say"]
                a["mountains"].add(x["mountain_id"])
                a["hazards"].update((h["label"], h["level"]) for h in x["hazards"])
            elif kind == "C":
                texts += x["say"] + [x["label"]]
                a["mountains"].add(x["mountain_id"])
                a["mountains"].update(x.get("mountains") or [])
            elif kind == "N":
                texts += x["say"] + day_forms(x["date"])
            elif kind == "K":
                texts += x["say"] + [x["text"]]
                a["mountains"].update(x["mountains"])
            elif kind == "G":
                texts += x["say"] + [x["text"]]
            else:
                texts.append(x["text"])
                if x is self.b["lines"]["data_time"] and self.b["shelf"].get("stale"):      # 古い予報: 「丸1日以上前」と言ってよい(実際の古さまで)
                    texts += [f"丸{n}日以上前" for n in range(1, int(self.b["shelf"]["age_hours"] // 24) + 1)]
        if not any(self.ids[m][0] in ("Y", "C", "N", "S", "T", "H", "M") for m in marks):
            for d in self.target_days:
                a["dates"].add((d.month, d.day))
            a["wds"] |= self.target_wd
        for s in texts:
            tk = self.tokens(s)
            a["dates"] |= tk["dates"]
            a["wds"] |= tk["wds"]
            a["times"] |= tk["times"]
            for ap, v, u, _ in tk["nums"]:
                a["nums"].add((ap, v, u))
                a["values"].add(v)
            for n, mid in self.names:
                if n in _norm(s):
                    a["mountains"].add(mid)
        return a

    def mask_names(self, t):
        """山の名前を置き換える。→ (置き換えた文, 出てきた山の ID の集合)。"""
        found = set()
        for n, mid in self.names:
            if n in t:
                found.add(mid)
                t = t.replace(n, MT)
        return t, found


def split_draft(text, R):
    """→ (本文の行, おすすめの id のリスト or None)。"""
    body, picks = [], None
    head = R["draft"]["picks_heading"]
    for line in (text or "").replace("\r\n", NL).split(NL):
        s = line.strip()
        if s.startswith(head):
            rest = s[len(head):].strip()
            picks = [] if rest in ("", "なし", "(なし)") else [x for x in re.split(r"[\s,、，]+", rest) if x]
            continue
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    return body, picks


def sentences(body_text, mre):
    """本文 → [{line, text(印つき), clean(印なし), ids}]。行の頭の印は前の文のもの。"""
    out = []
    for ln, line in enumerate(body_text.split(NL), 1):
        if not line.strip():
            continue
        segs = re.findall(r"[^。！？!?]+[。！？!?]?", line)
        for s in segs:
            m = re.match(rf"^\s*(?P<marks>(?:{mre.pattern}\s*)+)(?P<rest>.*)$", s)
            if m and out:
                out[-1]["text"] += m.group("marks").strip()
                out[-1]["ids"] = mre.findall(out[-1]["text"])
                s = m.group("rest")
            if not s.strip():
                continue
            ids = mre.findall(s)
            clean = re.sub(r"\s*" + mre.pattern, "", s).strip()
            clean = re.sub(r"^(?:[-*・#>\s]+|\d{1,2}[.)．]\s+|[①-⑨]\s*)+", "", clean).replace("**", "").strip()
            if clean:
                out.append({"line": ln, "text": s.strip(), "clean": clean, "ids": ids})
    return out


def _err(code, s, detail, fix):
    return {"code": code, "line": (s or {}).get("line", 0), "sentence": (s or {}).get("clean", "")[:120], "detail": detail, "fix": fix}


def _has_any(t, words):
    return [w for w in words if w in t]


def _cut(s, words):
    for w in words:
        s = s.replace(w, " ")
    return s


def _clauses(t):
    return [c for c in re.split(r"[、,;；]", t) if c.strip()]


def _superlative_topics(t, CP):
    """最上級の語のある文 → [(何を比べているか, その語のある節)]。比べる対象の語が文にないものは入れない。
    比べる対象は、最上級の語のあとの語(いちばん「弱い」)→ 同じ節の語 → 文の中の語、の順に決める。"""
    out = []
    t = _cut(t, CP["ok"])
    words = sorted(CP["superlatives"], key=len, reverse=True)
    rx = re.compile("|".join(re.escape(w) for w in words))
    score_any = any(w in t for w in CP["topics"]["score"])
    for c in _clauses(t):
        for m in rx.finditer(c):
            near = m.group(0) + c[m.end():m.end() + CP["window"]]
            topic = None
            for key in ("near", "far", "wind_weak", "wind_strong"):
                if any(w in near for w in CP["topics"][key]):
                    topic = key
                    break
            if topic in ("wind_weak", "wind_strong") and not any(w in t for w in CP["topics"]["wind"]):
                topic = "other"
            if topic is None and any(w in near for w in CP["topics"]["high_low"]):
                low = any(w in near for w in CP["topics"]["low"])
                in_clause = any(w in c for w in CP["topics"]["score"])
                blocked = any(w in c for w in CP["topics"]["not_score"])
                topic = ("score_low" if low else "score") if (in_clause or score_any) and not (blocked and not in_clause) else "other"
            if topic is None and any(w in near for w in CP["topics"]["other"]):
                topic = "other"
            if topic is None:
                for scope in (c, t):
                    if any(w in scope for w in CP["topics"]["wind"]):
                        topic = "wind"
                    elif any(w in scope for w in CP["topics"]["score"]):
                        topic = "score"
                    elif any(w in scope for w in CP["topics"]["near"]):
                        topic = "near"
                    elif any(w in scope for w in CP["topics"]["far"] + CP["topics"]["high_low"]):
                        topic = "other"
                    if topic:
                        break
            if topic:
                out.append((topic, c))
    return out


def _check_comparisons(X, s, t, ids, errs):
    """比べる文(いちばん・最も など)を、比べた結果の事実 [C…] と順位の事実に照らす。"""
    CP = X.R["compare"]
    tn = t
    for w, mid in X.names:                   # 山の名前を ID の印に置き換える(名前の中の「高」「風」などを見ない。節ごとの山が分かる)
        tn = tn.replace(w, f"\x02{mid}\x03")
    topics = _superlative_topics(tn, CP)

    def mids(text):
        return list(dict.fromkeys(re.findall(r"\x02(m\d{3})\x03", text)))

    ys = [X.ids[i][1] for i in ids if X.ids[i][0] == "Y"]
    cs = [X.ids[i][1] for i in ids if X.ids[i][0] == "C"]
    for topic, clause in topics:
        who = mids(clause) or mids(tn) or list(dict.fromkeys(f["mountain_id"] for f in ys))
        if topic == "score":
            if any(w in t for w in CP["score_skip"]):
                continue
            top = [f for f in ys if f.get("rank") == 1]
            ok = bool(who) and all(any(f["mountain_id"] == m for f in top) for m in who)
            if not ok:
                errs.append(_err("comparison_mismatch", s, "「点数がいちばん高い」に、その日の順位が 1 位の事実の印がない(または 1 位でない山を言っている)",
                                 "1 位の山の事実の印を付けるか、順位の表記で書く"))
            elif len(who) == 1 and not any(f["mountain_id"] == who[0] and (f.get("rank_ties") or 1) == 1 for f in top):
                errs.append(_err("comparison_tied", s, "同点の山があるのに、1 つの山だけを「いちばん高い」と言っている",
                                 "順位の表記(「1位(同点 5 座)」)で書く"))
            continue
        kind = {"wind_weak": "ridge_wind_min", "wind": "ridge_wind_min", "near": "nearest"}.get(topic)
        hit = [x for x in cs if x["kind"] == kind]
        if not hit:
            errs.append(_err("comparison_unmarked", s, "最上級の比べ方に、比べた結果の事実の印 [C…] がない",
                             "資料の「比べた結果」にあるものだけを [C…] の印つきで書く(ほかは数字だけを書く)"))
            continue
        if len(who) != 1 or who[0] not in {x["mountain_id"] for x in hit}:
            errs.append(_err("comparison_mismatch", s, "比べた結果の事実の山と、文の山が合わない(または、どの山のことか分からない)",
                             "1 つの文に 1 つの山だけを書き、その山の事実の印 [Y…] と [C…] を付ける"))
            continue
        days = {f["date"] for f in ys if f["mountain_id"] == who[0]}
        if days and not days & {x["date"] for x in hit if x["mountain_id"] == who[0]}:
            errs.append(_err("comparison_mismatch", s, "比べた結果の事実の日と、文の山の日が合わない", "同じ日の事実の印を付ける"))
        if not any(w in t for w in CP["scope"]):
            errs.append(_err("comparison_scope", s, "何の中でいちばんかが書いていない(比べたのはおすすめの候補の中だけ)",
                             "「おすすめの候補の中で」と書く"))
    # 同点のある順位を、同点と分からない形で書いていないか
    for n in re.findall(r"(\d+)\s*(?:位|番目)", tn):
        hit = [f for f in ys if f.get("rank") == int(n)]
        if hit and all((f.get("rank_ties") or 1) > 1 for f in hit) and "同点" not in t:
            errs.append(_err("rank_tie_hidden", s, f"同点のある順位({n}位)を、同点と分からない形で書いている",
                             f"「{n}位(同点 {hit[0].get('rank_ties')} 座)」の形で書く"))


def _check_named_gap(X, s, t, ids, errs):
    """「差はわずか」を、名指しの山どうしの差の事実 [C…](kind = peak_wind_gap)と照らす。"""
    G = X.R["named_gap"]
    tn = _cut_clear(_cut(t, G["ok"]))
    if not (any(w in tn for w in G["diff"]) and any(w in tn for w in G["small"])):
        return
    if not any(w in tn for w in G["topic"]) and not any(X.ids[i][1].get("kind") == "peak_wind_gap" for i in ids if X.ids[i][0] == "C"):
        return
    hit = [X.ids[i][1] for i in ids if X.ids[i][0] == "C" and X.ids[i][1]["kind"] == "peak_wind_gap"]
    if not hit:
        errs.append(_err("gap_unmarked", s, "風の差が小さいと言っているのに、名指しの山どうしの差の印 [C…] がない",
                         "資料の「名指しの山どうしの差」にある印を付ける"))
    elif not all(x["small"] for x in hit):
        errs.append(_err("gap_mismatch", s, "「差はわずか」ではない差を、わずかだと言っている", "差の数字だけを書く"))


def _cut_clear(t):
    """「雲はほとんど無い」の部分を取り除く(「ほとんど」を、危険信号の割合の語や、風の差の語と読み違えないため)。"""
    return re.sub(verify_rules()["cloud"]["clear_re"], " ", t)


def _cloud_nums(text, CL):
    out = set()
    for m in re.finditer(CL["number_re"], _norm(text)):
        v = Decimal("一二三四五六七八九".index(m["v"]) + 1) if m["v"] in "一二三四五六七八九" else Decimal(m["v"])
        out.add(v * 10 if m["u"] == "割" else v)
    return out


def _cloud_value_nums(facts, CL):
    """事実の雲量(補正後)の数: そのままの値・書いてよい表記・1 % に丸めた値。"""
    out = set()
    for f in facts:
        for v in f["values"]:
            if v["key"] == "cloud_pct":
                out |= {Decimal(str(v["value"])), Decimal(str(v["value"])).quantize(Decimal("1"), rounding=ROUND_HALF_UP)}
                out |= {n for s in v["say"] for n in _cloud_nums(s, CL)}
    return out


def cloud_errors(X, sents, facts_of, carry=False):
    """雲の書き方(生の雲量が 0 % の山 = 事実の cloud_clear)の検査 → [(文, コード, 詳しく)]。Stop フックも使う。
    節ごとに、どの山のどの日かを決める(節に無ければ、文の中の前の節。carry なら前の文も)。facts_of(文) はその文の事実。"""
    CL = X.R["cloud"]
    out, mids, days = [], set(), (set(), set())
    for s in sents:
        if not carry:
            mids, days = set(), (set(), set())
        facts = facts_of(s)
        tn = _marked_names(X, _cut(_without_sites(X, _norm(s["clean"])), CL["not_cloud"]))
        tn = re.sub(r"(\x03)[、,](?=\x02)", r"\1・", tn)                 # 「A、B は」の並びを 1 つの節に
        tn = re.sub(r"(雲量?[はがも])[、,]", r"\1", tn)                   # 「雲量は、18.6 %」を 1 つの節に
        whole = set(re.findall(r"\x02(m\d{3})\x03", tn))
        for clause in _clauses(tn):
            here = set(re.findall(r"\x02(m\d{3})\x03", clause))
            tk = X.tokens(re.sub(r"\x02m\d{3}\x03", " ", clause))
            mids = here or mids
            days = (tk["dates"], tk["wds"]) if tk["dates"] or tk["wds"] else days
            who = mids or whole
            if carry and not who:                                      # どの山のことか分からない(迷う場合は通す)
                continue
            fs = [f for f in facts if f["mountain_id"] in who] if who else list(facts)
            if days[0] or days[1]:
                on = [f for f in fs if f["weekday"] in days[1] or (int(f["date"][5:7]), int(f["date"][8:])) in days[0]]
                fs = on if on or carry else fs                          # carry のとき、言っている日の事実が無ければ見ない(迷う場合は通す)
            clear = [f for f in fs if f.get("cloud_clear")]
            other = [f for f in fs if f.get("cloud_clear") is False]
            if other and re.search(CL["clear_re"], clause):
                out.append((s, "cloud_mismatch", f"雲の印の無い山({other[0]['name']}・{other[0]['label']})に「雲はほとんど無い」と書いている"))
            if not clear:
                continue
            if re.search(CL["assert_re"], _cut(clause, CL["assert_ok"])):
                out.append((s, "cloud_assertion", f"予報なのに、空に雲が無いと言い切っている({clear[0]['name']}・{clear[0]['label']})"))
            rest = re.sub(CL["other_pct_re"], " ", _cut_clear(clause))
            if "雲" not in rest:
                continue
            ok = _cloud_value_nums([f for f in fs if not f.get("cloud_clear")], CL) - _cloud_value_nums(clear, CL)
            if _cloud_nums(re.sub(r"\x02m\d{3}\x03", " ", rest), CL) - ok:
                out.append((s, "cloud_number", f"雲の印の付いた山({clear[0]['name']}・{clear[0]['label']})に、雲量の数字を書いている"))
    return out


def _without_sites(X, t):
    """星の地点の名前を取り除く(「石割山(山中湖村)」の中の山の名前を読まない)。星の無い資料ではそのまま。"""
    return X.star.mask(t)[0] if X.star else t


CLOUD_FIX = {"cloud_number": "雲量の数字を書かず、「雲はほとんど無い予報です」のように言葉で書く(比べるときは、数字を書く山の名前を同じ節に書く)",
             "cloud_assertion": "「快晴」「雲ひとつない」と言い切らず、「雲はほとんど無い予報です」と書く",
             "cloud_mismatch": "雲の印の無い山は、雲量の数字を「書いてよい表記」で書く(予報の無い山には雲のことを書かない)"}


def _check_cloud(X, sents, errs):
    def facts_of(s):
        return [X.ids[i][1] for i in s["ids"] if i in X.ids and X.ids[i][0] == "Y"]
    for s, code, detail in cloud_errors(X, sents, facts_of):
        errs.append(_err(code, s, detail, CLOUD_FIX[code]))


def _check_named(X, body, mre, errs):
    """山を名指しした質問(利用者の決定 2026-11-25): 名指しの山が答えに出ているか、名指しでない山を並べていないか。決まりは concierge/named.py。"""
    from . import named as N
    for s, code, detail in N.errors(X, strip_marks(body, mre), lambda t: sentences(t, mre), _norm):
        errs.append(_err(code, s, detail, N.FIX[code]))


def _check_lone_number(X, body, errs):
    """山を名指しで比べる答えで、番号が 1 行だけに付いていないか(比べる山の片方にだけ番号が付くのを止める)。"""
    if len(dict.fromkeys(X.b["filters"].get("mountains") or [])) < 2:
        return
    heads = [x for x in body.split(NL) if NUMBER_HEAD.match(x)]
    if len(heads) == 1:
        errs.append(_err("number_lone", {"line": 0, "clean": heads[0]}, "比べる山のうち 1 座にだけ番号が付いている",
                         "番号を全部の山に付けるか、全部から外す"))


def stale_assertions(text):
    """古い予報のときに言い切ってはいけない言い方(「おすすめします」など)→ [(文, 語)]。Stop フックも使う。"""
    S = verify_rules()["stale"]
    mre = re.compile(verify_rules()["draft"]["marker_re"])
    out = []
    for s in sentences(text, mre):
        t = _cut(_norm(s["clean"]), S["ok"])
        bad = _has_any(t, S["assert"])
        if not bad and _has_any(t, S["weak"]) and S["candidate"] not in t:
            bad = _has_any(t, S["weak"])
        if bad:
            out.append((s, bad[0]))
    return out


def _check_stale(X, body, errs):
    """予報が古いときの書き方(利用者の決定 2026-11-25): 最初の文は data_time、言い切らない、最後に新しくする方法。"""
    L, mre = X.b["lines"], re.compile(X.R["draft"]["marker_re"])
    if not X.b["shelf"].get("stale"):
        return
    first = L["data_time"]
    if first and not mre.sub("", body).lstrip(" \t　" + NL + "-*・>").startswith(first["text"]):
        errs.append(_err("stale_first", None, "予報が古いのに、答えの最初の文が予報の時点(古さ)の決まった文でない",
                         f"[{first['id']}] の文を最初に置き、結論はその次に書く"))
    for s, word in stale_assertions(mre.sub("", body)):
        errs.append(_err("stale_assertion", s, f"予報が古いのに「{word}」と言い切っている", "「古い予報では、○○が候補です」の形で書く"))
    ref, tail_ok = L.get("refresh"), L["attribution"]
    if ref and ref["text"] in body:
        tail = body.split(ref["text"])[-1]
        for x in [tail_ok, L.get("star_attribution")]:      # 帰属の文(星の質問では、星の帰属の文も)
            if x:
                tail = tail.replace(x["text"], "")
        if mre.sub("", tail).strip(" \t　" + NL):
            errs.append(_err("stale_refresh_last", None, "新しくする方法の文のあとに、ほかの文がある(あとに書けるのは帰属の文だけ)", f"[{ref['id']}] の文を最後に置く"))
    elif ref:
        errs.append(_err("line_missing", None, f"決まった文 refresh([{ref['id']}])がない(予報が古い)", f"[{ref['id']}] の文を、答えの最後にそのまま写す"))


def _marked_names(X, t):
    """山の名前を ID の印(\x02m001\x03)に置き換える(節ごとの山が分かる)。"""
    for w, mid in X.names:
        t = t.replace(w, f"\x02{mid}\x03")
    return t


def _clause_facts(X, clause, whole, ys):
    """節の中の山と日の事実。節に山がなければ文の中の山、それもなければ印の事実の全部。日も同じ(節に日がなければ絞らない)。"""
    mids = set(re.findall(r"\x02(m\d{3})\x03", clause)) or set(re.findall(r"\x02(m\d{3})\x03", whole))
    out = [f for f in ys if f["mountain_id"] in mids] if mids else list(ys)
    tk = X.tokens(re.sub(r"\x02m\d{3}\x03", " ", clause))
    if tk["dates"] or tk["wds"]:
        out = [f for f in out if f["weekday"] in tk["wds"] or (int(f["date"][5:7]), int(f["date"][8:])) in tk["dates"]] or out
    return out


def _level_claims(text, W):
    """種類を書かずに段階だけを言っているところ → [(言い方の種類 at_least / until / exact, 段階, 打ち消しか, 位置)]。言い方の形は verify.yaml。"""
    out, t = [], text
    lvs = "|".join(re.escape(x) for x in W["hazard_levels"] if not x.endswith("以上"))
    kinds = "|".join(re.escape(k) for k in W["hazard_kinds"] if k != HZ)
    for mode in ("at_least", "until", "exact"):
        for form in W["hazard_level_forms"][mode]:
            rx = re.compile(form.replace("{lv}", f"(?P<lv>{lvs})"))
            for m in list(rx.finditer(t)):
                before = t[:m.start("lv")]
                if m.start() == m.start("lv") and re.search(rf"(?:{kinds})[のがはも:]?$", before):      # 「強風警戒の危険信号」は種類がある
                    continue
                neg = bool(re.search(W["hazard_level_not_re"], t[m.end():]))
                out.append((mode, m.group("lv"), neg, m.start()))
                t = t[:m.start()] + "\x00" * (m.end() - m.start()) + t[m.end():]      # 同じところを 2 回見ない
    return sorted(out, key=lambda x: x[3])


def _level_ok(mode, lv, neg, f):
    """事実 f のいちばん重い段階が、言い方と合うか。簡易行の「警戒以上」は、上の段階が分からないので「まで」とは言えない。"""
    worst = RANK.get(f["hazard_level"], 0)
    open_ended = any(h["level"] == "警戒以上" for h in f["hazards"])
    if neg:                      # 「警戒以上の危険信号は出ていません」
        return worst < RANK[lv] if mode == "at_least" else mode == "exact" and not open_ended and all(h["level"] != lv for h in f["hazards"])
    if mode == "at_least":
        return worst >= RANK[lv]
    return worst == RANK[lv] and not (mode == "until" and open_ended)


def _check_level_only(X, s, t, ids, errs):
    """種類を書かずに段階だけを言う文(「危険信号が警戒まで出ています」): 印の事実のいちばん重い段階と照らす。"""
    tn = _marked_names(X, t)
    ys = [X.ids[i][1] for i in ids if X.ids[i][0] == "Y"]
    ns = [X.ids[i][1] for i in ids if X.ids[i][0] == "N"]
    for clause in _clauses(tn):
        for mode, lv, neg, _ in _level_claims(clause, X.R["words"]):
            if ns and not (ys and re.search(r"\x02m\d{3}\x03", clause)):      # 件数の事実 [N…] の文: 山を名指ししていない節は件数と照らす
                key = {("at_least", "警戒"): "total", ("exact", "警戒"): "warning", ("exact", "危険"): "danger", ("at_least", "危険"): "danger"}.get((mode, lv))
                told = _has_any(tn, _universals(X)) or re.search(_count_re(X), tn)      # 数・「どれも」は _check_hazard_counts で見る
                if not told and not (key and all((n["all"][key] == 0) == neg for n in ns)):
                    errs.append(_err("hazard_count_mismatch", s, f"危険信号の段階「{lv}」の山があるかどうかが、件数の事実と合わない",
                                     "件数の事実 [N…] の「書いてよい言い方」で書く"))
                continue
            facts = _clause_facts(X, clause, tn, ys)
            if not facts or not all(_level_ok(mode, lv, neg, f) for f in facts):
                tail = {"at_least": "以上", "until": "まで", "exact": ""}[mode]
                errs.append(_err("hazard_mismatch", s, f"危険信号の段階「{lv}{tail}{'(出ていない)' if neg else ''}」が、印の事実のいちばん重い段階と合わない",
                                 "印の事実の危険信号のいちばん重い段階を書く(種類を書くなら「強風警戒」のように書く)"))


def _count_re(X):
    return r"(\d+)\s*(?:" + "|".join(re.escape(u) for u in X.R["hazard_count"]["units"]) + ")"


def _count_example(X):
    """件数の文の例: 資料にあれば、その日の件数の事実から(印つき)。"""
    n = next(iter(X.b["hazard_counts"]), None)
    return f"例: {n['label']}は、{n['say'][0]}です。[{n['id']}]" if n else "例: 危険信号が警戒以上の山は 31 座"


def _universals(X):
    return X.R["hazard_count"]["universal"]


def _named_days(X, t):
    """文に書かれた日(日付・曜日)の、対象の日の中の date の集合。書いていなければ None。"""
    tk = X.tokens(X.mask_names(t)[0])
    if not tk["dates"] and not tk["wds"]:
        return None
    days = X.b["when"]["days"]
    out = [d for d in days if (int(d["date"][5:7]), int(d["date"][8:])) in tk["dates"]]
    rest = tk["wds"] - {d["weekday"] for d in out}
    return {d["date"] for d in out} | {d["date"] for d in days if d["weekday"] in rest}


def _check_hazard_counts(X, s, t, ids, errs):
    """危険信号の件数(○ 座)と「どれも・全部」の文を、件数の事実 [N…] と照らす。合うかどうかを決められない言い方は止める。"""
    W, CN = X.R["words"], X.R["hazard_count"]
    t = _cut_clear(t)
    fix = "「どれも」などをやめて、日を書き、件数の事実 [N…] の「書いてよい言い方」で件数を書く(例: 日曜は、危険信号が警戒以上の山は 30 座です)"
    tn = re.sub(r"\x02m\d{3}\x03", MT, _marked_names(X, t))
    tn = re.sub(r"同点\s*\d+\s*座", " ", tn)               # 順位の表記の数
    kinds = [k for k in W["hazard_kinds"] if k != HZ]
    plain = tn.replace(HZ, "　　　　")                     # 「危険信号」の「危険」を段階と読まない(長さは変えない)
    lv_re = re.compile("|".join(re.escape(x) for x in sorted(CN["levels"], key=len, reverse=True)))
    hazard = HZ in tn or any(k in tn for k in kinds) or lv_re.search(plain)
    ns = {X.ids[i][1]["date"]: X.ids[i][1] for i in ids if X.ids[i][0] == "N"}
    ys = [i for i in ids if X.ids[i][0] == "Y"]
    named = _named_days(X, t)

    def err(code, detail):
        errs.append(_err(code, s, detail, fix))

    if ns and not ys and any(k in tn for k in kinds):
        err("hazard_count_mismatch", "件数の事実は、危険信号の種類(強風・低体温症・雷)ごとの数を持たない")
    # 割合・ぼかした言い方(割合を件数と照らすことはしない。印があってもなくても止める)
    vague = _has_any(tn, CN["vague"])
    if hazard and vague:
        errs.append(_err("hazard_vague", s, f"危険信号の文に、割合・ぼかした言い方「{'・'.join(vague[:3])}」がある",
                         "件数の文を写す(" + _count_example(X) + ")"))
    # 「どれも」「全部」
    cut = _cut(tn, CN["universal_ok"])
    if hazard and _has_any(cut, _universals(X)) and not _listed_universal_true(X, t, ids):
        have = {n["date"] for n in X.b["hazard_counts"]}
        need = have if named is None else named
        if not ns:
            err("hazard_universal_unmarked", "「どれも・全部」と危険信号を 1 文に書いているのに、件数の事実の印 [N…] がない(資料に載っている山は枠の中だけ)")
        elif not need or not need <= set(ns) or not _universal_true(X, cut, kinds, lv_re, list(ns.values())):
            err("hazard_universal_mismatch", "「どれも・全部」の言っている範囲・段階・日が、件数の事実と合わない(または、合うかどうかを決められない)")
    # 件数
    nums = list(re.finditer(_count_re(X), plain))
    if not nums or not (ns or hazard):
        return
    if not ns:
        err("hazard_count_unmarked", "危険信号の文に山の数を書いているのに、件数の事実の印 [N…] がない")
        return
    if len(ns) > 1 or (named is not None and named != set(ns)) or (named is None and "週末" in tn and len(X.b["hazard_counts"]) > 1):
        err("hazard_count_mismatch", "どの日の件数かが、件数の事実と合わない(1 つの文に 1 つの日だけを書く)")
        return
    n = next(iter(ns.values()))
    value = {"警戒以上": n["all"]["total"], "警戒": n["all"]["warning"], "危険": n["all"]["danger"], "基準": n["above"]}
    what = re.compile(lv_re.pattern + "|基準")
    prev = 0
    for i, m in enumerate(nums):
        end = nums[i + 1].start() if i + 1 < len(nums) else len(plain)
        seg, tail = plain[prev:m.start()], plain[m.end():end]
        hit = (list(what.finditer(seg)) or list(lv_re.finditer(plain[:m.start()])) or list(lv_re.finditer(tail))[:1])
        near = seg[list(what.finditer(seg))[-1].end():] if what.search(seg) else seg
        ok = bool(hit) and value[hit[-1].group(0)] == int(m.group(1)) and not any(k in seg for k in kinds) \
            and not _has_any(near, CN["not_words"]) and (what.search(seg) or not any(k in tail for k in kinds))
        if not ok:
            err("hazard_count_mismatch", f"山の数「{m.group(0)}」が、件数の事実の段階ごとの数と合わない(または、何の数か決められない)")
        prev = m.end()


def _listed_universal_true(X, t, ids):
    """山の名前を並べた「A・B・C は、どれも強風危険…」が、並べた山の全部(印の事実の全部)に合うか。
    名前を並べていない文・件数の印 [N…] のある文・合うかどうかを決められない文は False(今までどおり件数の事実と照らす)。"""
    W, CN = X.R["words"], X.R["hazard_count"]
    ys = [X.ids[i][1] for i in ids if X.ids[i][0] == "Y"]
    tid = _cut(_marked_names(X, t), CN["universal_ok"])
    uni = "|".join(re.escape(w) for w in _universals(X))
    item = r"\x02m\d{3}\x03"
    lists = re.findall(rf"({item}(?:{CN['listed_sep']}{item})+){CN['listed_tail']}(?:{uni})", tid)
    if not ys or any(X.ids[i][0] == "N" for i in ids) or not lists or len(lists) != len(re.findall(uni, tid)) or _has_any(tid, CN["listed_not"]):
        return False
    # 並べた山の全部に印があるか(日を書いていれば、書いた日ごとに)
    mids = {m for x in lists for m in re.findall(r"m\d{3}", x)}
    days = _named_days(X, t)
    if _has_any(t, CN["listed_all_days"]):
        days = {d["date"] for d in X.b["when"]["days"]}
    have = {(f["mountain_id"], f["date"]) for f in ys}
    if not mids <= {m for m, _ in have} or (days is not None and (not days or not all((m, d) in have for m in mids for d in days))):
        return False
    # どの印の事実も、文の危険信号(種類と段階)を持っているか
    plain = re.sub(item, MT, tid)
    kinds = "|".join(re.escape(k) for k in W["hazard_kinds"] if k != HZ)
    lvs = "|".join(re.escape(x) for x in W["hazard_levels"])
    said = []

    def take(m):                                  # 「強風・低体温症危険」は、どちらも危険
        said.extend((k, m.group("lv")) for k in re.findall(kinds, m.group("ks")))
        return " "
    rest = re.sub(rf"(?P<ks>(?:(?:{kinds})[・とや、])*(?:{kinds}))\s*[のが:は]?\s*(?P<lv>{lvs})", take, plain)
    said += [(k, None) for k in re.findall(kinds, rest)]
    claims = _level_claims(plain, W)              # 種類を書かない段階(節ごとの照らしは _check_level_only)
    for form in W["hazard_level_forms"]["at_least"] + W["hazard_level_forms"]["until"] + W["hazard_level_forms"]["exact"]:
        rest = re.sub(form.replace("{lv}", f"(?:{lvs})"), " ", rest)
    if re.search(r"警戒|危険|注意(?![がしを])", rest.replace(HZ, " ")):     # 何の段階か決められない(「注意が要ります」「注意して」は段階ではない)
        return False
    for c in _clauses(plain):
        if (HZ in c or re.search(kinds + "|" + lvs, c)) and _has_any(c, CN["listed_not_clause"]):
            return False
    for f in ys:
        hz = {(h["label"], h["level"]) for h in f["hazards"]}
        if not hz or not all((k, lv) in hz or (lv is None and any(k == x for x, _ in hz)) for k, lv in said):
            return False
        if not all(_level_ok(mode, lv, neg, f) for mode, lv, neg, _ in claims):
            return False
    return True


def _universal_true(X, t, kinds, lv_re, ns):
    """「どれも…」の文が件数の事実 ns(日ごと)と合うか。決められないときは False。
    決められるのは、基準点以上の山の全部について、危険信号が出ている・段階(警戒以上・警戒・危険)だけを言う文(打ち消しも)。"""
    CN = X.R["hazard_count"]
    if not _has_any(t, CN["universal_scope"]):
        return False
    words = _universals(X)
    span = next((c for c in _clauses(t) if _has_any(c, words) and (HZ in c or lv_re.search(c))), None)
    if span is None:
        span = t[min(t.index(w) for w in words if w in t):]
    plain = span.replace(HZ, "　　　　")
    if any(k in span for k in kinds) or "注意" in plain or _has_any(plain, CN["not_words_universal"]):
        return False
    lvs = {m.group(0) for m in lv_re.finditer(plain)}
    neg = re.search(r"ない|なし|なく|ません", plain)
    if len(lvs) > 1 or (neg and not lvs):
        return False
    key = {"警戒以上": "total", "警戒": "warning", "危険": "danger"}[lvs.pop()] if lvs else "total"
    return all(n["all"][key] == (0 if neg else n["above"]) for n in ns)


def check(draft, brief):
    """→ {ok, errors, final, picks}。"""
    X = Ctx(brief)
    R = X.R
    W = R["words"]
    mre = re.compile(R["draft"]["marker_re"])
    errs = []
    body_lines, picks = split_draft(draft, R)
    body = NL.join(body_lines)
    # 決まった文: そのまま写してあるか(印つき)。写した部分は置き換えてから文に分ける
    present = set()
    masked = body
    for x in X.lines:
        if x["text"] in masked:
            present.add(x["id"])
            masked = masked.replace(x["text"], PH + "。")
    for mid in set(mre.findall(body)):
        if mid in X.ids and X.ids[mid][0] == "L" and mid not in present:
            errs.append(_err("line_altered", None, f"[{mid}] の決まった文が書き換えてある", f"資料の [{mid}] の文を一字一句そのまま写す"))
    sents = sentences(masked, mre)
    exempt_re = re.compile("|".join(re.escape(w) for w in sorted(W["safety_exempt"], key=len, reverse=True)))
    lodging_ok = set(W["lodging_ok"])
    for s in sents:
        clean = s["clean"].replace(PH, "")
        if not clean.strip("。 "):
            continue
        ids = s["ids"]
        bad = [i for i in ids if i not in X.ids]
        if bad:
            errs.append(_err("unknown_mark", s, f"資料にない印 {', '.join(bad)}", "資料にある事実の印だけを付ける"))
            ids = [i for i in ids if i in X.ids]
        t = _norm(clean)
        if X.star:                               # 星の地点の名前を先に置き換える(山の名前・天気の語と重なるため)
            from .stars_verify import sentence_errors
            t, sites = X.star.mask(t)
            sentence_errors(X, s, t, sites, ids, lambda code, detail, fix, s=s: errs.append(_err(code, s, detail, fix)))
        tm, mentioned = X.mask_names(t)
        tk = X.tokens(tm)
        exempt = bool(exempt_re.search(t))
        kinds = {X.ids[i][0] for i in ids}
        # 76 座にない山の名前(形で見る。質問に書かれた名前は通す)
        for m in re.finditer(W["mountain_re"], tm):
            w = m.group(0)
            if any(w.endswith(c) for c in W["mountain_common"]) or w in X.question or w in X.named_specs:
                continue
            errs.append(_err("unknown_mountain", s, f"資料にない山の名前「{w}」", "資料にある山だけを書く(76 座にない山は「足りないもの」を使う)"))
        if ids:
            a = X.allowed(ids)
            a["mountains"] |= X.q_mountains          # 質問に書かれた山は、名前を出してよい(数字などは印の事実と照らす)
            for mid in sorted(mentioned - a["mountains"]):
                code = "mountain_unmarked" if mid in X.in_brief else "mountain_not_in_brief"
                errs.append(_err(code, s, f"印の事実にない山({mid})を書いている",
                                 "その山の事実の印も付ける(比べる文はそれぞれの印が要る)" if code == "mountain_unmarked" else "資料にない山を書かない"))
            for d in sorted(tk["dates"] - a["dates"]):
                errs.append(_err("date_mismatch", s, f"日付 {d[0]}月{d[1]}日 が印の事実と合わない", "印の事実の日付を書く"))
            for w in sorted(tk["wds"] - a["wds"]):
                errs.append(_err("date_mismatch", s, f"曜日「{w}」が印の事実と合わない", "印の事実の曜日を書く"))
            for tm_ in sorted(tk["times"] - a["times"]):
                errs.append(_err("time_mismatch", s, f"時刻 {tm_[0]}:{tm_[1]:02d} が資料にない", "資料にある時刻だけを書く"))
            for ap, v, u, after in tk["nums"]:
                if u is None and any(after.startswith(c) for c in R["numbers"]["counters"]):
                    continue
                ok = (ap, v, u) in a["nums"] if u else v in a["values"]
                if not ok:
                    errs.append(_err("number_mismatch", s, f"数「{'約' if ap else ''}{v}{u or ''}」が印の事実の書いてよい表記にない",
                                     "事実の「書いてよい表記」をそのまま使う(自分で丸めない)"))
            for kind in W["hazard_kinds"]:
                if kind == HZ:                       # 種類を書かずに段階だけを言う文は、下の _check_level_only で見る
                    continue
                for lv in W["hazard_levels"]:
                    if re.search(re.escape(kind) + r"\s*[のが:は]?\s*" + re.escape(lv), tm) and (kind, lv) not in a["hazards"]:
                        if not (lv == "警戒" and (kind, "警戒以上") in a["hazards"]):
                            errs.append(_err("hazard_mismatch", s, f"危険信号「{kind}{lv}」が印の事実と合わない", "印の事実の危険信号の語を書く"))
            _check_level_only(X, s, t, ids, errs)
            if tk["urls"]:
                errs.append(_err("url_not_in_brief", s, "URL を書いている", "URL を書かない"))
        else:
            if tk["dates"] or (tk["wds"] - X.target_wd):
                errs.append(_err("date_unmarked", s, "印のない文に日付・対象の日でない曜日", "日付は事実の印を付けて書く(印なしで書けるのは今日・明日・今週末・来週末・対象の日の曜日だけ)"))
            if tk["times"]:
                errs.append(_err("time_unmarked", s, "印のない文に時刻", "時刻は事実の印を付けて書く"))
            nums = [(ap, v, u) for ap, v, u, after in tk["nums"] if u]
            if nums:
                errs.append(_err("number_unmarked", s, "印のない文に数字と単位(" + "・".join(f"{v}{u}" for _, v, u in nums[:3]) + ")",
                                 "数字は事実の印を付けて、書いてよい表記で書く"))
            if tk["urls"]:
                errs.append(_err("url_unmarked", s, "印のない文に URL", "URL を書かない"))
            t_w = tm
            for w in W["weather_ok"] + W["safety"]:       # 安全の語(積雪・雪山など)は種類 C の検査で見る
                t_w = t_w.replace(w, " ")
            hits = _has_any(t_w, W["weather"])
            if hits:
                errs.append(_err("weather_unmarked", s, f"印のない文に天気の語「{'・'.join(hits[:3])}」",
                                 "天気・予報の話は事実の印を付けて書く(一般的な話なら天気の語を使わない)"))
            hz = [k for k in W["hazard_kinds"] if k in tm and k not in hits]
            if hz:
                errs.append(_err("hazard_unmarked", s, f"印のない文に危険信号の語「{'・'.join(hz)}」", "危険信号は事実の印を付けて書く"))
            for mid in sorted(mentioned - X.in_brief):
                if not any(n in X.question for n, m_ in X.names if m_ == mid):
                    errs.append(_err("mountain_not_in_brief", s, f"資料にない山({mid})を書いている", "資料にある山だけを書く"))
        _check_comparisons(X, s, t, ids, errs)
        _check_named_gap(X, s, t, ids, errs)
        _check_hazard_counts(X, s, t, ids, errs)
        # 種類 C(山の安全): 危険信号の事実・知識カードの印、または「判断できません」の形(足りないものの印だけでは通さない)
        sc = _has_any(exempt_re.sub(" ", t), W["safety"])
        if sc and not exempt:
            hazard_fact = any(X.ids[i][0] == "Y" and X.ids[i][1]["hazards"] for i in ids)
            basis = "K" in kinds or (hazard_fact and all(w in W["safety_hazard_ok"] for w in sc))
            if not basis:
                errs.append(_err("safety_without_basis", s, f"山の安全に関わる語「{'・'.join(sc[:3])}」に裏づけがない",
                                 "資料に無いなら「この予報からは判断できません」の形で書き、足りないものの印 [G…] を付ける([G…] の印だけでは通らない)"))
            if ids and _has_any(exempt_re.sub(" ", t), W["safety_positive"]) and "K" not in kinds:
                errs.append(_err("safety_assertion", s, f"安全の言い切り「{'・'.join(_has_any(t, W['safety_positive'])[:3])}」に知識カードの裏づけがない",
                                 "行ける・安全だと言い切らない(予報の数字と危険信号の文だけを書く)"))
        # おすすめの語と、宣言したおすすめ
        if picks is not None and _has_any(_cut(t, W["recommend_ok"]), W["recommend"]) and not _has_any(t, W["recommend_not"]):
            ys = [i for i in ids if X.ids[i][0] == "Y"]
            stars_ = [i for i in ids if X.ids[i][0] == "S"]
            if stars_ and not set(ys + stars_) & set(picks):
                errs.append(_err("pick_undeclared", s, f"すすめている星の地点({', '.join(stars_)})が [おすすめ] にない", "[おすすめ] の行にその事実の id を書く"))
            elif ys and not set(ys) & set(picks):
                errs.append(_err("pick_undeclared", s, f"すすめている山({', '.join(ys)})が [おすすめ] にない", "[おすすめ] の行にその事実の id を書く"))
        # ビヨリをまたいで点を比べる
        if re.search(r"\d\s*点|点数", t) and _has_any(t, W["other_biyori"]):
            errs.append(_err("score_across_biyori", s, "山の点とほかのビヨリの話を 1 文で比べている", "ビヨリ間で点数を比べない"))
        for m in re.finditer(W["lodging_re"], tm):
            if m.group(0) not in lodging_ok:
                errs.append(_err("lodging_name", s, f"宿・山小屋の名前らしい語「{m.group(0)}」", "宿・山小屋の名前を書かない(「泊まりにすると」まで)"))
    # 全体
    _check_lone_number(X, body, errs)
    _check_stale(X, body, errs)
    _check_cloud(X, sents, errs)
    _check_named(X, body, mre, errs)
    L = brief["lines"]
    for key in ("data_time", "coverage", "attribution"):
        if L[key] and L[key]["id"] not in present:
            errs.append(_err("line_missing", None, f"決まった文 {key}([{L[key]['id']}])がない", f"[{L[key]['id']}] の文をそのまま写す"))
    plan_main = {p["main"]["fact"] for p in brief["plans"]}
    if picks is None:
        errs.append(_err("picks_missing", None, "最後の行の [おすすめ] がない", "最後の行に「[おすすめ] Y…」(なければ「[おすすめ] なし」)を書く"))
        picks_ = []
    else:
        picks_ = picks
    for pid in picks_:
        x = X.ids.get(pid)
        if x and x[0] == "S":                    # 星のおすすめは whole_errors で見る
            continue
        if not x or x[0] != "Y":
            errs.append(_err("pick_unknown", None, f"[おすすめ] の {pid} が山の事実にない", "山の事実の id を書く"))
            continue
        f = x[1]
        if not f["main_ok"]:
            errs.append(_err("pick_not_allowed", None, f"{f['name']}({f['label']})は主役にできない山", "主役にできる山だけをすすめる(見送りとして書く)"))
            continue
        if pid not in plan_main and not (X.star and any(a["fact"] == pid for p in brief["plans"] for a in p["adds"])):
            errs.append(_err("pick_not_in_plans", None, f"{pid} が組み合わせの案にない", "資料の組み合わせにある主役だけをすすめる"))
        for h in L["hazards"]:
            if h["fact"] == pid and h["id"] not in present:
                errs.append(_err("hazard_line_missing", None, f"{f['name']}({f['label']})の危険信号の文([{h['id']}])がない",
                                 f"[{h['id']}] の文をそのまま写す"))
        if not f["reliable"] and not (L["lead_time"] and L["lead_time"]["id"] in present):
            errs.append(_err("lead_time_missing", None, f"{f['label']}は信用してよい範囲の外なのに、先の予報である旨の文がない",
                             f"[{(L['lead_time'] or {}).get('id', 'L…')}] の文をそのまま写す"))
    if X.star:
        from .stars_verify import whole_errors
        whole_errors(X, body, sents, present, picks_, mre, lambda s, code, detail, fix: errs.append(_err(code, s, detail, fix)), R["stale"]["assert"])
    final = strip_marks(place_note(body, X, mre, exempt_re), mre)
    plain = final
    for x in X.lines:
        plain = plain.replace(x["text"], " ")
    if X.star:                                   # 地点の名前(英字・「印」などを含むもの)を、内部の言葉・英語の検査に掛けない
        for x in brief["stars"]["index"]:
            plain = plain.replace(x["label"], "　")
    plain_n = exempt_re.sub(" ", _norm(plain))
    for line in plain_n.split(NL):
        for rx in W["internal"]:
            m = re.search(rx, line)
            if m:
                errs.append(_err("internal_word", {"line": 0, "clean": line}, f"内部の言葉「{m.group(0)}」", "利用者の言葉に言い換える"))
                break
        if re.search(W["english_re"], line):
            errs.append(_err("english_note", {"line": 0, "clean": line}, "英語の文・メモ", "英語のメモを書かない"))
    for s in sentences(plain, mre):
        for rx in W["question"]:
            if re.search(rx, s["clean"]):
                errs.append(_err("question_in_answer", s, "読む人への問いかけ", "質問をしない(答えだけを書く)"))
                break
        for rx in W["offer"]:
            if re.search(rx, s["clean"]):
                errs.append(_err("offer_in_answer", s, "できないことの提案", "「〜しましょうか」と提案しない"))
                break
    mx = brief["limits"]["max_chars"]
    if len(final) > mx:
        errs.append(_err("too_long", None, f"{len(final)} 字({mx} 字まで)", "短くする"))
    return {"ok": not errs, "errors": errs, "final": final, "picks": picks_, "checked": len(sents),
            "marked": sum(1 for s in sents if s["ids"])}


NUMBER_HEAD = re.compile(r"^\s*(?:[-*・]\s*)?(?:\*\*)?(?:\d{1,2}[.)．]|[①-⑨])")
LIST_HEAD = re.compile(r"^(?:[-*・#>\s]+|\d{1,2}[.)．]\s*|[①-⑨]\s*)+")


def place_note(body, X, mre, exempt_re):
    """危険信号の注記(lines.hazard_note)を正しい位置に 1 回だけ置き直した本文(印つき)を返す。ほかの文の順番・中身は変えない。
    位置: 最後の危険信号の決まった文(山ごと・見送りのまとめ)・件数の文([N…])のあと。そのあとに足りないものの文があれば、その前
    (なければ、その段落の終わり。出典の文があればその前)。前後を空行で分けて 1 つの段落にする。危険信号の決まった文がなければ、注記を出さない。"""
    L, note = X.b["lines"], X.b["lines"].get("hazard_note")
    if not note:
        return body
    mk = rf"(?:\s*{mre.pattern})*"
    lines = []
    for line in re.sub(re.escape(note["text"]) + mk + r"[ \t　]*", HOLE, body).split(NL):
        if HOLE in line:
            line = line.replace(HOLE, "")
            if not LIST_HEAD.sub("", line):                      # 注記だけの行(箇条書きの印だけが残る行)はなくす
                continue
        lines.append(line)
    out = NL.join(lines)
    ends = [m.end() for x in list(L["hazards"]) + list(L.get("skips") or []) for m in re.finditer(re.escape(x["text"]) + mk, out)]
    if not ends:
        return out
    segs = [(m.start(), m.end(), {X.ids[i][0] for i in mre.findall(m.group(0)) if i in X.ids}, m.group(0))
            for m in re.finditer(rf"[^。！？!?\n]+[。！？!?]?(?:[ \t]*{mre.pattern})*", out)]
    anchor = max(ends + [e for _, e, kinds, _ in segs if "N" in kinds])
    gap = next((s for s, _, kinds, t in segs if s >= anchor and ("G" in kinds or (not kinds and exempt_re.search(_norm(t))))), None)
    if gap is not None:
        head = out.rfind(NL, 0, gap) + 1
        pos = max(anchor, gap if LIST_HEAD.sub("", out[head:gap]) else head)      # 行の途中の文なら、そこで段落を分ける
    else:
        pos = re.compile(r"\n[ \t　]*\n|\Z").search(out, anchor).start()
        src = out.find(L["attribution"]["text"], anchor) if L["attribution"] else -1
        pos = src if 0 <= src < pos else pos
    before, after = out[:pos].rstrip(), out[pos:].lstrip(" \t　" + NL)
    return before + NL + NL + f"{note['text']}[{note['id']}]" + (NL + NL + after if after else "")


def strip_marks(body, mre):
    out = []
    for line in body.split(NL):
        line = re.sub(r"\s*" + mre.pattern + r"(?:[ \t　]+(?=\S))?", "", line).rstrip()   # 印の後ろの空白も取る(「です。[Y1] 次の文」)
        out.append(line)
    text = NL.join(out).strip(NL)
    return re.sub(r"\n{3,}", "\n\n", text) + NL


def report(res):
    out = [f"{res['status']}(照らした文 {res['checked']}・印のある文 {res['marked']}・{res['attempt']} 回目)"]
    for e in res["errors"]:
        where = f"{e['line']}行目 " if e.get("line") else ""
        out.append(f"NG [{e['code']}] {where}{e['detail']}" + (f"\n   文: {e['sentence']}" if e.get("sentence") else "") + f"\n   直し方: {e['fix']}")
    if res["status"] == "FAIL":
        out.append(f"書き直しはあと {res['left']} 回です。直して同じコマンドをもう一度実行します。")
    return NL.join(out) + NL


def max_rewrites():
    return int(config()["answer"]["max_rewrites"])


def run(draft_text, bid, base, now):
    """→ {status: PASS / FAIL / FALLBACK / NO_BRIEF / OLD_BRIEF, text, errors, attempt, left}。回数は置き場の briefs/<id>.verify.json で数える。"""
    import json
    from pathlib import Path

    from . import brief as B
    from . import fallback as F
    from .common import dump_json, iso, read_json, write_text
    b = B.load(bid, base)
    if b is None:
        return {"status": "NO_BRIEF", "text": None, "errors": [], "attempt": 0, "left": 0, "checked": 0, "marked": 0}
    if not B.is_current(b):                      # 前の形の資料(回数は数えない)
        return {"status": "OLD_BRIEF", "text": None, "errors": [], "attempt": 0, "left": 0, "checked": 0, "marked": 0}
    st_path = B.brief_dir(base) / f"{bid}.verify.json"
    st = read_json(st_path) or {"attempts": 0, "history": []}
    st["attempts"] += 1
    r = check(draft_text, b)
    rewrites = st["attempts"] - 1
    mx = max_rewrites()
    if r["ok"]:
        status, text = "PASS", r["final"]
    elif rewrites >= mx:
        fb = check(F.draft(b), b)
        if not fb["ok"]:                         # 長すぎるなどで控えの文が通らなければ、短い形にする(必ず答えを出す)
            fb = check(F.draft(b, compact=True), b)
        status, text = "FALLBACK", fb["final"]
    else:
        status, text = "FAIL", None
    st["history"].append({"attempt": st["attempts"], "status": status, "errors": sorted({e["code"] for e in r["errors"]})})
    write_text(st_path, dump_json(st))
    if text:
        write_text(B.brief_dir(base) / f"{bid}.final.txt", text)
        write_text(Path(base) / LAST_ANSWER, dump_json({"brief": bid, "at": iso(now), "text": text}))      # Stop フックが読む
    row = {"brief": bid, "at": iso(now), "result": {"PASS": "合格", "FAIL": "不合格", "FALLBACK": "控え"}[status],
           "rewrites": rewrites, "failed": sorted({e["code"] for e in r["errors"]})}
    p = Path(base) / "logs" / "answers.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + NL)
    return {"status": status, "text": text, "errors": r["errors"], "attempt": st["attempts"], "left": max(0, mx - rewrites),
            "checked": r["checked"], "marked": r["marked"]}
