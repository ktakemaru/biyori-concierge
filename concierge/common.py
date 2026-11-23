"""答える側の共通部品: 置き場・設定・時刻・JSON。通信しない。"""
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from collect.common import ROOT, SCHEMAS, config as base_config

JST = timezone(timedelta(hours=9))
WEEKDAY_JA = "月火水木金土日"
PKG = Path(__file__).resolve().parent
DATA = PKG / "data"
NL = "\n"


def data_dir(env=None):
    """手元の置き場。BIYORI_CONCIERGE_DATA_DIR → Windows は %LOCALAPPDATA%\\biyori-concierge → ~/.local/share/biyori-concierge。
    リポジトリの中は使わない(指されたら ValueError)。"""
    env = os.environ if env is None else env
    p = env.get("BIYORI_CONCIERGE_DATA_DIR")
    if p:
        d = Path(p)
    elif sys.platform == "win32" and env.get("LOCALAPPDATA"):
        d = Path(env["LOCALAPPDATA"]) / "biyori-concierge"
    else:
        d = Path.home() / ".local" / "share" / "biyori-concierge"
    d = d.resolve()
    if d == ROOT or ROOT in d.parents:
        raise ValueError(f"置き場がリポジトリの中を指している: {d}(BIYORI_CONCIERGE_DATA_DIR を直す)")
    return d


def _merge(a, b):
    out = deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else deepcopy(v)
    return out


@lru_cache(maxsize=None)
def _local_config():
    p = ROOT / "config.local.yaml"
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def config():
    """config.yaml に config.local.yaml(あれば)を重ねたもの。"""
    return _merge(base_config(), _local_config())


SCHEMA_DIR = SCHEMAS     # 資料 biyori-brief/1 のスキーマも、棚・提案の契約と同じリポジトリ直下の schemas/ に置く(利用者の決定。2026-11-23)


@lru_cache(maxsize=None)
def _brief_schema():
    return json.loads((SCHEMA_DIR / "biyori-brief.schema.json").read_text(encoding="utf-8"))


def brief_schema_errors(doc):
    """資料のスキーマの検査。→ エラーの文のリスト(空なら合格)。"""
    from jsonschema import Draft202012Validator
    v = Draft202012Validator(_brief_schema())
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in v.iter_errors(doc)]


@lru_cache(maxsize=None)
def verify_rules():
    return yaml.safe_load((DATA / "verify.yaml").read_text(encoding="utf-8"))


def parse_now(s):
    """--now(ISO 8601)→ JST の datetime。オフセットが無ければ JST とみなす。None なら現在時刻。"""
    if not s:
        return datetime.now(JST).replace(microsecond=0)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def iso(dt):
    return None if dt is None else dt.isoformat(timespec="seconds")


def parse_iso(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else None


def dump_json(doc):
    return json.dumps(doc, ensure_ascii=False, indent=1) + NL


def write_text(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def read_json(path):
    try:
        p = Path(path)
        if not p.is_file() or p.is_symlink():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def md_label(d):
    """date → 「11月22日(日)」。"""
    return f"{d.month}月{d.day}日({WEEKDAY_JA[d.weekday()]})"


def jst_time_label(dt):
    """datetime → 「11月22日(日) 7:32」。"""
    dt = dt.astimezone(JST)
    return f"{md_label(dt.date())} {dt.hour}:{dt.minute:02d}"
