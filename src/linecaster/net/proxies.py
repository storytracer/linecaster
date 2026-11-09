"""Proxies shared through the broker (``linecaster.broker``): each proxy of a list has one owner at a time, the worker
that holds its lease, so what holds per proxy (a server's rate limits per IP, its blocks) holds across every worker
that shares the broker, on any executor and machine, and across runs pointed at the same folder.

A worker's ``ProxyPool`` claims its fair share of the proxies not marked blocked for the host it fetches (``ceil(free /
live workers)``, at least one if any is free), and at each renew gives back the ones beyond its share (the ones
blocked for its hosts first), so a worker that joins gets its part within a renew. A block (``block``: a 429, a status
in the host's ``blacklist_on``, an HTML page where another format was expected) is a mark on the proxy for that host
until the end the server asked for; the owner stops using the proxy there and releases it once it is blocked for every
host the worker uses, and whoever claims it later sees the mark. A broken proxy (``broken``: a proxy error, no
connection to it) is marked for every host (scope ``*``) after ``threshold`` failures in a row. ``pick`` chooses the
owned proxy whose turn comes first and reserves its turn: requests through one proxy to one host are spread
``interval`` seconds apart (the host's strictest rate limit), and since nobody else uses the proxy, that holds per IP.

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

#: the broker's kind for proxies
KIND = "proxies"
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


def _redact(proxy: str) -> str:
    from .http import redact

    return redact(proxy)


class ProxyPool:
    """A worker's share of a proxy list, leased through the broker (see the module docstring). Thread-safe:
    ``pick`` and the bookkeeping are in memory; ``fill``, ``rebalance``, ``block`` and ``broken`` read or write the
    broker.

    Args:
        broker: the broker the workers share.
        proxies: the proxy list, as URLs (``linecaster.net.http.read_proxies``).
        clock: monotonic seconds, for the turns (``time.monotonic``).
        fill_seconds: how often ``fill`` lists the broker, at most (None: ``FILL_SECONDS``).
        keep_alive: whether to renew and rebalance in the broker's background thread.
    """

    def __init__(self, broker: Broker, proxies: list[str], clock: Callable[[], float] = time.monotonic,
                 fill_seconds: float | None = None, keep_alive: bool = True):
        self.broker, self.clock, self.fill_seconds = broker, clock, fill_seconds
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
        blocked there, and how many nobody holds that are not blocked there (claimed at the next ``fill``).

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
            free = len(self._free({host}))
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

    def _free(self, hosts: set[str]) -> list[str]:
        """The proxies nobody holds that are not blocked for every one of ``hosts`` (and not broken)."""
        now = self.broker.clock()
        out = []
        for pid in self.proxies:
            r = self._survey.get(pid)
            if pid in self._owned or (r is not None and r.holder is not None):
                continue
            if any(self._ends(pid, h) is None and (r is None or (u := r.marked(h)) is None or u <= now)
                   for h in hosts):
                out.append(pid)
        return out

    def _sharable(self, hosts: set[str]) -> int:
        """The proxies to share among the workers: those not blocked for every one of ``hosts``."""
        now = self.broker.clock()

        def open_for(pid: str, h: str) -> bool:
            r = self._survey.get(pid)
            return self._ends(pid, h) is None and (r is None or (u := r.marked(h)) is None or u <= now)

        return sum(1 for pid in self.proxies if any(open_for(pid, h) for h in hosts))

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
        """Claims proxies usable for ``host`` up to this worker's fair share (at least one when it holds none usable
        there); at most every ``fill_seconds`` unless ``force``. Returns how many it claimed.

        Args:
            host: the host the requests go to.
            force: list the broker even if it did within ``fill_seconds``.
        """
        with self._fill_lock:
            now, wall = self.clock(), self.broker.clock()
            with self._lock:                                  # a block known to have ended since: list at once
                ended = any(self._filled_wall < end <= wall for (_, scope), end in self._blocked.items()
                            if scope in (host, EVERY_SCOPE))
            every = FILL_SECONDS if self.fill_seconds is None else self.fill_seconds
            if not force and not ended and now - self._filled < every:
                return 0
            self._filled, self._filled_wall = now, wall
            self._apply(self.broker.survey(KIND))
            with self._lock:
                self._hosts.add(host)
                sharable = self._sharable({host})
            share = self.broker.fair_share(KIND, sharable)
            with self._lock:
                mine = sum(1 for pid in self._owned if self._usable(pid, host))
                want = max(share - len(self._owned), 0 if mine else 1)
                free = self._order(self._free({host}))
            got = self._claim(free, want) if want and free else 0
            if got:
                logger.debug("worker {worker} claimed {n} proxies for {host}; holds {held}",
                             worker=self.broker.worker, n=got, host=host, held=self.held())
            return got

    def rebalance(self) -> None:
        """After a renew: forgets the proxies whose leases it lost, gives back the ones beyond its fair share (those
        blocked for its hosts first), and claims more up to it."""
        held = set(self.broker.held(KIND))
        self._apply(self.broker.survey(KIND))
        with self._lock:
            self._owned &= held
            hosts = set(self._hosts) or {EVERY_SCOPE}
            sharable = self._sharable(hosts)
        share = self.broker.fair_share(KIND, sharable)
        with self._lock:
            extra = len(self._owned) - share
            give = []
            if extra > 0:
                def rank(pid: str) -> tuple:
                    blocked = sum(1 for h in hosts if not self._usable(pid, h))
                    return (-blocked, pid)
                give = sorted(self._owned, key=rank)[:extra]
                self._owned -= set(give)
            free = self._order(self._free(hosts)) if extra < 0 else []
        for pid in give:
            self.broker.release(KIND, pid)
        if give:
            logger.debug("worker {worker} gave back {n} proxies beyond its share ({share})",
                         worker=self.broker.worker, n=len(give), share=share)
        if free:
            self._claim(free, -extra)

    def block(self, proxy: str, host: str, seconds: float, **data) -> None:
        """Marks ``proxy`` blocked for ``host`` (``*``: every host) for ``seconds``: this worker stops using it there
        at once, and releases it when it is blocked for every host the worker uses.

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


def shared_pool(broker: Broker, proxies: list[str]) -> ProxyPool:
    """Returns this process's pool for ``proxies`` in ``broker``, made at the first use (every fetcher of the process
    with that list shares it, so the worker's leases and turns are one).

    Args:
        broker: the broker (``linecaster.broker.shared``).
        proxies: the proxy list.
    """
    key = (os.getpid(), id(broker), tuple(proxies))
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            pool = _POOLS[key] = ProxyPool(broker, proxies)
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
