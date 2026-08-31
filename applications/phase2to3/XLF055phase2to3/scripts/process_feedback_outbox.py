#!/usr/bin/env python3
"""Process the V2.2 feedback mail outbox without logging message content."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from planning_tool.feedback import process_email_outbox  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    interval = max(10, min(args.interval_seconds, 300))
    while True:
        result = process_email_outbox(limit=args.limit)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.once:
            unhealthy = bool(
                result["config_error"]
                or result["retry_scheduled"]
                or result["permanent_failed"]
                or result["terminal_failed_count"]
            )
            return 1 if unhealthy else 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
