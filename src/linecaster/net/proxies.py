"""Proxies shared through the broker (``linecaster.broker``): each proxy of a list has one owner at a time, the worker
that holds its lease, so what holds per proxy (a server's rate limits per IP, its blocks) holds across every worker
that shares the broker, on any executor and machine, and across runs pointed at the same folder.

How many proxies a worker holds is its ``per_worker`` setting (a host's ``proxies_per_worker``,
``linecaster.net.policy``):

- ``"share"`` (the default, ``DEFAULT_PER_WORKER``): **a fair share per worker**, ``ceil(free / live workers)`` of the
  proxies not marked blocked for the host it fetches (at least one if any is free). A worker claims at most
  ``FIRST_FILL`` when it looks for proxies (``fill``) and grows to its share only at the checks of its pool
  (``rebalance``, at most doubling each time), where it also gives back the ones beyond its share (the ones blocked
  for its hosts first), so a worker that joins gets its part within seconds and early workers do not take the proxies
  of those still starting. Few workers then use many proxies, which suits output on object storage, where more
  workers do not make a run faster.
- ``1``: **one proxy per worker**. The worker claims one free proxy usable for the host it fetches and sends every
  request through it. When it is blocked (``block``: a 429, a status in the host's ``blacklist_on``, an HTML page
  where another format was expected) or broken (``broken``: a proxy error, no connection to it, after ``threshold``
  failures in a row), the worker marks it, releases it and claims another free usable one at once; with none free its
  requests pause until a block it knows of ends (or another worker gives one back; it looks every ``FILL_SECONDS``).
  No fair share and no rebalancing: the host's rate limits per proxy are the worker's own. Using every proxy then
  takes as many workers as proxies.
- ``N`` (a whole number above 1): **up to N per worker**, as with ``1``, claimed one by one (one when it has none
  usable, then one more at each check of its pool, ``rebalance``) up to N, never more.

A block is a mark on the proxy for that host until the end the server asked for, a broken proxy one for every host
(scope ``*``); the owner stops using the proxy there and releases it once it is blocked for every host the worker uses,
and whoever claims it later sees the mark. With several hosts, a worker at its count whose proxies are all blocked for
one host swaps one of them for a free proxy usable for every host it uses, if there is one, and otherwise pauses that
host's requests. ``pick`` chooses the owned proxy whose turn comes first and reserves its turn: requests through one
proxy to one host are spread ``interval`` seconds apart (the host's strictest rate limit), and since nobody else uses
the proxy, that holds per IP.

The proxy ids in the broker are hashes of the proxies' hosts and ports (``proxy_id``): no credential reaches the
folder.
"""
from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from collections.abc import Callable

from loguru import logger

from ..broker import EVERY_SCOPE, Broker, Resource, resource_id
from ..errors import PipelineConfigError

#: the broker's kind for proxies
KIND = "proxies"
#: the ``per_worker`` setting of a fair share per worker
SHARE = "share"
#: the ``per_worker`` setting when none is given: a fair share per worker
DEFAULT_PER_WORKER = SHARE
#: the most proxies a worker sharing them (``SHARE``) claims when it looks for proxies; it grows to its fair share at
#: the checks of its pool (``ProxyPool.rebalance``)
FIRST_FILL = 2
#: how often a pool lists the broker for proxies to claim, at most (unless forced)
FILL_SECONDS = 5.0
#: how often a pool in use checks its share (``rebalance``, in a thread of its own), besides after each renew, so a
#: worker that joins gets its part within seconds
REBALANCE_SECONDS = 10.0


def proxy_id(proxy: str) -> str:
    """Returns a proxy's id in the broker: a hash of its host and port, without scheme or credentials.

    Args:
        proxy: the proxy, as a URL (with or without credentials) or ``host:port``.
    """
    address = proxy.split("://", 1)[-1].rsplit("@", 1)[-1].rstrip("/").lower()
    return resource_id(address)


def per_worker_setting(value, where: str = "proxies_per_worker") -> int | str:
    """Returns a ``proxies_per_worker`` setting checked: ``"share"`` or a whole number, at least 1; raises
    ``PipelineConfigError`` for anything else.

    Args:
        value: the setting.
        where: what names it in the error (a policy file and host).
    """
    if value == SHARE or (isinstance(value, int) and not isinstance(value, bool) and value >= 1):
        return value
    raise PipelineConfigError(f"{where}: proxies_per_worker is `share` (a fair share per worker, the default) or a "
                              f"whole number of proxies, at least 1 (1: one proxy per worker), not {value!r}")


def describe_per_worker(value: int | str) -> str:
    """Returns how many proxies a worker holds, in words: ``1 proxy per worker``, ``up to 3 per worker``, ``a fair
    share per worker``.

    Args:
        value: a ``proxies_per_worker`` setting.
    """
    if value == SHARE:
        return "a fair share per worker"
    return "1 proxy per worker" if value == 1 else f"up to {value} per worker"


def _redact(proxy: str) -> str:
    from .http import redact

    return redact(proxy)


class ProxyPool:
    """A worker's part of a proxy list, leased through the broker (see the module docstring). Thread-safe:
    ``pick`` and the bookkeeping are in memory; ``fill``, ``rebalance``, ``block`` and ``broken`` read or write the
    broker.

    Args:
        broker: the broker the workers share.
        proxies: the proxy list, as URLs (``linecaster.net.http.read_proxies``).
        clock: monotonic seconds, for the turns (``time.monotonic``).
        fill_seconds: how often ``fill`` lists the broker, at most (None: ``FILL_SECONDS``).
        keep_alive: whether to renew and rebalance in the broker's background thread.
        per_worker: how many proxies the worker holds: ``"share"`` (``SHARE``, the default: a fair share), 1, or up
            to N; see the module docstring.
    """

    def __init__(self, broker: Broker, proxies: list[str], clock: Callable[[], float] = time.monotonic,
                 fill_seconds: float | None = None, keep_alive: bool = True,
                 per_worker: int | str = DEFAULT_PER_WORKER):
        self.broker, self.clock, self.fill_seconds = broker, clock, fill_seconds
        self.per_worker = per_worker_setting(per_worker)
        self.proxies = {proxy_id(p): p for p in proxies}
        self._lock = threading.Lock()
        self._owned: set[str] = set()
        self._blocked: dict[tuple[str, str], float] = {}      # (proxy id, scope) -> end (broker's clock)
        self._turn: dict[tuple[str, str], float] = {}         # (proxy id, host) -> next free turn (``clock``)
        self._failures: dict[str, int] = {}
        self._hosts: set[str] = set()
        self._survey: dict[str, Resource] = {}
        self._filled, self._filled_wall = -math.inf, -math.inf
        self._fill_lock = threading.Lock()
        self._refill = False                                  # a proxy was given up: the next fill lists at once
        self._rebalanced, self._rebalancing = clock(), False
        held = [pid for pid in broker.held(KIND) if pid in self.proxies]
        if held:
            self._apply(broker.survey(KIND))
            with self._lock:
                self._owned.update(held)
            logger.info("worker {worker} holds {n} proxies again (from its slot's earlier process)",
                        worker=broker.worker, n=len(held))
        if keep_alive:
            broker.keep_alive(self.rebalance)

    # ------------------------------------------------------------------ in memory

    def _ends(self, pid: str, host: str) -> float | None:
        ends = [self._blocked.get((pid, s)) for s in (host, EVERY_SCOPE)]
        ends = [e for e in ends if e is not None and e > self.broker.clock()]
        return max(ends) if ends else None

    def _usable(self, pid: str, host: str) -> bool:
        return self._ends(pid, host) is None

    def usable(self, proxy: str, host: str) -> bool:
        """Returns whether this worker holds ``proxy`` and it is not blocked for ``host``.

        Args:
            proxy: the proxy URL.
            host: the host.
        """
        pid = proxy_id(proxy)
        with self._lock:
            return pid in self._owned and self._usable(pid, host)

    def has_usable(self, host: str) -> bool:
        """Returns whether this worker holds a proxy not blocked for ``host``.

        Args:
            host: the host.
        """
        with self._lock:
            return any(self._usable(pid, host) for pid in self._owned)

    def pick(self, host: str, interval: float) -> tuple[str, float] | None:
        """Returns the owned proxy usable for ``host`` whose turn comes first, with the seconds until its turn, and
        reserves that turn (the proxy's next one at ``host`` is ``interval`` later); None when none is usable.

        Args:
            host: the host the request goes to.
            interval: the seconds between two requests through one proxy to ``host`` (0: none).
        """
        now = self.clock()
        with self._lock:
            self._hosts.add(host)
            usable = [pid for pid in self._owned if self._usable(pid, host)]
            if not usable:
                return None
            pid = min(usable, key=lambda p: (self._turn.get((p, host), -math.inf), p))
            start = max(now, self._turn.get((pid, host), -math.inf))
            self._turn[(pid, host)] = start + interval
            return self.proxies[pid], start - now

    def tick(self) -> None:
        """Checks the share (``rebalance``) in a thread of its own if ``REBALANCE_SECONDS`` have passed since the last
        check; called as requests go out."""
        now = self.clock()
        with self._lock:
            if self._rebalancing or now - self._rebalanced < REBALANCE_SECONDS:
                return
            self._rebalancing, self._rebalanced = True, now

        def run() -> None:
            try:
                self.rebalance()
            except Exception as e:  # noqa: BLE001 - checked again at the next tick
                logger.warning("proxies: share not checked: {error}", error=e)
            finally:
                with self._lock:
                    self._rebalancing = False

        threading.Thread(target=run, name="linecaster-proxies", daemon=True).start()

    def held(self) -> int:
        """Returns how many proxies this worker holds."""
        with self._lock:
            return len(self._owned)

    def counts(self) -> tuple[int, int, int]:
        """Returns (held by this worker, blocked for a host it uses or broken, free: held by nobody and not
        blocked), from what it knows (its last listing of the broker and its own blocks)."""
        now = self.broker.clock()
        with self._lock:
            hosts = self._hosts or {EVERY_SCOPE}

            def blocked(pid: str) -> bool:
                if any(self._ends(pid, h) is not None for h in hosts):
                    return True
                r = self._survey.get(pid)
                return r is not None and any((u := r.marked(h)) is not None and u > now for h in hosts)

            n_blocked = sum(1 for pid in self.proxies if blocked(pid))
            free = sum(1 for pid in self.proxies if pid not in self._owned and not blocked(pid)
                       and (self._survey.get(pid) is None or self._survey[pid].holder is None))
            return len(self._owned), n_blocked, free

    def outlook(self, host: str) -> tuple[float | None, int, int]:
        """Returns what this worker waits for when no proxy it holds is usable for ``host``, from what it knows: the
        seconds until the first block there ends (None: none), how many proxies other workers hold that are not
        blocked there, and how many it could claim at the next ``fill`` (nobody holds them and they are not blocked
        there; with a count per worker at its count, those usable for every host it uses, to swap).

        Args:
            host: the host.
        """
        now = self.broker.clock()
        with self._lock:
            ends, others = [], 0
            for pid in self.proxies:
                r = self._survey.get(pid)
                end = self._ends(pid, host)
                if end is None and r is not None and pid not in self._owned:
                    end = r.marked(host)
                    end = end if end is not None and end > now else None
                if end is not None:
                    ends.append(end - now)
                elif r is not None and r.holder is not None and pid not in self._owned:
                    others += 1
            if self.per_worker == SHARE:
                free = len(self._free({host}))
            else:
                free = len(self._candidates(host)[0]) if not any(self._usable(p, host) for p in self._owned) else 0
            return (min(ends) if ends else None), others, free

    # ------------------------------------------------------------------ through the broker

    def _apply(self, survey: dict[str, Resource]) -> None:
        """Takes the marks of a listing as known blocks."""
        with self._lock:
            self._survey = {pid: r for pid, r in survey.items() if pid in self.proxies}
            for pid, r in self._survey.items():
                for scope, end in r.marks.items():
                    if end > self._blocked.get((pid, scope), -math.inf):
                        self._blocked[(pid, scope)] = end

    def _order(self, pids) -> list[str]:
        """``pids`` in an order of this worker's own, so workers claiming at once try different proxies first."""
        worker = self.broker.worker
        return sorted(pids, key=lambda p: hashlib.sha256(f"{worker}/{p}".encode()).hexdigest())

    def _open(self, pid: str, host: str, now: float) -> bool:
        """Whether ``pid`` is not blocked for ``host`` (nor broken), by this worker's blocks and the last listing."""
        r = self._survey.get(pid)
        return self._ends(pid, host) is None and (r is None or (u := r.marked(host)) is None or u <= now)

    def _free(self, hosts: set[str], every: bool = False) -> list[str]:
        """The proxies nobody holds that are not blocked for one of ``hosts`` (``every``: for any of them), and not
        broken."""
        now = self.broker.clock()
        test = all if every else any
        out = []
        for pid in self.proxies:
            r = self._survey.get(pid)
            if pid in self._owned or (r is not None and r.holder is not None):
                continue
            if test(self._open(pid, h, now) for h in hosts):
                out.append(pid)
        return out

    def _sharable(self, hosts: set[str]) -> int:
        """The proxies to share among the workers: those not blocked for every one of ``hosts``."""
        now = self.broker.clock()
        return sum(1 for pid in self.proxies if any(self._open(pid, h, now) for h in hosts))

    def _candidates(self, host: str) -> tuple[list[str], list[str]]:
        """With a count per worker (not ``SHARE``), what ``fill`` claims for ``host`` when no proxy the worker holds
        is usable there: (the proxies to try, in this worker's order; the owned one to give up for one of them, or
        none). Below its count, the free ones usable for ``host``, those usable for every host it uses first; at its
        count, a swap: the free ones usable for every host it uses, for an owned one blocked at ``host``. Called with
        the lock held."""
        hosts = self._hosts | {host}
        everywhere = self._order(self._free(hosts, every=True))
        if len(self._owned) < self.per_worker:
            first = set(everywhere)
            return everywhere + [p for p in self._order(self._free({host})) if p not in first], []
        blocked = sorted((p for p in self._owned if not self._usable(p, host)),
                         key=lambda p: (-sum(1 for h in hosts if not self._usable(p, h)), p))
        return (everywhere, blocked[:1]) if everywhere and blocked else ([], [])

    def _claim(self, pids: list[str], want: int) -> int:
        got = 0
        for pid in pids:
            if got >= want:
                break
            if self.broker.claim(KIND, pid):
                with self._lock:
                    self._owned.add(pid)
                    self._failures.pop(pid, None)
                got += 1
        return got

    def fill(self, host: str, force: bool = False) -> int:
        """Claims proxies usable for ``host`` (see the module docstring): with a count per worker one when it holds
        none usable there (below its count, or for one of its proxies at its count); sharing them up to
        ``FIRST_FILL`` and its fair share, at least one when it holds none usable there. Lists the broker at most every
        ``fill_seconds``, unless ``force``, a block it knows of has ended since, or it gave a proxy up. Returns how
        many it claimed.

        Args:
            host: the host the requests go to.
            force: list the broker even if it did within ``fill_seconds``.
        """
        with self._fill_lock:
            now, wall = self.clock(), self.broker.clock()
            with self._lock:                                  # a block known to have ended since: list at once
                ended = any(self._filled_wall < end <= wall for (_, scope), end in self._blocked.items()
                            if scope in (host, EVERY_SCOPE))
                refill, self._refill = self._refill, False
            every = FILL_SECONDS if self.fill_seconds is None else self.fill_seconds
            if not force and not ended and not refill and now - self._filled < every:
                return 0
            self._filled, self._filled_wall = now, wall
            self._apply(self.broker.survey(KIND))
            with self._lock:
                self._hosts.add(host)
                mine = sum(1 for pid in self._owned if self._usable(pid, host))
            if self.per_worker == SHARE:
                with self._lock:
                    sharable = self._sharable({host})
                share = self.broker.fair_share(KIND, sharable)
                with self._lock:
                    want = max(min(share, FIRST_FILL) - len(self._owned), 0 if mine else 1)
                    free = self._order(self._free({host}))
                got = self._claim(free, want) if want and free else 0
                give = []
            else:
                if mine:
                    return 0
                with self._lock:
                    free, give = self._candidates(host)
                got = self._claim(free, 1) if free else 0
            if got and give:                                   # swapped: the one blocked here goes back
                with self._lock:
                    self._owned.discard(give[0])
                self.broker.release(KIND, give[0])
            if got:
                logger.debug("worker {worker} claimed {n} proxies for {host}; holds {held}",
                             worker=self.broker.worker, n=got, host=host, held=self.held())
            return got

    def rebalance(self) -> None:
        """After a renew and every ``REBALANCE_SECONDS`` in use: forgets the proxies whose leases it lost; with a count
        per worker gives back the ones beyond it (blocked for its hosts first; e.g. inherited from its slot's earlier
        process) and claims one more while below it (a lost one replaced at once); sharing them gives back the ones
        beyond its fair share (those blocked for its hosts first) and claims more toward it, at most doubling."""
        held = set(self.broker.held(KIND))
        self._apply(self.broker.survey(KIND))
        with self._lock:
            self._owned &= held
            hosts = set(self._hosts) or {EVERY_SCOPE}
            sharable = self._sharable(hosts)
        if self.per_worker == SHARE:
            target = self.broker.fair_share(KIND, sharable)
        else:
            target = self.per_worker
        with self._lock:
            extra = len(self._owned) - target
            give = []
            if extra > 0:
                def rank(pid: str) -> tuple:
                    blocked = sum(1 for h in hosts if not self._usable(pid, h))
                    return (-blocked, pid)
                give = sorted(self._owned, key=rank)[:extra]
                self._owned -= set(give)
            free, want = [], 0
            if extra < 0 and self._hosts:
                if self.per_worker == SHARE:
                    free, want = self._order(self._free(hosts)), min(-extra, max(FIRST_FILL, len(self._owned)))
                else:
                    every = self._order(self._free(hosts, every=True))
                    first = set(every)
                    free, want = every + [p for p in self._order(self._free(hosts)) if p not in first], 1
        for pid in give:
            self.broker.release(KIND, pid)
        if give:
            logger.debug("worker {worker} gave back {n} proxies beyond its {what} ({target})",
                         worker=self.broker.worker, n=len(give), target=target,
                         what="share" if self.per_worker == SHARE else "count")
        if free:
            self._claim(free, want)

    def block(self, proxy: str, host: str, seconds: float, **data) -> None:
        """Marks ``proxy`` blocked for ``host`` (``*``: every host) for ``seconds``: this worker stops using it there
        at once, and releases it when it is blocked for every host the worker uses (its next ``fill`` then claims
        another at once).

        Args:
            proxy: the proxy URL.
            host: the host that turned it away, or ``*``.
            seconds: how long the block lasts.
            **data: what the mark records (the status).
        """
        pid = proxy_id(proxy)
        until = self.broker.clock() + seconds
        with self._lock:
            self._blocked[(pid, host)] = max(until, self._blocked.get((pid, host), -math.inf))
            hosts = self._hosts | ({host} if host != EVERY_SCOPE else set())
            everywhere = all(not self._usable(pid, h) for h in hosts)
            owned = pid in self._owned
            if everywhere:
                self._owned.discard(pid)
                self._refill = self._refill or owned
            usable = sum(1 for p in self._owned if self._usable(p, host))
            total = len(self._owned)
        try:
            self.broker.mark(KIND, pid, host, until, **data)
        except Exception as e:  # noqa: BLE001 - the block holds in this worker; its lease is released below
            logger.warning("proxy {proxy}: block not marked in the broker {path}: {error}", proxy=_redact(proxy),
                           path=self.broker.path, error=e)
        if everywhere and owned:
            self.broker.release(KIND, pid)
        log = logger.warning if usable == 0 else logger.info
        log("proxy {proxy} blocked {where} for {seconds}; {usable} of the {held} held usable there",
            proxy=_redact(proxy), where="everywhere" if host == EVERY_SCOPE else f"at {host}",
            seconds=f"{seconds:.0f} s", usable=usable, held=total)

    def broken(self, proxy: str, threshold: int, seconds: float) -> None:
        """Counts a failure of ``proxy`` itself (a proxy error, no connection); after ``threshold`` in a row it is
        marked for every host (``*``) for ``seconds``.

        Args:
            proxy: the proxy URL.
            threshold: failures in a row that leave it out.
            seconds: how long it is left out then.
        """
        pid = proxy_id(proxy)
        with self._lock:
            self._failures[pid] = self._failures.get(pid, 0) + 1
            out = self._failures[pid] >= threshold
            if out:
                self._failures.pop(pid)
        if out:
            self.block(proxy, EVERY_SCOPE, seconds, status="broken")

    def answered(self, proxy: str) -> None:
        """Notes that ``proxy`` carried an answer: its failures in a row start again.

        Args:
            proxy: the proxy URL.
        """
        with self._lock:
            self._failures.pop(proxy_id(proxy), None)


_POOLS: dict[tuple, ProxyPool] = {}
_POOLS_LOCK = threading.Lock()


def shared_pool(broker: Broker, proxies: list[str], per_worker: int | str = DEFAULT_PER_WORKER) -> ProxyPool:
    """Returns this process's pool for ``proxies`` in ``broker``, made at the first use (every fetcher of the process
    with that list shares it, so the worker's leases and turns are one). Fetchers that share a list must agree on
    ``per_worker``: ``PipelineConfigError`` otherwise.

    Args:
        broker: the broker (``linecaster.broker.shared``).
        proxies: the proxy list.
        per_worker: how many proxies the worker holds (``ProxyPool``; default a fair share).
    """
    key = (os.getpid(), id(broker), tuple(proxies))
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            pool = _POOLS[key] = ProxyPool(broker, proxies, per_worker=per_worker)
        elif pool.per_worker != per_worker_setting(per_worker):
            raise PipelineConfigError(f"one proxy list with proxies_per_worker {pool.per_worker!r} and "
                                      f"{per_worker!r}: the hosts that share a list share its setting")
        return pool


def pools() -> list[ProxyPool]:
    """Returns this process's shared pools."""
    with _POOLS_LOCK:
        return [p for (pid, _, _), p in _POOLS.items() if pid == os.getpid()]


def close_pools() -> None:
    """Forgets this process's shared pools and hands over its brokers' slots (``linecaster.broker.hand_over_shared``):
    the leases stay with the worker for the slot's next process."""
    from ..broker import hand_over_shared

    with _POOLS_LOCK:
        _POOLS.clear()
    hand_over_shared()
