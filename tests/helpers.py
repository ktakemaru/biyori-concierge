"""テストの共通部品。import すると nonet(ソケット禁止)も有効になる。"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

import nonet  # noqa: F401  (ソケット禁止)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"
FAKE_YAMA = FIX / "yamabiyori"
HOOK_PATH = ROOT / "collect" / "measure" / "sitecustomize.py"
NET_SCRIPT = FIX / "net_probe.py"


def tmpdir(test, prefix="biyori-c-"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    test.addCleanup(shutil.rmtree, d, True)
    return d


def load_hook(**env):
    """計測フックを、フックを有効にせずに(BIYORI_REQ_LOG なし)モジュールとして読む。env は読み込み時だけ設定する。"""
    keep = {k: os.environ.pop(k, None) for k in list(os.environ) if k.startswith("BIYORI_")}
    os.environ.update(env)
    err = io.StringIO()
    try:
        spec = importlib.util.spec_from_file_location("biyori_hook_under_test", HOOK_PATH)
        m = importlib.util.module_from_spec(spec)
        with redirect_stderr(err):
            spec.loader.exec_module(m)
    finally:
        for k in env:
            os.environ.pop(k, None)
        for k, v in keep.items():
            if v is not None:
                os.environ[k] = v
    return m, err.getvalue()


class Stopped(Exception):
    pass
