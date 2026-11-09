"""Proxies shared through the broker (``linecaster.net.proxies.ProxyPool``). One proxy per worker (``1``): each worker
holds exactly one, never another's; a block swaps it for a free one at once and nobody takes the blocked one until
its mark ends; all blocked pauses until a mark ends; a claim race lost is replaced, said at INFO. Up to N per worker:
claimed one by one, never more. A fair share (``share``, the default): two workers never use one proxy at once, so
the rate limits per proxy hold across them; a block by one worker is seen by the other at once; a crashed worker's
proxies come free after the lease time; no hoarding at the start, a worker that joins gets its share by rebalancing.
Turns run on a fake clock; time passes for the broker's files by moving their modification times back, or by the
broker's clock."""
import os
import time
from collections import defaultdict

import pytest
from loguru import logger

from linecaster.broker import LEASE_TTL, Broker
from linecaster.errors import PipelineConfigError
from linecaster.net.proxies import KIND, SHARE, ProxyPool, proxy_id, shared_pool

PROXIES = [f"http://user:secret@10.0.0.{i}:8080" for i in range(4)]


class Clock:
    """A monotonic clock that moves only when told."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def age(folder, seconds: float) -> None:
    for root, _, files in os.walk(folder):
        for name in files:
            path = os.path.join(root, name)
            m = os.stat(path).st_mtime
            os.utime(path, (m - seconds, m - seconds))


def worker(tmp_path, name: str, proxies=PROXIES, clock=None, broker_clock=time.time, per_worker=SHARE) -> ProxyPool:
    broker = Broker(str(tmp_path), worker=name, clock=broker_clock)
    broker.heartbeat()
    return ProxyPool(broker, proxies, clock=clock or Clock(), keep_alive=False, per_worker=per_worker)


def owned(pool: ProxyPool) -> set[str]:
    return {pool.proxies[pid] for pid in pool.broker.held(KIND)}


def test_two_workers_never_share_a_proxy_and_its_rate_limit_holds_across_them(tmp_path):
    clock = Clock()
    a, b = worker(tmp_path, "a-0", clock=clock), worker(tmp_path, "b-0", clock=clock)
    assert a.fill("tile.loc.gov") == 2 and b.fill("tile.loc.gov") == 2          # ceil(4 / 2) each
    assert not owned(a) & owned(b) and len(owned(a) | owned(b)) == 4
    starts = defaultdict(list)
    users = defaultdict(set)
    for _ in range(40):                                  # both send as fast as the turns allow: 0.5 s per proxy
        for name, pool in (("a", a), ("b", b)):
            proxy, wait = pool.pick("tile.loc.gov", 0.5)
            starts[proxy].append(clock.t + wait)
            users[proxy].add(name)
    assert all(len(u) == 1 for u in users.values())       # one worker per proxy
    for times in starts.values():
        times.sort()
        assert all(later - earlier >= 0.5 - 1e-9 for earlier, later in zip(times, times[1:]))
        assert max(sum(1 for t in times if w <= t < w + 1) for w in times) <= 2          # 2 per second at most
    assert sorted(len(t) for t in starts.values()) == [20, 20, 20, 20]                 # spread evenly
    assert "secret" not in "".join(p.name for p in (tmp_path / KIND).iterdir())


def test_a_block_by_one_worker_is_never_used_by_the_other(tmp_path):
    proxies = PROXIES[:2]
    a = worker(tmp_path, "a-0", proxies)
    assert a.fill("lccn.loc.gov") == 2                                          # alone: both
    b = worker(tmp_path, "b-0", proxies)
    blocked = a.pick("lccn.loc.gov", 0)[0]
    a.block(blocked, "lccn.loc.gov", 3600, status=429)
    assert blocked not in owned(a) and a.counts() == (1, 1, 0)                  # blocked everywhere it fetches
    assert b.fill("lccn.loc.gov", force=True) == 0 and b.pick("lccn.loc.gov", 0) is None   # seen at once
    first, others, free = b.outlook("lccn.loc.gov")
    assert 3590 < first <= 3600 and (others, free) == (1, 0)
    assert b.fill("www.loc.gov", force=True) == 1                               # free for another host
    assert b.pick("www.loc.gov", 0)[0] == blocked and b.pick("lccn.loc.gov", 0) is None


def test_all_blocked_the_worker_waits_and_goes_on_when_a_block_ends(tmp_path):
    offset = [0.0]
    a = worker(tmp_path, "a-0", PROXIES[:1], broker_clock=lambda: time.time() + offset[0])
    assert a.fill("lccn.loc.gov") == 1
    a.block(PROXIES[0], "lccn.loc.gov", 30, status=429)
    assert a.pick("lccn.loc.gov", 0) is None and a.fill("lccn.loc.gov", force=True) == 0
    first, others, free = a.outlook("lccn.loc.gov")
    assert 25 < first <= 30 and (others, free) == (0, 0)
    offset[0] = 31                                                               # the block has ended
    assert a.fill("lccn.loc.gov", force=True) == 1 and a.pick("lccn.loc.gov", 0)[0] == PROXIES[0]


def test_a_broken_proxy_is_left_out_everywhere_after_its_threshold(tmp_path):
    a = worker(tmp_path, "a-0", PROXIES[:2])
    a.fill("lccn.loc.gov")
    a.broken(PROXIES[0], 2, 3600)
    assert PROXIES[0] in owned(a)                                                # one failure of two
    a.answered(PROXIES[0])
    a.broken(PROXIES[0], 2, 3600)
    a.broken(PROXIES[0], 2, 3600)
    assert owned(a) == {PROXIES[1]}
    (mark,) = (tmp_path / KIND / proxy_id(PROXIES[0]) / "marks" / "*").iterdir()
    assert mark.name.endswith(".json")


def test_a_crashed_workers_proxies_come_free_after_the_lease_time(tmp_path):
    a = worker(tmp_path, "a-0", PROXIES[:2])
    assert a.fill("lccn.loc.gov") == 2
    b = worker(tmp_path, "b-0", PROXIES[:2])
    assert b.fill("lccn.loc.gov", force=True) == 0                              # both held by a
    assert b.outlook("lccn.loc.gov") == (None, 2, 0)
    age(tmp_path, LEASE_TTL + 1)                                                 # a crashed: no renew
    b.broker.heartbeat()
    assert b.fill("lccn.loc.gov", force=True) == 2                              # alone now: both
    assert owned(b) == set(PROXIES[:2])


def test_a_worker_that_joins_gets_its_share_at_the_next_renew(tmp_path):
    a = worker(tmp_path, "a-0")
    assert a.fill("tile.loc.gov") == 2                                          # at most 2 at a fill
    a.rebalance()
    assert len(owned(a)) == 4                                                    # its share, by rebalancing
    a.pick("www.loc.gov", 0)                                                     # it uses two hosts
    blocked = a.pick("www.loc.gov", 0)[0]
    a.block(blocked, "www.loc.gov", 3600, status=403)                           # blocked at one: kept
    assert blocked in owned(a)
    b = worker(tmp_path, "b-0")
    assert b.fill("tile.loc.gov", force=True) == 0
    a.broker.renew()
    a.rebalance()
    assert len(owned(a)) == 2 and blocked not in owned(a)                        # the blocked one given back first
    assert b.fill("tile.loc.gov", force=True) == 2
    assert not owned(a) & owned(b) and blocked in owned(b)


def test_sharing_does_not_hoard_at_the_start_and_converges_by_rebalancing(tmp_path):
    """Alone, a worker takes 2 at its first fill and grows to its share (8) by rebalancing, at most doubling; one that
    joins finds every proxy held, and the rebalancing hands it its half."""
    proxies = [f"http://10.0.1.{i}:8080" for i in range(8)]
    a = worker(tmp_path, "a-0", proxies)
    assert a.fill("tile.loc.gov") == 2
    a.rebalance()
    assert len(owned(a)) == 4
    a.rebalance()
    assert len(owned(a)) == 8
    b = worker(tmp_path, "b-0", proxies)
    assert b.fill("tile.loc.gov", force=True) == 0 and b.pick("tile.loc.gov", 0) is None
    a.rebalance()                                                                # its share is 4 now
    assert len(owned(a)) == 4
    assert b.fill("tile.loc.gov", force=True) == 2                              # 2 at a fill, though its share is 4
    b.rebalance()
    assert len(owned(b)) == 4 and not owned(a) & owned(b)


# ---------------------------------------------------------------- one proxy per worker, up to N


def one(tmp_path, name: str, proxies=PROXIES, **kwargs) -> ProxyPool:
    return worker(tmp_path, name, proxies, per_worker=1, **kwargs)


def test_one_proxy_per_worker_each_holds_exactly_one_never_the_same(tmp_path):
    clock = Clock()
    a, b = one(tmp_path, "a-0", clock=clock), one(tmp_path, "b-0", clock=clock)
    assert a.fill("tile.loc.gov") == 1 and b.fill("tile.loc.gov") == 1
    for pool in (a, b):
        pool.rebalance()                                                         # no fair share: still one
        pool.rebalance()
    assert len(owned(a)) == len(owned(b)) == 1 and not owned(a) & owned(b)
    assert a.fill("tile.loc.gov", force=True) == 0                              # one usable: nothing to claim
    (mine,) = owned(a)
    picks = [a.pick("tile.loc.gov", 0.5) for _ in range(4)]
    assert [p for p, _ in picks] == [mine] * 4 and [w for _, w in picks] == [0, 0.5, 1.0, 1.5]   # its limit
    assert a.counts() == (1, 0, 2)                                              # held, blocked, free


def test_a_block_swaps_to_a_free_proxy_at_once_and_nobody_takes_the_blocked_one_until_its_mark_ends(tmp_path):
    offset = [0.0]

    def clock():
        return time.time() + offset[0]

    pools = [one(tmp_path, f"w-{i}", broker_clock=clock) for i in range(4)]
    a, b, c, d = pools
    assert a.fill("lccn.loc.gov") == 1
    (blocked,) = owned(a)
    a.block(blocked, "lccn.loc.gov", 30, status=429)
    assert owned(a) == set() and a.pick("lccn.loc.gov", 0) is None
    assert a.fill("lccn.loc.gov") == 1                                          # at once, not after FILL_SECONDS
    assert len(owned(a)) == 1 and blocked not in owned(a)
    assert b.fill("lccn.loc.gov") == 1 and c.fill("lccn.loc.gov") == 1         # the two other free ones
    assert d.fill("lccn.loc.gov") == 0 and blocked not in owned(b) | owned(c)   # the blocked one: nobody's
    first, others, free = d.outlook("lccn.loc.gov")
    assert 25 < first <= 30 and (others, free) == (3, 0)
    offset[0] = 31                                                               # its mark has ended
    assert d.fill("lccn.loc.gov") == 1 and owned(d) == {blocked}


def test_all_blocked_pauses_and_resumes_when_a_mark_ends(tmp_path):
    offset = [0.0]
    a = one(tmp_path, "a-0", PROXIES[:2], broker_clock=lambda: time.time() + offset[0])
    assert a.fill("lccn.loc.gov") == 1
    a.block(a.pick("lccn.loc.gov", 0)[0], "lccn.loc.gov", 60, status=429)
    assert a.fill("lccn.loc.gov") == 1
    a.block(a.pick("lccn.loc.gov", 0)[0], "lccn.loc.gov", 30, status=429)
    assert a.fill("lccn.loc.gov") == 0 and a.pick("lccn.loc.gov", 0) is None   # every one blocked: a pause
    first, others, free = a.outlook("lccn.loc.gov")
    assert 25 < first <= 30 and (others, free) == (0, 0)
    offset[0] = 31                                                               # the first mark has ended
    assert a.fill("lccn.loc.gov") == 1 and a.pick("lccn.loc.gov", 0) is not None


def test_a_proxy_blocked_at_one_of_two_hosts_is_swapped_for_one_usable_at_both(tmp_path):
    a = one(tmp_path, "a-0")
    assert a.fill("www.loc.gov") == 1
    (proxy,) = owned(a)
    a.block(proxy, "lccn.loc.gov", 3600, status=403)                            # usable at www.loc.gov still: kept
    assert owned(a) == {proxy} and a.pick("lccn.loc.gov", 0) is None
    assert a.fill("lccn.loc.gov", force=True) == 1                              # a swap: still one
    (other,) = owned(a)
    assert other != proxy and a.pick("lccn.loc.gov", 0)[0] == other and a.pick("www.loc.gov", 0)[0] == other


def test_a_claim_race_lost_is_replaced_at_once_said_at_info(tmp_path):
    """Two workers both believed they won a proxy; at the renew the later claim finds the earlier, gives it up (INFO,
    no WARNING) and claims another at once."""
    lines = []
    sink = logger.add(lambda m: lines.append((m.record["level"].name, m.record["message"])), level="DEBUG")
    try:
        a = one(tmp_path, "a-0")
        assert a.fill("tile.loc.gov") == 1
        (raced,) = owned(a)
        leases = tmp_path / KIND / proxy_id(raced) / "leases"
        (leases / "20200101T000000000Z-z-0.json").write_text('{"holder": "z-0"}')   # z-0's earlier claim
        assert a.broker.renew() == [(KIND, proxy_id(raced))]
        a.rebalance()                                                            # after the renew (keep_alive)
        assert len(owned(a)) == 1 and raced not in owned(a)
        assert any(lvl == "INFO" and "lost a claim race" in m and "to z-0; it takes another" in m for lvl, m in lines)
        assert not [m for lvl, m in lines if lvl == "WARNING"]
    finally:
        logger.remove(sink)


def test_up_to_n_per_worker_are_claimed_one_by_one_never_more(tmp_path):
    proxies = [f"http://10.0.2.{i}:8080" for i in range(8)]
    a, b = (worker(tmp_path, n, proxies, per_worker=3) for n in ("a-0", "b-0"))
    assert a.fill("tile.loc.gov") == 1 and b.fill("tile.loc.gov") == 1
    sizes = []
    for _ in range(4):
        for pool in (a, b):
            pool.rebalance()
        sizes.append((len(owned(a)), len(owned(b))))
    assert sizes == [(2, 2), (3, 3), (3, 3), (3, 3)] and not owned(a) & owned(b)


def test_more_than_n_inherited_are_given_back(tmp_path):
    proxies = [f"http://10.0.3.{i}:8080" for i in range(6)]
    first = worker(tmp_path, "a-0", proxies)                                    # sharing: it holds 6
    first.fill("tile.loc.gov")
    first.rebalance()
    first.rebalance()
    assert len(owned(first)) == 6
    again = ProxyPool(Broker(str(tmp_path), worker="a-0"), proxies, clock=Clock(), keep_alive=False, per_worker=2)
    again.pick("tile.loc.gov", 0)
    again.rebalance()
    assert again.held() == 2 and len(again.broker.held(KIND)) == 2


def test_a_list_shared_by_fetchers_has_one_setting(tmp_path, monkeypatch):
    from linecaster.net import proxies

    monkeypatch.setattr(proxies, "_POOLS", {})                                   # this test's pools only
    broker = Broker(str(tmp_path), worker="a-0")
    pool = shared_pool(broker, PROXIES[:2], per_worker=2)
    assert shared_pool(broker, PROXIES[:2], per_worker=2) is pool
    with pytest.raises(PipelineConfigError, match="proxies_per_worker"):
        shared_pool(broker, PROXIES[:2], per_worker=SHARE)
    with pytest.raises(PipelineConfigError, match="not 0"):
        ProxyPool(broker, PROXIES, per_worker=0, keep_alive=False)
