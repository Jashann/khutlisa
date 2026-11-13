"""Counts requests per client over sliding windows, in memory.

The search is open to anyone, so it is counted per client address: so many in any minute and so many in any hour.
The counts live in this process only. They are lost when the server restarts and are not shared between several
server processes, which is enough to slow one caller down and is not a defence against many addresses at once.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from math import ceil
from typing import Callable

MINUTE, HOUR = 60, 3600


class SlidingWindow:
    """`limits` is a list of (how many, in how many seconds). `take(key)` counts one request for `key` and returns
    0, or, when a limit is already full, the number of whole seconds until a place frees up; a refused request is
    not counted. A limit of 0 or less is switched off. `clock` returns seconds and exists so tests need not wait.
    """

    def __init__(self, limits: list[tuple[int, int]], clock: Callable[[], float] = time.monotonic):
        self.limits = [(int(n), int(seconds)) for n, seconds in limits if int(n) > 0]
        self.longest = max((seconds for _, seconds in self.limits), default=0)
        self.clock = clock
        self.seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._swept = clock()

    def _sweep(self, now: float) -> None:
        """Forgets clients whose last request is older than the longest window, so the table cannot grow for ever."""
        for key in [k for k, times in self.seen.items() if not times or now - times[-1] >= self.longest]:
            del self.seen[key]
        self._swept = now

    def take(self, key: str) -> int:
        if not self.limits:
            return 0
        now = self.clock()
        with self._lock:
            if now - self._swept >= MINUTE or len(self.seen) > 10_000:
                self._sweep(now)
            times = self.seen.setdefault(key, deque())
            while times and now - times[0] >= self.longest:
                times.popleft()
            wait = 0.0
            for n, seconds in self.limits:
                inside = [t for t in times if now - t < seconds]
                if len(inside) >= n:
                    wait = max(wait, inside[len(inside) - n] + seconds - now)
            if wait > 0:
                return max(1, ceil(wait))
            times.append(now)
            return 0

    def full_limit(self, key: str) -> tuple[int, int] | None:
        """The longest limit that is full for `key` right now, for the sentence that explains a refusal."""
        now = self.clock()
        with self._lock:
            times = self.seen.get(key) or ()
            full = [(n, seconds) for n, seconds in self.limits if sum(1 for t in times if now - t < seconds) >= n]
        return max(full, key=lambda limit: limit[1], default=None)
