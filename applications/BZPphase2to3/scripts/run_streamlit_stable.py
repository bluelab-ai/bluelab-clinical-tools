#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import itertools
import os
import runpy
import sys
import threading
import time
import uuid


_counter = itertools.count()
_counter_lock = threading.Lock()


def _stable_uuid4() -> uuid.UUID:
    """Avoid the host-specific uuid4 crash while preserving unique v4-shaped IDs."""
    with _counter_lock:
        serial = next(_counter)
    payload = f"{time.time_ns()}:{os.getpid()}:{threading.get_ident()}:{serial}".encode()
    digest = hashlib.blake2b(payload, digest_size=16).digest()
    return uuid.UUID(bytes=digest, version=4)


uuid.uuid4 = _stable_uuid4

if __name__ == "__main__":
    sys.argv[0] = "streamlit"
    runpy.run_module("streamlit", run_name="__main__")
