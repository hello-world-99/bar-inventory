import threading
import time
from collections import deque


class SlidingWindowLimiter:
    """In-memory sliding-window limiter; adequate for the single backend process of the MVP.

    Keys whose window has emptied are dropped, and the number of tracked keys is capped,
    so a flood of random keys cannot grow memory without bound.
    """

    def __init__(self, max_events: int, window_seconds: int, max_keys: int = 50_000):
        self.max_events = max_events
        self.window = window_seconds
        self.max_keys = max_keys
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _live(self, key: str, now: float) -> deque[float] | None:
        q = self._events.get(key)
        if q is None:
            return None
        while q and now - q[0] > self.window:
            q.popleft()
        if not q:
            del self._events[key]
            return None
        return q

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            q = self._live(key, time.monotonic())
            return q is not None and len(q) >= self.max_events

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._live(key, now)
            if q is None:
                if len(self._events) >= self.max_keys:
                    self._evict(now)
                q = self._events[key] = deque()
            q.append(now)

    def _evict(self, now: float) -> None:
        for k in list(self._events):
            self._live(k, now)
        # Still full: drop the 10% least recently active keys at once so the sort cost is amortized.
        if len(self._events) >= self.max_keys:
            batch = max(1, self.max_keys // 10)
            for k in sorted(self._events, key=lambda k: self._events[k][-1])[:batch]:
                del self._events[k]

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        return len(self._events)
