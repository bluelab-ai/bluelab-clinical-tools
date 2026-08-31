#!/usr/bin/env python3
"""Start the V2.6 frontend after main-thread engine preloading.

The runtime password remains environment-only.  This entry point binds only to
127.0.0.1:8520 when explicitly executed; creating or checking this file does
not start or replace the current local service.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from planning_tool.engine import engine_health, registered_engine  # noqa: E402


EXPECTED_ENGINE_VERSION = "2.3.0"
EXPECTED_MODEL_VERSION = "2.1.0"


def main() -> int:
    if not os.environ.get("XLF055_APP_PASSWORD", "").strip():
        raise RuntimeError(
            "XLF055_APP_PASSWORD must be supplied through the runtime environment"
        )
    os.environ.setdefault("XLF055_APP_USERNAME", "BlueBalloon")

    # Keep the first registered artifact/Parquet read on the process main
    # thread, matching the existing V2.5 Arrow-safety runtime contract.
    registered_engine()
    health = engine_health()
    if health.get("status") != "ready":
        raise RuntimeError("Registered scenario engine failed startup validation")
    if health.get("engine_version") != EXPECTED_ENGINE_VERSION:
        raise RuntimeError("Unexpected registered scenario engine version")
    if health.get("model_version") != EXPECTED_MODEL_VERSION:
        raise RuntimeError("Unexpected registered model version")

    from streamlit.web import cli as streamlit_cli

    sys.argv = [
        "streamlit",
        "run",
        str(APP_ROOT / "app.py"),
        "--server.address=127.0.0.1",
        "--server.port=8520",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]
    return int(streamlit_cli.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
