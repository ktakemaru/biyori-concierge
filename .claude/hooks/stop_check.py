"""Claude Code の Stop フックの入口(.claude/settings.json から起動)。中身は concierge/stop_hook.py。
どんな失敗でも終了コード 0 で通す(応答を止めない)。"""
import sys
from pathlib import Path

try:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from concierge import stop_hook
except Exception:
    sys.exit(0)

if __name__ == "__main__":
    sys.exit(stop_hook.main())
