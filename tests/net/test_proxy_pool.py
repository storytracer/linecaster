"""Proxies shared through the broker (``linecaster.net.proxies.ProxyPool``): two workers never use one proxy at once,
so the rate limits per proxy hold across them; a block by one worker is seen by the other at once; no proxy usable
pauses the worker until a block ends; a crashed worker's proxies come free after the lease time; a worker that joins
gets its share. Turns run on a fake clock; time passes for the broker's files by moving their modification times
back."""
import os
import time
from collections import defaultdict

from linecaster.broker import LEASE_TTL, Broker
from linecaster.net.proxies import KIND, ProxyPool, proxy_id

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


def worker(tmp_path, name: str, proxies=PROXIES, clock=None, broker_clock=time.time) -> ProxyPool:
    broker = Broker(str(tmp_path), worker=name, clock=broker_clock)
    broker.heartbeat()
    return ProxyPool(broker, proxies, clock=clock or Clock(), keep_alive=False)


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
    assert a.fill("tile.loc.gov") == 4
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
