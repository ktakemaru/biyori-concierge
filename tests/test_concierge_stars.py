"""星を足した答え(段階 3 第 2 部 B): 資料・一日の流れの案・照合・控えの文。見本の棚は tests/fixtures/shelf_day/(実物から減らしたもの。
山は 2026-11-23、星は 2026-11-25 の実物。作り方は tests/make_stars_fixture.py)。通信しない。"""
import json
import re
import shutil
import unittest
from datetime import date
from pathlib import Path

from concierge_helpers import SHELF_FIX, build, edit_json
from helpers import FIX, tmpdir

from concierge import brief as B
from concierge import fallback as F
from concierge import named as N
from concierge import shelf as S
from concierge import stars as ST
from concierge import status
from concierge import verify as V
from concierge.common import brief_schema_errors, parse_now

DAY_FIX = FIX / "shelf_day"
NOW = "2026-11-25T23:00:00+09:00"          # 星を取ったあと(山は 54 時間前 = 古い予報)
Q = "土曜の夜に星を見たい。昼は何をするといい?"
STARS, BOTH = ["星空"], ["登山・ハイキング", "星空"]


def base_of(test, fix=DAY_FIX, edit=None):
    base = tmpdir(test, "biyori-cday-")
    shutil.copytree(fix, base / "shelf")
    if edit:
        edit(base / "shelf")
    return base


def fresh(shelf_dir):
    """作り物: 山の時点だけを星と同じ日に書き換える(古い予報でない形のテストのため。予報の数字は変えない)。"""
    edit_json(shelf_dir / "manifest.json", lambda m: m["agents"]["yamabiyori"].update(data_time="2026-11-25T16:53:19+09:00"))


def stars_edit(fn):
    def edit(shelf_dir):
        fresh(shelf_dir)
        edit_json(shelf_dir / "hoshibiyori" / "stars.json", fn)
    return edit


def make(test, when="2026-11-28", interest=STARS, edit=fresh, q=Q, **kw):
    return build(base_of(test, edit=edit), question=q, when=when, interest=interest, now=kw.pop("now", NOW), **kw)


def sfact(doc, name, day="2026-11-28"):
    return next(f for f in doc["stars"]["facts"] if f["name"].startswith(name) and f["date"] == day)


def yfact(doc, name, day="2026-11-28"):
    return next(f for f in doc["facts"] if f["name"].startswith(name) and f["date"] == day)


def ln(x):
    return f"{x['text']}[{x['id']}]"


def draft_of(doc, body, picks, head="", lead=True):
    """決まった文のそろった下書き(星が起点・山も星も 1 つずつ)。"""
    L = doc["lines"]
    out = [head] if head else []
    out += [ln(L["data_time"]), ln(L["coverage"]), ln(L["star_data_time"]), ln(L["star_mode"]), "", body]
    if lead and L["lead_time"]:
        out.append(ln(L["lead_time"]))
    if L["star_regime"]:
        out.append(ln(L["star_regime"]))
    out += [ln(x) for x in L["star_skips"]]
    out += [ln(g) for g in doc["gaps"]] + [ln(L["attribution"]), ln(L["star_attribution"]), "", "[おすすめ] " + (", ".join(picks) or "なし")]
    return "\n".join(out) + "\n"


class MountainOnly(unittest.TestCase):
    """星の興味の語が無い質問は、星の棚があってもなくても 1 バイトも変わらない。"""

    def test_no_star_word_means_no_change_even_with_a_star_shelf(self):
        def without(d):
            shutil.rmtree(d / "hoshibiyori")
            (d / "proposals" / "hoshibiyori.json").unlink()
            edit_json(d / "manifest.json", lambda m: m["agents"].pop("hoshibiyori"))
        for kw in (dict(when="今週末"), dict(when="今週末", mountains=["鍋割山", "石割山"]), dict(when="2026-11-28", interest=["紅葉"])):
            with self.subTest(**kw):
                a = build(base_of(self), question="どこ?", now=NOW, **kw)
                b = build(base_of(self, edit=without), question="どこ?", now=NOW, **kw)
                self.assertEqual(json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False))
                self.assertNotIn("stars", a)
                self.assertNotIn("frames", json.dumps(a["plans"]))
                self.assertIn("星空と、花・紅葉・野鳥の情報は、まだ使えません。", [g["text"] for g in a["gaps"]])
                self.assertEqual(F.draft(a), F.draft(b))
                self.assertEqual(B.render_md(a), B.render_md(b))

    def test_star_word_without_a_star_shelf_answers_with_mountains_and_one_sentence(self):
        base = base_of(self, SHELF_FIX)
        d = build(base, interest=BOTH, now="2026-10-15T08:00:00+09:00")
        self.assertNotIn("stars", d)
        texts = [g["text"] for g in d["gaps"]]
        self.assertEqual([t for t in texts if "星" in t], ["星の予報は今回使えませんでした。"])
        self.assertTrue(d["facts"])
        r = V.check(F.draft(d), d)
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(r["final"].count("星の予報は今回使えませんでした。"), 1)

    def test_broken_star_file_is_not_used(self):
        def broken(d):
            (d / "hoshibiyori" / "stars.json").write_text("{}", encoding="utf-8")
        d = make(self, edit=broken)
        self.assertNotIn("stars", d)
        self.assertIn("星の予報は今回使えませんでした。", [g["text"] for g in d["gaps"]])


class Brief(unittest.TestCase):
    def test_facts_schema_and_determinism(self):
        base = base_of(self, edit=fresh)
        a, b = (build(base, question=Q, when="今週末", interest=STARS, now=NOW) for _ in range(2))
        self.assertEqual(a, b)
        self.assertEqual(brief_schema_errors(a), [])
        self.assertEqual(a["stars"]["mode"], "stars")                       # 11 月の見本: 天の川の候補が少ない
        f = sfact(a, "丹沢湖(山北町)")
        self.assertEqual((f["site_id"][:8], f["label"], f["status"], f["regime"], f["rank"]), ("curated:", "11月28日(土)の夜", "passed", "ECMWF", None))
        self.assertIn("18:01〜20:31", f["say"])
        self.assertIn("28日(土)の夜", f["say"])
        self.assertEqual(a["stars"]["counts"][0]["say"][2], "調べた 897 地点のうち条件を通った地点は 157 地点")
        self.assertTrue(all(x["id"] and x["label"] for x in a["stars"]["index"]))

    def test_rank_orders_the_sites_of_a_candidate_night(self):
        d = make(self, "2026-12-06")
        tops = [f for f in d["stars"]["facts"] if f["selected_by"] == "top"]
        self.assertTrue(all(isinstance(f["rank"], int) for f in tops if f["group"] == "primary"))
        keys = [ST.site_key(f, f["distance_km"]) for f in tops]
        self.assertEqual(keys, sorted(keys))

    def test_far_sites_are_not_used(self):
        d = make(self, "2026-11-29")
        self.assertNotIn("八丈富士(八丈町)", [f["name"] for f in d["stars"]["facts"]])      # 直線 250km より遠い
        self.assertIn("八丈富士(八丈町)", [x["label"] for x in d["stars"]["index"]])

    def test_moon_night_has_no_candidates_and_a_fixed_line(self):
        d = make(self, "2026-11-25")
        self.assertEqual(d["stars"]["facts"], [])                           # 実物では 541 地点が passed だが、月が一晩じゅう出ている
        t = d["stars"]["counts"][0]
        self.assertEqual(t["state"], "moon")
        self.assertIn("月の無い時間帯が無いため", d["lines"]["star_skips"][0]["text"])

    def test_night_without_any_passed_site(self):
        d = make(self, "2026-12-04")
        self.assertEqual(d["stars"]["counts"][0]["state"], "none_passed")
        self.assertIn("雲 628 地点", d["lines"]["star_skips"][0]["text"])

    def test_night_out_of_the_shelf_is_not_examined(self):
        d = make(self, "2026-12-12")
        self.assertEqual(d["stars"]["counts"][0]["state"], "not_examined")
        self.assertEqual(d["lines"]["star_skips"], [])
        self.assertIn("12月12日(土)の夜は、その夜の雲の予報は今回調べられていません。", [g["text"] for g in d["gaps"]])

    def test_examined_night_with_no_cloud_data_is_not_examined(self):
        def edit(doc):                                                      # 作り物: 11/28 の window_kind が none(実物には無い形)
            r = next(r for r in doc["requested_nights"] if r["night_date"] == "2026-11-28")
            r.update(window_kind="none", none_reason="out_of_forecast_range", counts=None, sites=[], forecast_regime=None)
        d = make(self, edit=stars_edit(edit))
        self.assertEqual((d["stars"]["counts"][0]["state"], d["stars"]["facts"]), ("not_examined", []))

    def test_site_without_an_id_is_not_a_fact(self):
        def edit(doc):                                                      # 作り物: 丹沢湖の site_id を null に
            sid = next(x["site_id"] for x in doc["site_index"] if x["name"] == "丹沢湖")
            for x in doc["site_index"] + [s for r in doc["requested_nights"] for s in r["sites"]]:
                if x["site_id"] == sid:
                    x["site_id"] = None
        d = make(self, edit=stars_edit(edit))
        self.assertFalse([f for f in d["stars"]["facts"] if f["name"].startswith("丹沢湖")])

    def test_milkyway_mode_when_there_are_enough_candidates(self):
        def edit(shelf_dir):                                                # 作り物: 天の川モードの候補を 5 件にする
            fresh(shelf_dir)
            st = json.loads((shelf_dir / "hoshibiyori/stars.json").read_text(encoding="utf-8"))
            edit_json(shelf_dir / "hoshibiyori/milkyway.json", lambda m: m.update(outlooks=[dict(x, score=1.0) for x in st["outlooks"][:5]]))
        self.assertEqual(make(self, edit=edit)["stars"]["mode"], "milkyway")

    def test_milky_way_question_says_why_the_mode_changed(self):
        d = make(self, interest=["天の川"])
        self.assertTrue(d["lines"]["star_mode"]["text"].startswith("天の川モードの候補が少ないため、"))

    def test_lift_site_has_a_line(self):
        d = make(self, "2026-11-29", BOTH, mountains=["木曽駒ヶ岳"])
        f = [x for x in d["stars"]["facts"] if x["requires_lift_access"]]
        for x in f:
            self.assertIn("リフト要の地点で、運行は確かめていません。", next(y["text"] for y in d["lines"]["star_lifts"] if y["fact"] == x["id"]))

    def test_status_shows_both(self):
        text = status.render(base_of(self), parse_now(NOW))
        self.assertIn("- 星: 11月25日(水) 22:34 時点", text)
        self.assertIn("ホシビヨリ 1.2.0(commit 3860af7)", text)
        self.assertNotIn("まだありません", text)

    def test_night_clock(self):
        d = date(2026, 11, 28)
        self.assertEqual(ST.clock("2026-11-28T18:40:59+09:00", d), "18:40")
        self.assertEqual(ST.clock("2026-11-29T02:30:00+09:00", d), "翌2:30")
        self.assertEqual(ST.clock("2026-11-28T17:30:00Z", d), "翌2:30")
        self.assertEqual((ST.hours_say(2.5), ST.hours_say(3.75)), ("2.5 時間", "約3.8 時間"))


class Plans(unittest.TestCase):
    def frames(self, p):
        return [(f["slot"], bool(f["fact"])) for f in p["frames"]]

    def test_frames_are_in_time_order_and_nature_is_empty(self):
        for it in (STARS, BOTH):
            d = make(self, "今週末", it)
            for p in d["plans"]:
                self.assertEqual([f["slot"] for f in p["frames"]], ["day_mountain", "day_nature", "night_stars"])
                self.assertIsNone(p["frames"][1]["fact"])

    def test_mountain_first_or_star_first_by_the_interest(self):
        a, b = make(self, "今週末", BOTH), make(self, "今週末", STARS)
        for d, first in ((a, "mountain"), (b, "stars")):
            for day in {p["date"] for p in d["plans"]}:
                kinds = [p["main"]["kind"] for p in d["plans"] if p["date"] == day]
                self.assertEqual(kinds[0], first)
                self.assertEqual(kinds, sorted(kinds, key=lambda k: k != first))
            self.assertEqual([p["date"] for p in d["plans"]], sorted(p["date"] for p in d["plans"]))

    def test_mountain_order_is_the_same_as_before(self):
        d = make(self, "今週末", BOTH)
        m = [p["main"]["fact"] for p in d["plans"] if p["main"]["kind"] == "mountain"]
        facts = {f["id"]: f for f in d["facts"]}
        self.assertEqual(m, [f["id"] for f in sorted((facts[i] for i in m), key=lambda f: (f["date"], B.main_key(f)))])

    def test_stars_are_attached_only_near_the_mountain_on_the_same_day(self):
        d = make(self, "今週末", BOTH)
        ys, ss = {f["id"]: f for f in d["facts"]}, {f["id"]: f for f in d["stars"]["facts"]}
        got = {}
        for p in d["plans"]:
            if p["main"]["kind"] != "mountain":
                continue
            y = ys[p["main"]["fact"]]
            got[(y["name"], y["date"])] = p["adds"]
            for a in p["adds"]:
                s = ss[a["fact"]]
                self.assertLessEqual(a["distance_km"], 20)
                self.assertEqual((s["date"], s["main_ok"]), (y["date"], True))
                self.assertIn(y["id"], [n["fact"] for n in s["near"]])
        self.assertTrue(got[("鍋割山", "2026-11-28")])
        self.assertEqual(got[("高尾山", "2026-11-28")], [])                 # 近くに星の地点が無い山には付けない
        self.assertEqual(got[("筑波山(女体山)", "2026-11-28")], [])

    def test_primary_site_first_then_distance_from_the_mountain(self):
        d = make(self, "2026-11-28", BOTH)
        y = yfact(d, "石割山")
        p = next(p for p in d["plans"] if p["main"]["fact"] == y["id"])
        s = next(f for f in d["stars"]["facts"] if f["id"] == p["adds"][0]["fact"])
        self.assertEqual(s["name"], "山中湖パノラマ台(山中湖村)")            # 0.2km の「石割山(山中湖村)」は参考の地点なので、主軸を先に
        self.assertEqual(p["adds"][0]["others"], 4)

    def test_star_plan_has_a_mountain_of_the_day(self):
        d = make(self, "2026-11-28", STARS)
        p = d["plans"][0]
        self.assertEqual((p["main"]["kind"], p["adds"][0]["kind"]), ("stars", "mountain"))
        self.assertTrue(next(f for f in d["facts"] if f["id"] == p["adds"][0]["fact"])["main_ok"])

    def test_hard_hazard_mountains_are_never_in_a_plan(self):
        d = make(self, "2026-11-29", STARS)
        bad = {f["id"] for f in d["facts"] if not f["main_ok"]}
        self.assertTrue(bad)
        self.assertFalse(bad & {f["fact"] for p in d["plans"] for f in p["frames"]})

    def test_moon_night_has_only_mountain_frames(self):
        d = make(self, "2026-11-25", STARS)
        self.assertTrue(d["plans"])
        self.assertFalse([f for p in d["plans"] for f in p["frames"] if f["kind"] == "stars" and f["fact"]])


class Verify(unittest.TestCase):
    def setUp(self):
        self.d = make(self)
        self.y, self.s = yfact(self.d, "鍋割山"), sfact(self.d, "丹沢湖")
        self.hz = next(ln(h) for h in self.d["lines"]["hazards"] if h["fact"] == self.y["id"])
        self.t = self.d["stars"]["counts"][0]

    def body(self, night=None, extra=""):
        y, s = self.y["id"], self.s["id"]
        night = night or f"夜は、11月28日(土)の夜に、丹沢湖(山北町)(鍋割山から直線で約9km)で、18:01〜20:31に晴れ間の見込みです。[{s}][{y}]"
        return f"朝〜日中は、28日(土)の鍋割山が76.3点で、雲はほとんど無い予報です。[{y}]".replace("28日(土)の", "11月28日(土)の") + "\n" + self.hz + "\n" + night + extra

    def check(self, body, picks=None, doc=None):
        d = doc or self.d
        return V.check(draft_of(d, body, picks if picks is not None else [self.y["id"], self.s["id"]]), d)

    def codes(self, *a, **kw):
        return {e["code"] for e in self.check(*a, **kw)["errors"]}

    def test_good_draft_passes(self):
        r = self.check(self.body())
        self.assertTrue(r["ok"], r["errors"])
        self.assertNotRegex(r["final"], r"\[[A-Z]\d")

    def test_short_night_label_passes(self):
        r = self.check(self.body(f"28日(土)の夜は、丹沢湖(山北町)で18:01〜20:31に晴れ間の見込みです。[{self.s['id']}]"))
        self.assertTrue(r["ok"], r["errors"])

    def night(self, text):
        return self.body(text + f"[{self.s['id']}]")

    def test_night_written_as_two_dates_is_stopped(self):
        for w in ("28日から29日は、", "28〜29日は、", "28日深夜は、", "28日(土)から29日(日)の夜は、", "29日未明は、", "土曜の深夜は、"):
            with self.subTest(w):
                r = self.check(self.night(w + "丹沢湖(山北町)で18:01〜20:31に晴れ間の見込みです。"))
                e = [x for x in r["errors"] if x["code"] == "night_label"]
                self.assertTrue(e, r["errors"])
                self.assertIn("の夜", e[0]["fix"])

    def test_star_fact_without_the_night_label_is_stopped(self):
        self.assertIn("night_label", self.codes(self.night("その夜は、丹沢湖(山北町)で18:01〜20:31に晴れ間の見込みです。")))

    def test_next_day_mark_missing_or_extra(self):
        d = make(self, "2026-12-06")                                        # 晴れ間が 0 時を過ぎる夜
        s = next(f for f in d["stars"]["facts"] if any("〜翌" in v["say"][0] and v["say"][0][0] != "翌" for v in f["values"] if v["key"] == "clear_window"))
        win = next(v["say"][0] for v in s["values"] if v["key"] == "clear_window")
        self.assertIn("翌", win)

        def codes(text):
            return {e["code"] for e in V.check(draft_of(d, text, [s["id"]]), d)["errors"]}
        ok = f"{s['label']}は、{s['name']}で{win}に晴れ間の見込みです。[{s['id']}]"
        self.assertNotIn("night_time", codes(ok))
        self.assertIn("night_time", codes(ok.replace("翌", "")))
        first = win.split("〜")[0]
        self.assertIn("night_time", codes(ok.replace(first + "〜", "翌" + first + "〜")))

    def test_time_not_in_the_fact_is_stopped(self):
        self.assertIn("time_mismatch", self.codes(self.night("28日(土)の夜は、丹沢湖(山北町)で19:30〜20:31に晴れ間の見込みです。")))

    def test_sites_not_in_the_brief_or_not_marked(self):
        self.assertIn("site_not_in_brief", self.codes(self.night("28日(土)の夜は、神磯の鳥居・大洗海岸(大洗町)で18:01〜20:31に晴れ間の見込みです。")))
        other = sfact(self.d, "山中湖パノラマ台")
        self.assertIn("site_unmarked", self.codes(self.night(f"28日(土)の夜は、{other['name']}で18:01〜20:31に晴れ間の見込みです。")))
        self.assertIn("unknown_site", self.codes(self.night("28日(土)の夜は、戦場ヶ原展望台で18:01〜20:31に晴れ間の見込みです。")))
        self.assertIn("site_label", self.codes(self.night("28日(土)の夜は、丹沢湖で18:01〜20:31に晴れ間の見込みです。")))

    def test_star_names_are_stopped(self):
        for w in ("オリオン座", "木星", "ふたご座流星群", "シリウス", "すばる", "冬の大三角", "天の川"):
            with self.subTest(w):
                self.assertIn("star_object", self.codes(self.body(extra=f"\n28日(土)の夜は、{w}が見られます。[{self.s['id']}]")))
                self.assertIn("star_object", self.codes(self.body(extra=f"\n{w}は冬の夜空で知られます。")))

    def test_points_and_stars_in_one_sentence_are_stopped(self):
        y, s = self.y["id"], self.s["id"]
        self.assertIn("score_across_biyori", self.codes(self.body(extra=f"\n鍋割山の76.3点は、28日(土)の夜の星より上です。[{y}][{s}]")))
        self.assertIn("star_superlative", self.codes(self.body(extra=f"\n28日(土)の夜は、丹沢湖(山北町)がいちばん長く晴れます。[{s}]")))

    def test_mountain_count_mark_does_not_pass_a_star_sentence(self):
        n = self.d["hazard_counts"][0]
        got = self.codes(self.body(extra=f"\n28日(土)の夜は、条件を通った地点が 2 地点です。[{n['id']}]"))
        self.assertIn("star_unmarked", got)
        self.assertIn("number_mismatch", got)
        self.assertNotIn(n["id"][0], self.t["id"][0])                        # 印の字が別

    def test_star_counts_need_the_star_mark_and_the_right_number(self):
        t = self.t["id"]
        self.assertEqual(self.codes(self.body(extra=f"\n28日(土)の夜は、条件を通った地点は 5 地点です。[{t}]")), set())
        self.assertIn("number_mismatch", self.codes(self.body(extra=f"\n28日(土)の夜は、条件を通った地点は 6 地点です。[{t}]")))
        self.assertIn("number_unmarked", self.codes(self.body(extra="\n条件を通った地点は 5 地点です。")))

    def test_mountain_and_star_counts_are_not_mixed(self):
        n = self.d["hazard_counts"][0]
        x = f"\n28日(土)の夜は条件を通った地点は 5 地点で、{n['label']}は、{n['say'][0]}です。[{n['id']}][{self.t['id']}]"
        self.assertIn("counts_mixed", self.codes(self.body(extra=x)))

    def test_not_examined_and_not_passed_are_not_mixed(self):
        self.assertIn("star_state", self.codes(self.body(extra=f"\n28日(土)の夜の雲は調べていません。[{self.t['id']}]")))
        self.assertIn("star_state", self.codes(self.body(extra=f"\n28日(土)の夜は、条件を通った地点がありません。[{self.t['id']}]")))
        d = make(self, "2026-12-12")
        t = d["stars"]["counts"][0]["id"]
        self.assertIn("star_state", {e["code"] for e in V.check(draft_of(d, f"12日(土)の夜は、条件を通りませんでした。条件を通った地点がありません。[{t}]", []), d)["errors"]
                                     } | {e["code"] for e in V.check(draft_of(d, f"12日(土)の夜は、条件を通った地点がありません。[{t}]", []), d)["errors"]})

    def test_distance_from_the_mountain_must_be_the_pair(self):
        y, s = self.y["id"], self.s["id"]
        self.assertIn("star_distance", self.codes(self.body(f"28日(土)の夜は、丹沢湖(山北町)(鍋割山から直線で約50km)で、18:01〜20:31に晴れ間の見込みです。[{s}][{y}]")))

    def test_time_order_of_the_day(self):
        y, s = self.y["id"], self.s["id"]
        wrong = (f"28日(土)の夜は、丹沢湖(山北町)で18:01〜20:31に晴れ間の見込みです。[{s}]\n"
                 f"朝〜日中は、11月28日(土)の鍋割山が76.3点です。[{y}]\n" + self.hz)
        head = f"11月28日(土)の鍋割山と、夜の星です。[{y}]\n"
        self.assertIn("flow_order", self.codes("結論です。\n" + f"28日(土)の夜は、丹沢湖(山北町)が候補です。[{s}]\n" + wrong.split("\n", 1)[0] + "\n" + wrong.split("\n", 1)[1]))
        self.assertNotIn("flow_order", self.codes(head + self.body()))
        self.assertNotIn("flow_order", self.codes(f"28日(土)の夜は、丹沢湖(山北町)が候補です。[{s}]\n" + self.body()))      # 結論の行では星を先に言ってよい

    def test_required_lines(self):
        d = self.d
        full = draft_of(d, self.body(), [self.y["id"], self.s["id"]])
        for key in ("star_data_time", "star_mode", "star_attribution", "star_regime"):
            with self.subTest(key):
                r = V.check(full.replace(ln(d["lines"][key]) + "\n", ""), d)
                self.assertIn("line_missing", {e["code"] for e in r["errors"]})

    def test_moon_line_and_gap_are_required(self):
        d = make(self, "2026-11-25")
        full = draft_of(d, "見送りです。", [])
        self.assertTrue(V.check(full, d)["ok"], V.check(full, d)["errors"])
        self.assertIn("line_missing", {e["code"] for e in V.check(full.replace(ln(d["lines"]["star_skips"][0]), ""), d)["errors"]})
        d = make(self, "2026-12-12")
        g = next(g for g in d["gaps"] if g["kind"] == "star_not_examined")
        full = draft_of(d, "今回は案がありません。", [])
        self.assertTrue(V.check(full, d)["ok"], V.check(full, d)["errors"])
        self.assertIn("star_gap_missing", {e["code"] for e in V.check(full.replace(ln(g), ""), d)["errors"]})

    def test_picks(self):
        self.assertIn("pick_undeclared", self.codes(self.body(extra=f"\nおすすめは、28日(土)の夜の丹沢湖(山北町)です。[{self.s['id']}]"), [self.y["id"]]))
        self.assertIn("pick_unknown", self.codes(self.body(), [self.y["id"], "S999"]))

    def test_stale_stars_are_not_asserted(self):
        d = make(self, now="2026-11-27T09:00:00+09:00", edit=None)
        self.assertTrue(d["stars"]["stale"])
        self.assertIn("34 時間前の古い予報", d["lines"]["star_data_time"]["text"])

    def test_site_names_with_mountain_names_are_not_read_as_mountains(self):
        x = sfact(self.d, "石割山(山中湖村)")
        r = self.check(self.body(extra=f"\n28日(土)の夜は、石割山(山中湖村)でも18:01〜20:31に晴れ間の見込みです。[{x['id']}]"))
        self.assertTrue(r["ok"], r["errors"])

    def test_named_question_with_a_star_site_is_not_named_other(self):
        d = make(self, "2026-11-28", BOTH, mountains=["鍋割山"])
        r = V.check(F.draft(d), d)
        self.assertTrue(r["ok"], r["errors"])
        mre = re.compile(V.verify_rules()["draft"]["marker_re"])
        X = V.Ctx(d)
        text = r["final"] + "28日(土)の夜は、石割山(山中湖村)です。\n"
        self.assertEqual(N.errors(X, text, lambda t: V.sentences(t, mre), V._norm), [])


class Fallback(unittest.TestCase):
    def test_every_case_passes_the_check(self):
        for edit in (None, fresh):
            base = base_of(self, edit=edit)
            for when in ("今週末", "2026-11-25", "2026-12-04", "2026-12-12", "2026-11-27..2026-12-01", "来週末"):
                for it in (STARS, BOTH):
                    for m in (None, ["石割山", "鍋割山"]) if edit else (None,):
                        with self.subTest(when=when, it=it, m=m, stale=edit is None):
                            d = build(base, question=Q, when=when, interest=it, mountains=m, now=NOW)
                            r = V.check(F.draft(d), d)
                            if {e["code"] for e in r["errors"]} == {"too_long"}:
                                r = V.check(F.draft(d, compact=True), d)
                            self.assertTrue(r["ok"], r["errors"])
                            self.assertLessEqual(len(r["final"]), 2000)

    def test_day_flow_order_and_night_label(self):
        d = make(self, "2026-11-28", STARS)
        t = V.check(F.draft(d), d)["final"]
        self.assertLess(t.index("朝〜日中(山): "), t.index("夜(星): "))
        self.assertIn("夜(星): 11月28日(土)の夜は、", t)
        self.assertNotRegex(t, r"\d日から\d+日")

    def test_moon_night_is_told_first(self):
        d = make(self, "2026-11-25", STARS)
        t = V.check(F.draft(d), d)["final"]
        self.assertTrue(t.startswith("11月25日(水)の夜は、暗い時間帯 10.9 時間のうち月が出ているのが 10.9 時間"), t[:80])
        self.assertNotIn("夜(星): ", t)

    def test_night_not_examined_is_not_called_a_skip(self):
        d = make(self, "2026-12-12", STARS)
        t = V.check(F.draft(d), d)["final"]
        self.assertIn("その夜の雲の予報は今回調べられていません。", t)
        self.assertNotIn("見送る", t)

    def test_star_answer_when_the_mountain_shelf_is_missing(self):
        def edit(shelf_dir):
            (shelf_dir / "proposals" / "yamabiyori.json").unlink()
        d = make(self, "2026-11-28", STARS, edit=edit)
        self.assertEqual(brief_schema_errors(d), [])
        r = V.check(F.draft(d), d)
        self.assertTrue(r["ok"], r["errors"])
        self.assertIn("山の予報は今回使えませんでした。", r["final"])
        self.assertIn("夜(星): ", r["final"])


class VoiceExamples(unittest.TestCase):
    def test_examples_in_answer_voice_pass(self):
        from helpers import ROOT
        text = (ROOT / "docs" / "answer-voice.md").read_text(encoding="utf-8")
        for head, interest in (("### 山と星がそろった日の手本", BOTH), ("### 星が付かない日の手本", BOTH), ("### 星が起点の日の手本", STARS)):
            with self.subTest(head):
                d = make(self, "2026-11-28", interest)
                r = V.check(text.split(head, 1)[1].split("```", 2)[1].strip("\n") + "\n", d)
                self.assertTrue(r["ok"], r["errors"])


class QuestionsAreNotSkippedByTheStopHook(unittest.TestCase):
    def test_star_questions_in_qa(self):
        from helpers import ROOT

        from concierge import stop_hook as SH
        qs = re.findall(r"(?m)^\| \d+ \| ([^|]+?) \| ", (ROOT / "docs" / "qa.md").read_text(encoding="utf-8").split("## 星の問い", 1)[1].split("## 採点", 1)[0])
        self.assertEqual(len(qs), 4)
        for q in qs:
            with self.subTest(q):
                self.assertIsNone(SH.exempt({"prompt": q, "calls": []}))


class Sync(unittest.TestCase):
    def test_load_stars_reads_only_the_star_part(self):
        base = base_of(self)
        self.assertTrue(S.load_stars(base)["ok"])
        shutil.rmtree(Path(base) / "shelf" / "hoshibiyori")
        self.assertEqual(S.load_stars(base)["problem"], "broken_files")
        self.assertTrue(S.load(base)["ok"])                                  # 山は今までどおり使える
        self.assertEqual(S.load_stars(base_of(self, SHELF_FIX))["problem"], "no_hoshibiyori")


if __name__ == "__main__":
    unittest.main()
