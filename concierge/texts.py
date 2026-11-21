"""決まった文の部品(status・brief・控えの文で共通)。値は棚から、言い方はここだけで決める。"""
from .common import JST, md_label, parse_iso, jst_time_label

SLOT_JA = {"morning": "朝", "evening": "夕"}
MODEL_JA = {"jma_msm": "気象庁 MSM", "ecmwf_ifs025": "ECMWF"}


def init_label(init):
    """'2026-11-21T15:00:00Z' → 「11月22日(日) 0時」(日本時間)。読めなければ None。"""
    t = parse_iso(init)
    if t is None:
        return None
    t = t.astimezone(JST)
    return f"{md_label(t.date())} {t.hour}時"


def runs_text(model_runs):
    """→ 「気象庁 MSM は 11月22日(日) 0時の回、ECMWF は 11月21日(土) 21時の回」。分からないものは「不明」。"""
    parts = []
    for key, ja in MODEL_JA.items():
        lab = init_label(((model_runs or {}).get(key) or {}).get("init"))
        parts.append(f"{ja} は {lab}の回" if lab else f"{ja} の回は不明")
    return "、".join(parts)


def data_time_label(entry):
    t = parse_iso((entry or {}).get("data_time"))
    return None if t is None else jst_time_label(t)


def coverage_counts(entry):
    c = (entry or {}).get("coverage") or {}
    total, fetched, pool = c.get("total_mountains"), c.get("fetched"), c.get("pool_size")
    return total, pool, fetched
