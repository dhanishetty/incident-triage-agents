"""What the shop records about itself: logs, one metrics sample per second, and a history of deploys and config changes.

These stand in for Log Analytics, Azure Monitor metrics and the Activity Log. The shop serves them over HTTP
(see app.py) and the triage backend's environment connectors read them.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class Telemetry:
    def __init__(self) -> None:
        self.logs: deque[dict] = deque(maxlen=5000)
        self.samples: deque[dict] = deque(maxlen=1800)  # 30 minutes at one per second
        self.changes: list[dict] = []
        self._lock = threading.Lock()

    def log(self, level: str, msg: str, **fields) -> None:
        with self._lock:
            self.logs.append({"ts": time.time(), "level": level, "msg": msg, **fields})

    def change(self, kind: str, detail: str, ts: float | None = None, **meta) -> None:
        with self._lock:
            self.changes.append({"ts": ts if ts is not None else time.time(), "kind": kind, "detail": detail, "meta": meta})

    def add_sample(self, sample: dict) -> None:
        with self._lock:
            self.samples.append(sample)

    def logs_since(self, seconds: float, level: str | None = None, limit: int = 2000) -> list[dict]:
        cutoff = time.time() - seconds
        with self._lock:
            out = [e for e in self.logs if e["ts"] >= cutoff and (level is None or e["level"] == level)]
        return out[-limit:]

    def samples_since(self, seconds: float) -> list[dict]:
        cutoff = time.time() - seconds
        with self._lock:
            return [s for s in self.samples if s["ts"] >= cutoff]

    def changes_since(self, seconds: float) -> list[dict]:
        cutoff = time.time() - seconds
        with self._lock:
            return [c for c in self.changes if c["ts"] >= cutoff]

    def clear(self) -> None:
        with self._lock:
            self.logs.clear()
            self.samples.clear()
            self.changes.clear()
