"""A small in-process sliding-window limiter.

Used on the vault's write and verify endpoints so they can't be driven as a free
key-validity oracle. State is per worker process, which is the right trade for a
single-instance deploy; move it to Redis if this ever runs on more than one.
"""
import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        """Record an attempt against ``key``; False once the window is full."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            cutoff = now - self._window
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)
