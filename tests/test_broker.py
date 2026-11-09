"""The broker (``linecaster.broker``): leases claimed, renewed and released; two claims at once decided by listing;
leases and heartbeats that expire without a renew; marks per scope that expire and are deleted by whoever sees them;
the fair share; worker slots that outlive processes, their leases inherited by the slot's next process. Time passes
for the storage by moving the files' modification times back (``age``), or for a broker by its clock."""
import os
import threading
import time

import pytest

from linecaster import broker as brokers
from linecaster.broker import EVERY_SCOPE, LEASE_TTL, Broker


@pytest.fixture(autouse=True)
def one_worker(monkeypatch):
    """This process is worker 0 of 1 (``set_worker_index``), so its brokers search the slots from 0, lowest free
    first, and the tests can name them."""
    monkeypatch.setattr(brokers, "_WORKER_INDEX", [(0, 1)])


def age(folder, seconds: float) -> None:
    """``seconds`` pass for everything written to ``folder`` so far."""
    for root, _, files in os.walk(folder):
        for name in files:
            path = os.path.join(root, name)
            m = os.stat(path).st_mtime
            os.utime(path, (m - seconds, m - seconds))


def leases(folder, kind: str, rid: str) -> list[str]:
    path = folder / kind / rid / "leases"
    return sorted(p.name for p in path.iterdir()) if path.exists() else []


def test_claim_renew_release(tmp_path):
    b = Broker(str(tmp_path), worker="w-0")
    assert b.claim("proxies", "a") and b.claim("proxies", "a")          # holding it already is holding it
    assert b.held("proxies") == ["a"]
    (name,) = leases(tmp_path, "proxies", "a")
    assert name.endswith("-w-0.json") and (tmp_path / "broker.json").exists() is False   # explicit worker: no init
    age(tmp_path, LEASE_TTL - 10)
    assert b.renew() == [] and leases(tmp_path, "proxies", "a") == [name]   # the same file, rewritten
    age(tmp_path, 20)                                                    # 190 s since the claim, 20 since the renew
    assert not Broker(str(tmp_path), worker="w-1").claim("proxies", "a")
    b.release("proxies", "a")
    assert b.held("proxies") == [] and leases(tmp_path, "proxies", "a") == []
    assert Broker(str(tmp_path), worker="w-1").claim("proxies", "a")


def test_two_claims_at_once_one_wins_and_the_loser_cleans_up(tmp_path):
    """Both list (nothing), both write, both list again: the earliest lease wins (then the worker id)."""
    barrier = threading.Barrier(2, timeout=10)

    class Racing(Broker):
        def _write(self, path, record):
            if "/leases/" in path and path.startswith("proxies/"):
                barrier.wait()                                           # both listed before either wrote
                super()._write(path, record)
                barrier.wait()                                           # both wrote before either lists
            else:
                super()._write(path, record)

    brokers = [Racing(str(tmp_path), worker=f"w-{n}") for n in range(2)]
    results = [None, None]

    def claim(n):
        results[n] = brokers[n].claim("proxies", "a")

    threads = [threading.Thread(target=claim, args=(n,)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False, True]
    winner = results.index(True)
    (name,) = leases(tmp_path, "proxies", "a")                          # the loser deleted its lease
    assert name.endswith(f"-w-{winner}.json")
    assert brokers[winner].held("proxies") == ["a"] and brokers[1 - winner].held("proxies") == []


def test_a_lease_expires_without_a_renew(tmp_path):
    a = Broker(str(tmp_path), worker="w-0")
    assert a.claim("proxies", "a")
    ahead = Broker(str(tmp_path), worker="w-1", clock=lambda: time.time() + LEASE_TTL + 1)   # its clock: later
    assert ahead.claim("proxies", "a")                                  # w-0's lease expired: deleted, claimed
    assert [n.endswith("-w-1.json") for n in leases(tmp_path, "proxies", "a")] == [True]
    assert a.renew() == [("proxies", "a")] and a.held("proxies") == []  # its file gone: it gives it up
    assert [n.endswith("-w-1.json") for n in leases(tmp_path, "proxies", "a")] == [True]


def test_marks_hold_per_scope_until_they_expire(tmp_path):
    a, b = Broker(str(tmp_path), worker="w-0"), Broker(str(tmp_path), worker="w-1")
    now = time.time()
    a.mark("proxies", "a", "lccn.loc.gov", now + 100, status=429)
    a.mark("proxies", "b", EVERY_SCOPE, now + 300, status="broken")
    (end,) = b.marks("proxies", "a", "lccn.loc.gov")
    assert now + 95 < end <= now + 101
    assert b.marks("proxies", "a", "www.loc.gov") == []
    assert len(b.marks("proxies", "b", "www.loc.gov")) == 1            # * holds for every host
    survey = b.survey("proxies")
    assert survey["a"].holder is None and survey["a"].marked("lccn.loc.gov") == end
    assert survey["b"].marked("anything") is not None
    age(tmp_path, 200)
    c = Broker(str(tmp_path), worker="w-2")                             # reads the marks after the time passed
    assert c.marks("proxies", "a", "lccn.loc.gov") == []               # expired: deleted by whoever sees it
    assert not list((tmp_path / "proxies" / "a" / "marks").rglob("*.json"))
    assert len(c.marks("proxies", "b", "x")) == 1
    later = Broker(str(tmp_path), worker="w-3", clock=lambda: time.time() + 301)   # or its clock is later
    assert later.marks("proxies", "b", "x") == [] and later.survey("proxies") == {}


def test_workers_are_the_live_heartbeats(tmp_path):
    a, b = Broker(str(tmp_path), worker="w-0"), Broker(str(tmp_path), worker="w-1")
    a.heartbeat()
    b.heartbeat()
    assert a.workers() == ["w-0", "w-1"]
    age(tmp_path, LEASE_TTL + 1)
    a.renew()
    assert b.workers() == ["w-0"] and not (tmp_path / "workers" / "w-1.json").exists()


def test_fair_share(tmp_path):
    brokers = [Broker(str(tmp_path), worker=f"w-{n}") for n in range(3)]
    for b in brokers:
        b.heartbeat()
    assert [brokers[0].fair_share("proxies", n) for n in (0, 1, 2, 10, 12)] == [0, 1, 1, 4, 4]


def test_slots_outlive_processes_and_their_successor_inherits_the_leases(tmp_path):
    """A process claims the lowest free slot of its machine; when it hands over, the next process on that machine
    claims the same slot, is the same worker, and holds (and renews) the leases."""
    first, second = Broker(str(tmp_path), machine="m"), Broker(str(tmp_path), machine="m")
    assert (first.worker, second.worker) == ("m-0", "m-1")
    assert Broker(str(tmp_path), machine="n").worker == "n-0"          # slots per machine
    assert first.claim("proxies", "a") and first.claim("proxies", "b")
    assert (tmp_path / "broker.json").exists()
    first.hand_over()                                                    # the process ends
    assert leases(tmp_path, "slots", "m/0") == [] and len(leases(tmp_path, "proxies", "a")) == 1
    successor = Broker(str(tmp_path), machine="m")
    assert successor.worker == "m-0" and successor.held("proxies") == ["a", "b"]
    age(tmp_path, LEASE_TTL - 10)
    assert successor.renew() == [] and second.renew() == []
    age(tmp_path, 20)
    assert not Broker(str(tmp_path), worker="x-0").claim("proxies", "a")   # renewed by the successor
    assert Broker(str(tmp_path), machine="m").worker == "m-2"          # 0 and 1 are taken


def test_a_crashed_slot_expires(tmp_path):
    crashed = Broker(str(tmp_path), machine="m")
    assert crashed.worker == "m-0" and crashed.claim("proxies", "a")
    age(tmp_path, LEASE_TTL + 1)                                         # no renew, no hand-over
    later = Broker(str(tmp_path), machine="m")
    assert later.worker == "m-0" and later.held("proxies") == []         # its leases expired too
    assert later.claim("proxies", "a")


class Counting(Broker):
    """A broker that counts its listings and its writes of slot leases (its claims of a slot), with storage slow
    enough that claims at once overlap."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.listings, self.slot_claims = 0, 0

    def _list(self, path):
        self.listings += 1
        time.sleep(0.005)
        return super()._list(path)

    def _write(self, path, record):
        if path.startswith("slots/"):
            self.slot_claims += 1
        time.sleep(0.005)
        super()._write(path, record)


def start_together(tmp_path, n: int, index) -> list[Counting]:
    """``n`` brokers of one machine that ask for their worker at once (threads past a barrier); ``index(i)`` is the
    worker index of the i-th."""
    brokers_ = [Counting(str(tmp_path), machine="m", worker_index=index(i)) for i in range(n)]
    barrier = threading.Barrier(n, timeout=30)

    def start(b):
        barrier.wait()
        b.worker

    threads = [threading.Thread(target=start, args=(b,)) for b in brokers_]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return brokers_


def test_brokers_started_together_claim_distinct_slots_in_one_attempt_each(tmp_path):
    """16 processes of one machine start at once, each with its worker index: 16 distinct slots, one claim each and
    four listings (the machine's slots, the heartbeats, the claim's two), however the storage interleaves them."""
    n = 16
    started = start_together(tmp_path / "indexed", n, lambda i: (i, n))
    assert sorted(b.worker for b in started) == sorted(f"m-{i}" for i in range(n))
    assert [b.slot_claims for b in started] == [1] * n and [b.listings for b in started] == [4] * n
    racing = start_together(tmp_path / "all-at-0", n, lambda i: (0, 1))        # every one starting at slot 0
    assert sorted(b.worker for b in racing) == sorted(f"m-{i}" for i in range(n))
    assert sum(b.slot_claims for b in racing) > n                               # claims raced for the same slots


def test_without_a_worker_index_the_search_starts_at_a_random_slot(tmp_path, monkeypatch):
    import random

    monkeypatch.setattr(brokers, "_WORKER_INDEX", [None])
    monkeypatch.setattr(brokers.os, "cpu_count", lambda: 64)
    random.seed(7)
    started = start_together(tmp_path, 8, lambda i: None)
    assert len({b.worker for b in started}) == 8
    assert sum(b.slot_claims for b in started) < 12                             # mostly one claim each


def test_a_successor_takes_a_handed_over_slot_before_a_free_one(tmp_path):
    """Two processes hand over their slots (their heartbeats are live, their leases wait); the next two, started with
    worker indexes 1 and 0, take those slots (one each) and hold their leases."""
    first, second = (Broker(str(tmp_path), machine="m", worker_index=(i, 2)) for i in range(2))
    assert (first.worker, second.worker) == ("m-0", "m-1")
    assert first.claim("proxies", "a") and second.claim("proxies", "b")
    first.hand_over()
    second.hand_over()
    one = Broker(str(tmp_path), machine="m", worker_index=(1, 4))
    zero = Broker(str(tmp_path), machine="m", worker_index=(0, 4))
    assert (one.worker, one.held("proxies")) == ("m-1", ["b"])
    assert (zero.worker, zero.held("proxies")) == ("m-0", ["a"])
    assert Broker(str(tmp_path), machine="m", worker_index=(0, 4)).worker == "m-2"   # then from its start, upward


def test_a_claim_race_lost_is_settled_at_the_renew_without_a_warning(tmp_path):
    """Both claims believed they won (one listed before the other's write had landed): at the renew the later one
    finds the earlier lease, gives the resource up and says so at INFO; a WARNING is only for an expired lease."""
    from loguru import logger

    lines = []
    sink = logger.add(lambda m: lines.append((m.record["level"].name, m.record["message"])), level="DEBUG")
    try:
        later = Broker(str(tmp_path), worker="w-1")
        assert later.claim("proxies", "a")
        earlier = (tmp_path / "proxies" / "a" / "leases" / "20200101T000000000Z-w-0.json")
        earlier.write_text('{"holder": "w-0"}')                                 # w-0's claim, landed late
        assert later.renew() == [("proxies", "a")] and later.held("proxies") == []
        assert leases(tmp_path, "proxies", "a") == [earlier.name]
        assert [lvl for lvl, m in lines if "lost a claim race for proxies/a to w-0; it takes another" in m] == ["INFO"]
        assert not [m for lvl, m in lines if lvl == "WARNING"]
        assert later.claim("proxies", "b")
        age(tmp_path, LEASE_TTL + 1)                                             # no renew within the lease time
        assert later.renew() == [("proxies", "b")]
        assert [lvl for lvl, m in lines if "lease on proxies/b expired" in m] == ["WARNING"]
    finally:
        logger.remove(sink)


def test_survey_kind_names_holders_their_runs_and_the_marks(tmp_path):
    from linecaster.broker import survey_kind

    assert survey_kind(str(tmp_path / "none"), "proxies") == {"resources": {}, "runs": {}}   # no broker yet
    mine, other = Broker(str(tmp_path), machine="m", run="OUT"), Broker(str(tmp_path), machine="n", run="OTHER")
    assert mine.claim("proxies", "a") and other.claim("proxies", "b")
    now = time.time()
    mine.mark("proxies", "c", "example.org", now + 600, status=429)
    survey = survey_kind(str(tmp_path), "proxies")
    assert {rid: r.holder for rid, r in survey["resources"].items()} == {"a": "m-0", "b": "n-0", "c": None}
    assert survey["runs"] == {"m-0": "OUT", "n-0": "OTHER"}
    assert now + 590 < survey["resources"]["c"].marked("example.org") <= now + 601
