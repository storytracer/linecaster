"""Rate limits (``linecaster.net.limits``): N/S windows checked, and requests spaced so every window holds."""
import asyncio
import time

import pytest

from linecaster.net.limits import RateLimiter, check_rate_limits


def test_windows_are_checked():
    assert check_rate_limits([(150, 60), (3.0, 1)]) == [(150, 60.0), (3, 1.0)]
    with pytest.raises(ValueError, match="Invalid rate limit"):
        check_rate_limits([(0, 1)])
    with pytest.raises(ValueError, match="Invalid rate limit"):
        check_rate_limits([(1, 0)])
    with pytest.raises(ValueError, match="Inconsistent"):
        check_rate_limits([(3, 1), (2, 60)])           # a longer window allowing fewer requests
    with pytest.raises(ValueError, match="Inconsistent"):
        check_rate_limits([(3, 1), (300, 60)])         # a longer window allowing a higher rate


def test_every_window_holds():
    """4 per 0.2 s and 6 per 1 s: 6 requests go out at once, the 7th after the first leaves the 1 s window; within
    any 0.2 s never more than 4, within any 1 s never more than 6."""
    limiter = RateLimiter([(4, 0.2), (6, 1.0)])

    async def main():
        sent = []
        for _ in range(8):
            await limiter.acquire()
            sent.append(time.monotonic())
        return sent

    sent = asyncio.run(main())
    for i, t in enumerate(sent):
        assert sum(1 for u in sent[:i + 1] if t - u < 0.2) <= 4
        assert sum(1 for u in sent[:i + 1] if t - u < 1.0) <= 6
    assert 1.0 <= sent[6] - sent[0] < 1.3


def test_the_wait_is_until_the_oldest_request_of_a_full_window_leaves_it():
    now = [100.0]
    limiter = RateLimiter([(2, 10)], clock=lambda: now[0])

    async def two():
        await limiter.acquire()
        now[0] = 103.0
        await limiter.acquire()

    asyncio.run(two())
    assert limiter.wait() == 7.0
    now[0] = 111.0
    assert limiter.wait() == 0.0
