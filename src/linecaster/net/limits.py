"""Rate limits for http(s) requests: ``N/S`` windows (at most ``N`` requests in any ``S`` seconds), all holding at
once, as a sliding window over the times the last ``N`` requests went out (``RateLimiter``). One limiter per
``linecaster.net.http.HTTPFetcher``, used from its event loop."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable, Iterable

#: a request that waited for a window to free up waits this much longer, so it does not land on the window's edge
SLACK = 0.05


def check_rate_limits(limits: Iterable[tuple[int, float]]) -> list[tuple[int, float]]:
    """``limits`` as ``(int, float)`` pairs, or ``ValueError``: each window allows at least one request in more than
    0 seconds, and the windows agree (sorted by length, a longer one allows more requests but a lower rate; e.g.
    ``[(3, 1), (150, 60)]``, not ``[(3, 1), (2, 60)]``)."""
    out = []
    for n, s in limits:
        if n < 1 or s <= 0:
            raise ValueError(f"Invalid rate limit ({n}, {s}): requests must be >= 1 and seconds > 0")
        out.append((int(n), float(s)))
    ordered = sorted(out, key=lambda limit: limit[1])
    for (n1, s1), (n2, s2) in zip(ordered, ordered[1:]):
        if not (s2 > s1 and n2 > n1 and n2 / s2 <= n1 / s1):
            raise ValueError(f"Inconsistent rate limits {out}: longer windows must allow more requests, "
                             "but a lower average rate, than shorter ones")
    return out


class RateLimiter:
    """Lets a request go out when every window has room: fewer than ``N`` requests went out in the last ``S``
    seconds. ``acquire`` waits until then, in the order the requests came (one waits at a time, the others queue
    behind it), and counts the request. ``clock`` (monotonic seconds) can be replaced in tests."""

    def __init__(self, limits: Iterable[tuple[int, float]], clock: Callable[[], float] = time.monotonic):
        self.limits = check_rate_limits(limits)
        self._clock = clock
        self._sent = [deque(maxlen=n) for n, _ in self.limits]   # the last N times a request went out, per window
        self._lock: asyncio.Lock | None = None                    # made in the event loop that uses it

    def wait(self) -> float:
        """Seconds until every window has room (0: now)."""
        now = self._clock()
        return max((sent[0] + s - now for (n, s), sent in zip(self.limits, self._sent) if len(sent) == n),
                   default=0.0)

    async def acquire(self) -> None:
        """Wait until a request may go out, and count it."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            while (wait := self.wait()) > 0:
                await asyncio.sleep(wait + SLACK)
            now = self._clock()
            for sent in self._sent:
                sent.append(now)
