from __future__ import annotations

import subprocess
import sys
import time


def main() -> int:
    mode = sys.argv[1]
    if mode == "child":
        time.sleep(120)
        return 0
    if mode == "pass":
        import os

        if any(name in os.environ for name in ("ANTHROPIC_API_KEY", "CODEX_HOME")):
            return 1
        print("2 passed, 1 skipped in 0.10s", flush=True)
        return 0
    if mode == "fail":
        print("2 passed, 1 failed in 0.10s", flush=True)
        return 1
    if mode == "timeout":
        subprocess.Popen([sys.executable, __file__, "child"])
        time.sleep(120)
        return 0
    if mode == "env":
        import os

        leaked = any(name in os.environ for name in ("ANTHROPIC_API_KEY", "CODEX_HOME"))
        print("1 passed" if not leaked else "1 failed", flush=True)
        return 1 if leaked else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
