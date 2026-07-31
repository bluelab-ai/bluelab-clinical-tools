from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "outputs/step19_dynamic_chinese_mvp/engine_cache"


class ResultCache:
    def __init__(self, cache_dir: str | Path = CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        value["cached"] = True
        return value

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self.cache_dir / f"{key}.json"
        payload = copy.deepcopy(value)
        payload["cached"] = False
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
