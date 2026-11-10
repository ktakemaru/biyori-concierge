"""取得の側の共通部品(通信なし)。設定・スキーマの読み込み、時刻、JSON の書き出し。"""
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
COLLECT = ROOT / "collect"
SCHEMAS = ROOT / "schemas"
MEASURE_DIR = COLLECT / "measure"
JST = timezone(timedelta(hours=9))
EXIT_HOOK_ABORT = 75          # collect/measure/sitecustomize.py の安全停止
EXIT_HOOK_SETUP = 76          # 同(フックの設定に失敗)


def load_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def config():
    return load_yaml(ROOT / "config.yaml")


@lru_cache(maxsize=None)
def hosts():
    return load_yaml(COLLECT / "hosts.yaml")["hosts"]


def allow_hosts(kind):
    """hosts.yaml に宣言したホストだけ。宣言がなければ空(フックは全拒否)。"""
    return list(hosts().get(kind) or [])


@lru_cache(maxsize=None)
def schema(name):
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def schema_errors(doc, name):
    """スキーマの検査。→ エラーの文のリスト(空なら合格)。"""
    v = Draft202012Validator(schema(name))
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in v.iter_errors(doc)]


def now_jst():
    return datetime.now(JST).replace(microsecond=0)


def iso(dt):
    return None if dt is None else dt.isoformat(timespec="seconds")


def epoch_to_utc_iso(t):
    """Unix 秒 → 'YYYY-MM-DDTHH:MM:SSZ'。数値でなければ None(推測で埋めない)。"""
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        return None
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path):
    """読めない・壊れているときは None。"""
    try:
        p = Path(path)
        if not p.is_file() or p.is_symlink():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def dump_json(doc):
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def write_json(path, doc):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump_json(doc), encoding="utf-8", newline="\n")
    return p
