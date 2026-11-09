"""The broker: a shared folder (any datatrove ``DataFolder``: local, S3, ...) through which workers across tasks, runs
and machines agree on who uses which shared resource and what is unavailable until when. No server, no lock service:
only files, their names and the modification times the storage reports. See ``docs/reference/broker.md``.

Layout (versioned and neutral, so a new kind of resource needs no change of the protocol)::

    <broker>/
      broker.json                          {"format": "linecaster.broker/1", "created": ...}
      workers/<worker>.json                heartbeat: machine, slot, run, started, renewed
      slots/<machine>/<n>/leases/...       the worker slots of a machine (a kind like any other)
      <kind>/<resource id>/
        leases/<claimed>-<worker>.json     who holds it (since when: the claim's time, in the name)
        marks/<scope>/<until>-<n>.json     what holds for it until when (e.g. a block at one host)

A **lease** says that one worker holds a resource. It is valid while its file was rewritten (``renew``) within
``LEASE_TTL`` seconds, by the modification time the storage lists, so a crashed worker's leases expire on their own and
the writers' clocks do not matter. A claim (``claim``) lists the resource's leases, writes its own if none is valid,
lists again, and the earliest valid lease wins (by the claim time in its name, then the worker); the losers delete
theirs. There is no exclusive create: two claims at once are told apart by listing. A holder that finds at a renew that
its own lease is gone or older than ``LEASE_TTL`` (it went that long without a renew) gives the resource up: the lease
expired. One that finds an earlier valid lease than its own (two claims at once both believed they won, when one
listed before the other's write had landed) gives it up too: it lost the claim race, and takes another.

A **mark** says that something holds for a resource in a scope (a host, or ``*`` for every scope) until a time: it
lasts ``ttl`` seconds from its file's modification time. Marks are written once and never changed; whoever sees one
expired deletes it.

The **worker identity** is a datatrove worker slot, not a process: on Ray every task is a new process, and leases tied
to processes would change hands with every task. At its first use a process claims a free slot of its machine
(``slots/<machine>/<n>``, a lease held by the process) and is the worker ``<machine>-<n>`` from then on; a later
process on the same machine that claims the same slot once it is free is the same worker again, and holds (and renews)
that worker's leases, which are named after the worker. A process that ends hands its slot over (``hand_over``) and
leaves its other leases to the slot's next process; leases nobody renews expire after ``LEASE_TTL``. The search for a
slot starts at a place of the process's own, so processes started together do not race for the same slots: the
executor's worker index k (``set_worker_index``; linecaster's executors set it), else a random one. It takes a
handed-over slot first (a live heartbeat, no slot lease: its leases wait for a successor), then the k-th free slot
(free: no valid slot lease claimed more than ``SLOT_PEERS_SECONDS`` ago, so the slots its peers claim meanwhile still
count), so a relaunch while a stopped run's slot leases are still valid does not race through them, then probes
upward, past every valid lease.

The folder as a whole (``linecaster broker``): ``survey_all`` says what it holds, ``survey_kind`` which resources of a
kind are held by whom and marked, ``clean`` removes what has expired (or, after a hard kill, every lease), ``purge``
resets it.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import random
import re
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger

from .errors import LinecasterError

#: the broker's format, in ``broker.json``
FORMAT = "linecaster.broker/1"
#: a lease (and a heartbeat) is valid this long after it was last written
LEASE_TTL = 180.0
#: how often ``keep_alive`` renews the leases and the heartbeat
RENEW_SECONDS = 60.0
#: the kind of the worker slots
SLOTS = "slots"
#: slot leases claimed within this many seconds before a process looks for a slot are its peers' (processes started
#: with it); older valid ones belong to a run before it (one stopped moments ago), whose slots its search skips
SLOT_PEERS_SECONDS = 60.0
#: the scope of a mark that holds in every scope
EVERY_SCOPE = "*"
_STAMP = len("20261109T101500123Z")
#: this process's worker index among the processes an executor runs at once, and how many those are
#: (``set_worker_index``)
_WORKER_INDEX: list[tuple[int, int] | None] = [None]


def set_worker_index(index: int, workers: int) -> None:
    """Tells this process's brokers which of the ``workers`` processes an executor runs at once it is (``index``, from
    0), so its search for a worker slot starts at a slot of its own (``Broker.worker``). Called by linecaster's
    executors before a task runs; a process that has its slot keeps it.

    Args:
        index: this process's worker index: datatrove's local rank (a local run's pool), the task's index among
            those running at once (Ray, a multi-GPU Job).
        workers: how many processes run at once on this machine at most.
    """
    _WORKER_INDEX[0] = (max(0, int(index)), max(1, int(workers)))


def _stamp(t: float) -> str:
    """``t`` (seconds since the epoch) as a name part: ``20261109T101500123Z``, sortable."""
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime(t)) + f"{int(t % 1 * 1000):03d}Z"


def _safe(text: str) -> str:
    """``text`` as one part of a file name: letters, digits, ``.``, ``_`` and ``-``."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", text) or "_"


def modified(info: dict) -> float | None:
    """Returns a listing entry's modification time (seconds since the epoch) as the storage reports it, or None.

    Args:
        info: one entry of an fsspec listing with ``detail=True``.
    """
    for key in ("LastModified", "mtime", "last_modified", "updated", "created"):
        value = info.get(key)
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def machine_name() -> str:
    """Returns this machine's name as the broker uses it: the host name's first label, safe for a file name."""
    return _safe(socket.gethostname().split(".")[0].lower())


@dataclass(frozen=True)
class Entry:
    """One file of the broker's folder, as its path (relative to the folder) names it: ``category`` is ``format``
    (``broker.json``), ``heartbeat`` (``workers/<worker>.json``; ``rid`` is the worker), ``lease``
    (``<kind>/<id>/leases/<name>``; the slots are kind ``slots``, id ``<machine>/<n>``), ``mark``
    (``<kind>/<id>/marks/<scope>/<name>``) or ``other`` (not the broker's)."""

    path: str
    category: str
    kind: str = ""
    rid: str = ""
    scope: str = ""
    name: str = ""

    @property
    def lease(self) -> tuple[str, str] | None:
        """A lease's (claimed, holder) from its name, or None for a name that is not a lease's."""
        if self.category != "lease" or not self.name.endswith(".json") or len(self.name) < _STAMP + 6:
            return None
        return self.name[:_STAMP], self.name[_STAMP + 1:-5]


def parse_path(path: str) -> Entry:
    """Returns what a file of the broker's folder is, from its path (``Entry``).

    Args:
        path: the file's path relative to the broker's folder, as a listing of it shows it.
    """
    if path == "broker.json":
        return Entry(path, "format")
    head, _, rest = path.partition("/")
    if head == "workers" and rest.endswith(".json") and "/" not in rest:
        return Entry(path, "heartbeat", rid=rest[:-5], name=rest)
    for part in ("/leases/", "/marks/"):
        rid, sep, tail = rest.partition(part)
        if not sep or not rid:
            continue
        if part == "/leases/" and tail and "/" not in tail:
            return Entry(path, "lease", head, rid, name=tail)
        scope, _, name = tail.partition("/")
        if part == "/marks/" and scope and name and "/" not in name:
            return Entry(path, "mark", head, rid, scope, name)
    return Entry(path, "other")


@dataclass
class Resource:
    """One resource as a listing of its kind shows it (``Broker.survey``): its holder (the worker of the winning
    valid lease, or None), and its live marks per scope (the latest end, on the broker's clock)."""

    holder: str | None = None
    marks: dict[str, float] = field(default_factory=dict)

    def marked(self, scope: str) -> float | None:
        """The end of the latest live mark for ``scope`` or for every scope, or None."""
        ends = [u for s, u in self.marks.items() if s in (_safe(scope), EVERY_SCOPE)]
        return max(ends) if ends else None


class Broker:
    """Coordinates shared resources between workers through a folder: leases (who holds what), marks (what is
    unavailable until when) and the workers' heartbeats. Thread-safe; one per process and folder (``shared``).

    Args:
        folder: the broker's folder, any fsspec path (or a datatrove ``DataFolder``).
        worker: this worker's identity; None (the default) claims a free slot of this machine at the first use
            (``worker``).
        clock: the time now, seconds since the epoch (``time.time``); compared with the storage's modification times
            and written into names.
        machine: this machine's name (default ``machine_name()``).
        run: what the heartbeat names as the worker's run (e.g. the output folder); informational.
        lease_ttl: how long a lease and a heartbeat stay valid without a renew (``LEASE_TTL``).
        renew_seconds: how often ``keep_alive`` renews (``RENEW_SECONDS``).
        worker_index: (index, workers) where this process's search for a slot starts (``set_worker_index``); None:
            the one set for the process, else a random start.
    """

    _instances = itertools.count()

    def __init__(self, folder, worker: str | None = None, clock: Callable[[], float] = time.time,
                 machine: str | None = None, run: str | None = None, lease_ttl: float = LEASE_TTL,
                 renew_seconds: float = RENEW_SECONDS, worker_index: tuple[int, int] | None = None):
        from datatrove.io import get_datafolder

        self.folder = get_datafolder(folder)
        self.path = folder if isinstance(folder, str) else self.folder.path
        self.clock, self.lease_ttl, self.renew_seconds = clock, lease_ttl, renew_seconds
        self.machine = _safe(machine) if machine else machine_name()
        self.run = run
        self._worker = _safe(worker) if worker else None
        self._worker_index = worker_index
        self._slot: tuple[str, str] | None = None             # (slot id, lease name) held by this process
        self._token = f"{self.machine}.p{os.getpid()}.{next(self._instances)}"   # the process, for its slot lease
        self._lock = threading.RLock()
        self._held: dict[tuple[str, str], str] = {}           # (kind, id) -> lease file name
        self._adopted: set[str] = set()                       # kinds whose inherited leases were looked for
        self._marks: dict[str, tuple[str, float]] = {}        # mark path -> (scope, end on the storage's clock)
        self._count = itertools.count()
        self._started = clock()
        self._listeners: list[Callable[[], None]] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ files

    def _write(self, path: str, record: dict) -> None:
        with self.folder.open(path, "w") as f:
            json.dump(record, f)

    def _list(self, path: str) -> dict[str, dict]:
        try:
            return self.folder.find(path, detail=True) or {}
        except FileNotFoundError:
            return {}

    def _rm(self, path: str) -> None:
        try:
            self.folder.rm(path)
        except (FileNotFoundError, OSError):
            pass                                              # deleted by another worker meanwhile

    def _age(self, info: dict) -> float:
        when = modified(info)
        return 0.0 if when is None else self.clock() - when

    def _init_folder(self) -> None:
        if not self.folder.exists("broker.json"):
            self._write("broker.json", {"format": FORMAT, "created": self.clock()})

    # ------------------------------------------------------------------ the worker

    @property
    def worker(self) -> str:
        """This worker's identity: the one given, or ``<machine>-<n>`` of the slot this process claims at the first
        use (``_claim_slot``)."""
        with self._lock:
            if self._worker is None:
                self._init_folder()
                self._claim_slot()
                self.heartbeat()
            return self._worker

    def _claim_slot(self) -> None:
        """Claims a free slot of this machine, from one listing of its slots and one of the heartbeats: a handed-over
        slot first (its worker's heartbeat is live and no process holds the slot, so its leases wait for a successor),
        then the k-th free slot, k this process's start (``_slot_order``), and upward from there, skipping every slot
        with a valid lease. Free counts the slots not held since before this launch (no valid lease claimed more than
        ``SLOT_PEERS_SECONDS`` ago): the slots of a run stopped moments ago are skipped in the count, those its peers
        claimed meanwhile are not, so processes started together, all at once or one after the other, take different
        slots and their claims do not race."""
        taken, earlier, orphans = set(), set(), []
        launch = _stamp(self.clock() - SLOT_PEERS_SECONDS)
        for path, info in self._list(f"{SLOTS}/{self.machine}").items():
            e = parse_path(path)
            n = e.rid.rpartition("/")[2]
            if e.category == "lease" and n.isdigit() and self._age(info) < self.lease_ttl:
                taken.add(int(n))
                if e.lease is not None and e.lease[0] < launch:     # held since before this launch
                    earlier.add(int(n))
        prefix = f"{self.machine}-"
        for path, info in self._list("workers").items():
            e = parse_path(path)
            n = e.rid[len(prefix):] if e.category == "heartbeat" and e.rid.startswith(prefix) else ""
            if n.isdigit() and int(n) not in taken and self._age(info) < self.lease_ttl:
                orphans.append(int(n))
        tried = set()
        for n in self._slot_order(earlier, sorted(orphans)):
            if n in taken or n in tried:
                continue
            tried.add(n)
            name = self._claim(SLOTS, f"{self.machine}/{n}", self._token)
            if name is not None:
                self._slot = (f"{self.machine}/{n}", name)
                self._worker = f"{self.machine}-{n}"
                logger.debug("broker {path}: this process is worker {worker} ({tries} claim(s))", path=self.path,
                             worker=self._worker, tries=len(tried))
                return

    def _slot_order(self, held: set[int], orphans: list[int]):
        """The slots to try, in order: the handed-over ones (``orphans``) from this process's place among them, then
        the free slots (those not in ``held``) from the k-th on, k this process's start, up to those its peers likely
        take, then the free ones below the k-th, then upward without end. Processes started together take distinct
        slots at the first claim, also where the leases of a run stopped moments ago are still valid. The start is its
        worker index (``set_worker_index``), else random among one free slot per CPU."""
        index = self._worker_index or _WORKER_INDEX[0]
        if index is None:
            size = max(1, os.cpu_count() or 1)
            start = random.randrange(size)
        else:
            start, workers = index
            size = max(workers, start + 1)
        if orphans:
            k = start % len(orphans)
            yield from orphans[k:] + orphans[:k]
        free = list(itertools.islice((n for n in itertools.count() if n not in held), size))
        yield from free[start:]
        yield from free[:start]
        yield from itertools.count(free[-1] + 1)

    def heartbeat(self) -> None:
        """Writes this worker's heartbeat (``workers/<worker>.json``: machine, slot, run, started, renewed)."""
        worker = self.worker
        slot = self._slot[0].rpartition("/")[2] if self._slot else None
        self._write(f"workers/{worker}.json", {"worker": worker, "machine": self.machine, "slot": slot,
                                               "run": self.run, "started": self._started, "renewed": self.clock()})

    def workers(self) -> list[str]:
        """Returns the live workers (a heartbeat within the lease time), this one among them; deletes the heartbeats
        of the others."""
        live = []
        for path, info in self._list("workers").items():
            e = parse_path(path)
            if e.category != "heartbeat":
                continue
            if self._age(info) < self.lease_ttl:
                live.append(e.rid)
            else:
                self._rm(path)
        return sorted(live)

    # ------------------------------------------------------------------ leases

    def _lease_name(self, holder: str) -> str:
        return f"{_stamp(self.clock())}-{holder}.json"

    def _leases(self, listing: dict[str, dict], prefix: str,
                own: str | None = None) -> tuple[list[tuple[str, str, str]], list[str]]:
        """The leases under ``prefix`` (a resource's ``leases/``): the valid ones as (claimed, holder, name), earliest
        first, and the paths of the expired ones; ``own`` (a name) counts as valid whatever its age (it was just
        written). Deletes nothing."""
        valid, expired = [], []
        for path, info in listing.items():
            parts = parse_path(path).lease if path.startswith(prefix) else None
            if parts is None:
                continue
            name = path[len(prefix):]
            if name != own and self._age(info) >= self.lease_ttl:
                expired.append(path)
                continue
            valid.append((*parts, name))
        return sorted(valid), expired

    def _valid(self, listing: dict[str, dict], prefix: str, own: str | None = None) -> list[tuple[str, str, str]]:
        """The valid leases under ``prefix`` as ``_leases`` finds them; the expired ones are deleted."""
        valid, expired = self._leases(listing, prefix, own)
        for path in expired:
            self._rm(path)
        return valid

    def _claim(self, kind: str, rid: str, holder: str) -> str | None:
        """Claims ``kind``/``rid`` for ``holder``: the lease's name if it won, else None."""
        prefix = f"{kind}/{rid}/leases/"
        if any(h != holder for _, h, _ in self._valid(self._list(prefix), prefix)):
            return None
        name = self._lease_name(holder)
        self._write(prefix + name, {"holder": holder, "claimed": self.clock()})
        valid = self._valid(self._list(prefix), prefix, own=name)
        winner = valid[0] if valid else None
        if winner is not None and winner[2] == name:
            for _, h, other in valid[1:]:
                if h == holder:                               # an older lease of the same holder: replaced
                    self._rm(prefix + other)
            return name
        self._rm(prefix + name)
        return None

    def claim(self, kind: str, rid: str) -> bool:
        """Claims a resource for this worker: True if it holds it now (also when it held it already).

        Args:
            kind: the kind of resource (``proxies``), a folder name.
            rid: the resource's id within its kind.
        """
        worker = self.worker
        with self._lock:
            self._adopt(kind)
            if (kind, rid) in self._held:
                return True
            name = self._claim(kind, rid, worker)
            if name is not None:
                self._held[(kind, rid)] = name
            return name is not None

    def release(self, kind: str, rid: str) -> None:
        """Releases a resource this worker holds (deletes its lease); nothing if it holds none.

        Args:
            kind: the kind of resource.
            rid: the resource's id.
        """
        with self._lock:
            name = self._held.pop((kind, rid), None)
        if name is not None:
            self._rm(f"{kind}/{rid}/leases/{name}")

    def held(self, kind: str) -> list[str]:
        """Returns the ids of the resources of ``kind`` this worker holds, those it inherited from its slot's earlier
        process among them.

        Args:
            kind: the kind of resource.
        """
        self.worker
        with self._lock:
            self._adopt(kind)
            return sorted(rid for k, rid in self._held if k == kind)

    def _adopt(self, kind: str, listing: dict[str, dict] | None = None) -> None:
        """The first time ``kind`` is used: the valid leases this worker (an earlier process in its slot) holds."""
        if kind in self._adopted or kind == SLOTS:
            return
        self._adopted.add(kind)
        listing = self._list(kind) if listing is None else listing
        mine = f"-{self._worker}.json"
        for path in listing:
            e = parse_path(path)
            rid, name = e.rid, e.name
            if e.category != "lease" or e.kind != kind or not name.endswith(mine) or (kind, rid) in self._held:
                continue
            prefix = f"{kind}/{rid}/leases/"
            valid = self._valid({p: i for p, i in listing.items() if p.startswith(prefix)}, prefix)
            if valid and valid[0][2] == name:
                self._held[(kind, rid)] = name
                logger.debug("broker {path}: worker {worker} holds {kind}/{rid} again", path=self.path,
                             worker=self._worker, kind=kind, rid=rid)

    def renew(self) -> list[tuple[str, str]]:
        """Renews this process's slot, every lease this worker holds and its heartbeat. Gives up a resource whose
        lease expired (its file is gone, deleted as expired by another worker, or older than the lease time: a
        WARNING) or whose earliest valid lease is another worker's (a claim race lost: two claims at once both
        believed they won; an INFO). Returns the (kind, id) given up."""
        self.worker
        with self._lock:
            held = dict(self._held)
            slot = self._slot
        if slot is not None:
            self._write(f"{SLOTS}/{slot[0]}/leases/{slot[1]}", {"holder": self._token, "renewed": self.clock()})
        expired, raced = [], []
        for kind in sorted({k for k, _ in held}):
            listing = self._list(kind)
            for (k, rid), name in held.items():
                if k != kind:
                    continue
                path = f"{kind}/{rid}/leases/{name}"
                info = listing.get(path)
                if info is None or self._age(info) >= self.lease_ttl:
                    expired.append((kind, rid))
                    continue
                self._write(path, {"holder": self._worker, "renewed": self.clock()})
                prefix = f"{kind}/{rid}/leases/"
                valid = self._valid({p: i for p, i in listing.items() if p.startswith(prefix)}, prefix, own=name)
                if valid and valid[0][2] != name:
                    raced.append((kind, rid, valid[0][1]))
        self.heartbeat()
        for kind, rid in expired:
            logger.warning("broker {path}: worker {worker}'s lease on {kind}/{rid} expired (no renew within the lease "
                           "time); it gives it up", path=self.path, kind=kind, rid=rid, worker=self._worker)
            self.release(kind, rid)
        for kind, rid, winner in raced:
            logger.info("broker {path}: worker {worker} lost a claim race for {kind}/{rid} to {winner}; it takes "
                        "another", path=self.path, kind=kind, rid=rid, worker=self._worker, winner=winner)
            self.release(kind, rid)
        return expired + [(kind, rid) for kind, rid, _ in raced]

    # ------------------------------------------------------------------ marks

    def mark(self, kind: str, rid: str, scope: str, until: float, **data) -> str:
        """Marks a resource for a scope until a time; returns the mark's path. The mark lasts ``until - now`` seconds
        from its file's modification time.

        Args:
            kind: the kind of resource.
            rid: the resource's id.
            scope: what the mark holds for (a host), or ``*`` (``EVERY_SCOPE``) for everything.
            until: the end, seconds since the epoch on the broker's clock.
            **data: what else the mark records (JSON values: a status, ...).
        """
        now = self.clock()
        path = f"{kind}/{rid}/marks/{_safe(scope) if scope != EVERY_SCOPE else scope}/" \
               f"{_stamp(until)}-{self.worker}.{next(self._count)}.json"
        self._write(path, {"ttl": round(until - now, 3), "until": until, "worker": self._worker, **data})
        with self._lock:
            self._marks[path] = (scope, until)
        return path

    def _mark_end(self, path: str, info: dict) -> float | None:
        with self._lock:
            known = self._marks.get(path)
        if known is not None:
            return known[1]
        try:
            with self.folder.open(path) as f:
                record = json.load(f)
            ttl = float(record["ttl"])
        except FileNotFoundError:
            return None                                       # expired and deleted by another worker meanwhile
        except (ValueError, KeyError, TypeError) as e:
            logger.debug("broker mark {path} unreadable (being written?), skipped: {error}", path=path, error=e)
            return None
        start = modified(info)
        end = (start + ttl) if start is not None else float(record.get("until") or 0.0)
        with self._lock:
            self._marks[path] = ("", end)
        return end

    def marks(self, kind: str, rid: str, scope: str) -> list[float]:
        """Returns the ends (seconds since the epoch, broker's clock) of a resource's live marks for ``scope``, those
        for every scope (``*``) among them; deletes the expired ones.

        Args:
            kind: the kind of resource.
            rid: the resource's id.
            scope: the scope (a host).
        """
        ends = []
        for s in {_safe(scope), EVERY_SCOPE}:
            prefix = f"{kind}/{rid}/marks/{s}/"
            ends += self._live_marks(self._list(prefix), prefix)
        return sorted(ends)

    def _live_marks(self, listing: dict[str, dict], prefix: str) -> list[float]:
        now, out = self.clock(), []
        for path, info in listing.items():
            if not path.startswith(prefix) or not path.endswith(".json"):
                continue
            end = self._mark_end(path, info)
            if end is None:
                continue
            if end <= now:
                self._rm(path)
                with self._lock:
                    self._marks.pop(path, None)
            else:
                out.append(end)
        return out

    def survey(self, kind: str) -> dict[str, Resource]:
        """Returns every resource of ``kind`` that has a valid lease or a live mark, from one listing of the kind:
        id -> ``Resource`` (its holder, its marks per scope). Expired leases and marks are deleted.

        Args:
            kind: the kind of resource.
        """
        self.worker
        listing = self._list(kind)
        with self._lock:
            self._adopt(kind, listing)
            own = {rid: name for (k, rid), name in self._held.items() if k == kind}
        out: dict[str, Resource] = {}
        groups: dict[tuple[str, str, str], dict[str, dict]] = {}
        for path, info in listing.items():
            e = parse_path(path)
            if e.kind == kind and e.category in ("lease", "mark"):
                part = "/leases/" if e.category == "lease" else "/marks/"
                groups.setdefault((e.rid, part, e.scope), {})[path] = info
        for (rid, part, scope), entries in groups.items():
            prefix = f"{kind}/{rid}{part}" + (f"{scope}/" if scope else "")
            if part == "/leases/":
                valid = self._valid(entries, prefix, own=own.get(rid))
                if valid:
                    out.setdefault(rid, Resource()).holder = valid[0][1]
            else:
                ends = self._live_marks(entries, prefix)
                if ends:
                    out.setdefault(rid, Resource()).marks[scope] = max(ends)
        return out

    def fair_share(self, kind: str, free: int) -> int:
        """Returns how many of ``free`` resources one worker should hold: ``ceil(free / live workers)``, at least 1
        when any is free.

        Args:
            kind: the kind of resource (for the record; every kind is shared by the same workers).
            free: the resources there are to share (e.g. the proxies not blocked).
        """
        if free <= 0:
            return 0
        return max(1, math.ceil(free / max(1, len(self.workers()))))

    # ------------------------------------------------------------------ lifetime

    def keep_alive(self, on_renew: Callable[[], None] | None = None) -> None:
        """Renews every ``renew_seconds`` in a background thread (started once), calling ``on_renew`` after each
        renew.

        Args:
            on_renew: called after each renew (in the thread), e.g. to rebalance; exceptions are logged.
        """
        with self._lock:
            if on_renew is not None and on_renew not in self._listeners:
                self._listeners.append(on_renew)
            if self._thread is not None or not self.renew_seconds:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._renewing, name="linecaster-broker", daemon=True)
            self._thread.start()

    def _renewing(self) -> None:
        while not self._stop.wait(self.renew_seconds):
            try:
                self.renew()
            except Exception as e:  # noqa: BLE001 - tried again at the next renew, within the lease time
                logger.warning("broker {path}: renew failed: {error}", path=self.path, error=e)
            for listener in list(self._listeners):
                try:
                    listener()
                except Exception as e:  # noqa: BLE001 - a listener's failure does not stop the renewing
                    logger.warning("broker {path}: after renew: {error}", path=self.path, error=e)

    def hand_over(self) -> None:
        """Ends this process's part: stops renewing and releases its slot, leaving this worker's other leases to the
        slot's next process (they expire after the lease time if none comes)."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._lock:
            slot, self._slot = self._slot, None
            if slot is not None:
                self._rm(f"{SLOTS}/{slot[0]}/leases/{slot[1]}")
                self._worker = None
                self._held.clear()
                self._adopted.clear()

    def close(self) -> None:
        """Ends this worker: releases every lease it holds and its slot, and deletes its heartbeat."""
        with self._lock:
            held = list(self._held)
            worker = self._worker
        for kind, rid in held:
            self.release(kind, rid)
        if worker is not None:
            self._rm(f"workers/{worker}.json")
        self.hand_over()


# ---------------------------------------------------------------------- the folder as a whole (``linecaster broker``)

#: the categories ``clean`` removes, in the order it reports them
CLEANED = ("heartbeats", "slots", "leases", "marks")


def _inspector(folder, now: float | None, lease_ttl: float) -> Broker:
    """A broker that only reads and deletes: an explicit worker (it claims no slot, writes no heartbeat) and a clock
    fixed at ``now`` if given."""
    clock = time.time if now is None else (lambda: now)
    return Broker(folder, worker="inspector", clock=clock, lease_ttl=lease_ttl)


def _scan(b: Broker) -> list[dict]:
    """Every file of the broker's folder from one listing, with what it is and whether it is live: per file the
    ``Entry`` (``entry``), its ``age`` (seconds since its last write, by the storage's modification time), ``live``
    (a heartbeat or lease written within the lease time, a mark not expired; None for a mark whose end could not be
    read) and, for a mark, its ``end``."""
    out = []
    for path, info in sorted(b._list("").items()):
        e = parse_path(path)
        if e.category == "lease" and e.lease is None:
            e = Entry(path, "other")
        age = b._age(info)
        row = {"entry": e, "age": age, "live": None, "end": None}
        if e.category in ("heartbeat", "lease"):
            row["live"] = age < b.lease_ttl
        elif e.category == "mark":
            row["end"] = b._mark_end(path, info)
            row["live"] = None if row["end"] is None else row["end"] > b.clock()
        out.append(row)
    return out


def _read_json(b: Broker, path: str) -> dict:
    """A small JSON file of the folder (a heartbeat, ``broker.json``) as a dict, or {} if it cannot be read."""
    try:
        with b.folder.open(path) as f:
            record = json.load(f)
        return record if isinstance(record, dict) else {}
    except (OSError, ValueError):
        return {}


def survey_all(folder, now: float | None = None, lease_ttl: float = LEASE_TTL) -> dict:
    """Returns what a broker's folder holds, from one listing, without changing anything: its format, the workers
    (live or stale), the worker slots per machine and, per kind of resource, how many are held, free, blocked per
    scope and marked for every scope. Ids only: no credential is in the folder (proxies are hashes).

    The result (JSON values): ``path``, ``format`` (``broker.json``'s, None without one), ``now``, ``lease_ttl``;
    ``workers``: one dict per heartbeat (``worker``, ``machine``, ``slot``, ``run``, ``age`` in seconds since its
    last renew, ``live``), live first; ``slots``: machine -> ``{"live": n, "stale": n}`` (a slot is live while a lease
    of it was renewed within the lease time, stale when it has only expired ones); ``kinds``: kind -> ``resources``
    (the ids with a lease or a mark file), ``held`` (``live``: a valid lease; ``stale``: only expired leases, free in
    effect until ``clean`` removes them), ``free`` (no lease file), ``holders`` (worker -> resources it holds),
    ``blocked`` (scope -> ``{"resources": n, "until": latest end}``, live marks for one scope), ``broken`` (the same
    for scope ``*``, or None) and ``expired_marks``.

    Args:
        folder: the broker's folder, any fsspec path (or a datatrove ``DataFolder``).
        now: the time to judge liveness by, seconds since the epoch; None: the clock now.
        lease_ttl: how long a lease and a heartbeat stay valid without a renew (``LEASE_TTL``).

    Example:
        survey_all("OUT/logs/broker")["kinds"]["proxies"]["free"]
    """
    b = _inspector(folder, now, lease_ttl)
    rows = _scan(b)
    fmt = None
    workers, slots, kinds = [], {}, {}
    leases: dict[tuple[str, str], list[tuple[str, str, bool]]] = {}
    for row in rows:
        e = row["entry"]
        if e.category == "format":
            fmt = _read_json(b, e.path).get("format")
        elif e.category == "heartbeat":
            record = _read_json(b, e.path)
            workers.append({"worker": e.rid, "machine": record.get("machine") or e.rid.rpartition("-")[0] or None,
                            "slot": record.get("slot"), "run": record.get("run"), "age": round(row["age"], 3),
                            "live": row["live"]})
        elif e.category == "lease":
            leases.setdefault((e.kind, e.rid), []).append((*e.lease, row["live"]))
        elif e.category == "mark":
            k = kinds.setdefault(e.kind, {"rids": set(), "blocked": {}, "expired_marks": 0})
            k["rids"].add(e.rid)
            if row["live"]:
                ends = k["blocked"].setdefault(e.scope, {})
                ends[e.rid] = max(ends.get(e.rid, 0.0), row["end"])
            elif row["live"] is False:
                k["expired_marks"] += 1
    out_kinds = {}
    for (kind, rid), found in sorted(leases.items()):
        valid = sorted((claimed, holder) for claimed, holder, live in found if live)
        if kind == SLOTS:
            machine, _, _ = rid.rpartition("/")
            counts = slots.setdefault(machine, {"live": 0, "stale": 0})
            counts["live" if valid else "stale"] += 1
            continue
        k = kinds.setdefault(kind, {"rids": set(), "blocked": {}, "expired_marks": 0})
        k["rids"].add(rid)
        k.setdefault("leases", {})[rid] = valid[0][1] if valid else None
    for kind, k in sorted(kinds.items()):
        held = k.get("leases", {})
        holders: dict[str, int] = {}
        for holder in held.values():
            if holder is not None:
                holders[holder] = holders.get(holder, 0) + 1
        live = sum(1 for h in held.values() if h is not None)
        blocked = {scope: {"resources": len(ends), "until": max(ends.values())}
                   for scope, ends in sorted(k["blocked"].items())}
        out_kinds[kind] = {"resources": len(k["rids"]), "held": {"live": live, "stale": len(held) - live},
                           "free": len(k["rids"]) - len(held), "holders": dict(sorted(holders.items())),
                           "blocked": {s: v for s, v in blocked.items() if s != EVERY_SCOPE},
                           "broken": blocked.get(EVERY_SCOPE), "expired_marks": k["expired_marks"]}
    workers.sort(key=lambda w: (not w["live"], w["worker"]))
    return {"path": b.path, "format": fmt, "now": b.clock(), "lease_ttl": lease_ttl, "workers": workers,
            "slots": dict(sorted(slots.items())), "kinds": out_kinds}


def survey_kind(folder, kind: str, now: float | None = None, lease_ttl: float = LEASE_TTL) -> dict:
    """Returns the resources of one kind as a broker's folder holds them, from one listing, without changing anything
    (what ``linecaster.runtime.run.allocate`` counts before a launch): ``resources``, id -> ``Resource`` (the holder
    of its winning valid lease, or None; its live marks per scope, the latest end each), for every resource with a
    lease or a mark file; ``runs``, worker -> the run its live heartbeat names (None when it names none), for the
    workers that hold one of them. A folder that does not exist yet holds nothing.

    Args:
        folder: the broker's folder, any fsspec path (or a datatrove ``DataFolder``).
        kind: the kind of resource (``proxies``).
        now: the time to judge liveness by, seconds since the epoch; None: the clock now.
        lease_ttl: how long a lease and a heartbeat stay valid without a renew (``LEASE_TTL``).

    Example:
        survey_kind("OUT/logs/broker", "proxies")["resources"]
    """
    b = _inspector(folder, now, lease_ttl)
    out: dict[str, Resource] = {}
    leases: dict[str, list[tuple[str, str]]] = {}
    beats: dict[str, str] = {}
    for row in _scan(b):
        e = row["entry"]
        if e.category == "heartbeat" and row["live"]:
            beats[e.rid] = e.path
        elif e.kind != kind:
            continue
        elif e.category == "lease":
            out.setdefault(e.rid, Resource())
            if row["live"]:
                leases.setdefault(e.rid, []).append(e.lease)
        elif e.category == "mark":
            r = out.setdefault(e.rid, Resource())
            if row["live"]:
                r.marks[e.scope] = max(r.marks.get(e.scope, 0.0), row["end"])
    for rid, valid in leases.items():
        out[rid].holder = min(valid)[1]
    holders = {r.holder for r in out.values() if r.holder is not None}
    runs = {w: _read_json(b, beats[w]).get("run") for w in sorted(holders) if w in beats}
    return {"resources": out, "runs": runs}


def clean(folder, *, leases: bool = False, marks: bool = False, dry_run: bool = False, now: float | None = None,
          confirm: Callable[[list[dict]], bool] | None = None, lease_ttl: float = LEASE_TTL) -> dict:
    """Removes what a broker's folder no longer needs, from one listing: by default only what has expired (safe while
    a run uses the broker): heartbeats and leases (worker slots and resources) not renewed within the lease time,
    and marks past their end. ``broker.json`` and files that are not the broker's are never removed.

    ``leases`` also removes every heartbeat, slot lease and resource lease, live or not: the cleanup after a hard
    kill (a killed run's leases look valid for up to the lease time, so a relaunch gets new slots and finds every
    proxy held). ``marks`` also removes every mark (blocked proxies are tried again at once). Both are safe only when
    no run uses the broker: when they would remove something live, ``confirm`` is asked first.

    Raises ``LinecasterError`` (removing nothing) when the folder has no ``broker.json`` of this ``FORMAT``, so a
    wrong path never loses files.

    Returns ``path``, ``dry_run``, ``aborted`` (``confirm`` said no: nothing was removed), ``removed`` (category of
    ``CLEANED`` -> one dict per file: ``path``, ``age``, ``live``; what would be removed with ``dry_run``) and
    ``live`` (the live files among them).

    Args:
        folder: the broker's folder, any fsspec path (or a datatrove ``DataFolder``).
        leases: also remove the live heartbeats, slot leases and resource leases.
        marks: also remove the live marks.
        dry_run: remove nothing; report what would be removed.
        now: the time to judge liveness by, seconds since the epoch; None: the clock now.
        confirm: called with the live files about to be removed (when there are any, and not ``dry_run``); False
            aborts and nothing is removed. None removes them without asking.
        lease_ttl: how long a lease and a heartbeat stay valid without a renew (``LEASE_TTL``).

    Example:
        clean("OUT/logs/broker", leases=True)["removed"]["slots"]
    """
    b = _inspector(folder, now, lease_ttl)
    rows = _scan(b)
    fmt = next((_read_json(b, r["entry"].path).get("format") for r in rows if r["entry"].category == "format"), None)
    if fmt != FORMAT:
        raise LinecasterError(f"{b.path} is not a broker of format {FORMAT} (broker.json: "
                              f"{fmt or 'missing or unreadable'}); nothing removed")
    removed: dict[str, list[dict]] = {c: [] for c in CLEANED}
    for row in rows:
        e, live = row["entry"], row["live"]
        category = _category(e)
        if category not in CLEANED:
            continue
        forced = marks if category == "marks" else leases
        if live is False or forced:
            removed[category].append({"path": e.path, "age": round(row["age"], 3), "live": live is not False})
    live = [f for c in CLEANED for f in removed[c] if f["live"]]
    result = {"path": b.path, "dry_run": dry_run, "aborted": False, "removed": removed, "live": live}
    if dry_run:
        return result
    if live and confirm is not None and not confirm(live):
        return {**result, "aborted": True}
    for c in CLEANED:
        for f in removed[c]:
            b._rm(f["path"])
    return result


#: the categories ``purge`` removes: ``broker.json`` and ``CLEANED``
PURGED = ("broker.json", *CLEANED)


def _category(e: Entry) -> str | None:
    """The category of ``PURGED`` a file of the broker's folder belongs to, or None for a file that is not the
    broker's."""
    if e.category == "lease":
        return "slots" if e.kind == SLOTS else "leases"
    return {"format": "broker.json", "heartbeat": "heartbeats", "mark": "marks"}.get(e.category)


def purge(folder, *, dry_run: bool = False, now: float | None = None,
          confirm: Callable[[dict], bool] | None = None, lease_ttl: float = LEASE_TTL) -> dict:
    """Resets a broker: removes every file of its layout, ``broker.json``, heartbeats, slot leases, resource leases
    and marks of every kind, live or not, so the next run starts as on an empty folder. Files that are not the
    broker's stay. Safe only when no run uses the broker; ``clean`` with ``leases`` and ``marks`` keeps the format
    file and is enough after a hard kill.

    Raises ``LinecasterError`` (removing nothing) when the folder does not look like a broker's (neither
    ``broker.json`` nor ``workers/`` or ``slots/`` files), so a wrong path never loses files.

    Returns ``path``, ``dry_run``, ``aborted`` (``confirm`` said no: nothing was removed), ``removed`` (category of
    ``PURGED`` -> one dict per file: ``path``, ``age``, ``live``; what would be removed with ``dry_run``),
    ``live_workers`` and ``live_marks`` (how many of them are live).

    Args:
        folder: the broker's folder, any fsspec path (or a datatrove ``DataFolder``).
        dry_run: remove nothing; report what would be removed.
        now: the time to judge liveness by, seconds since the epoch; None: the clock now.
        confirm: called with the result before anything is removed (unless ``dry_run``, or there is nothing to
            remove); False aborts and nothing is removed. None removes without asking.
        lease_ttl: how long a lease and a heartbeat stay valid without a renew (``LEASE_TTL``).

    Example:
        purge("OUT/logs/broker", dry_run=True)["removed"]["marks"]
    """
    b = _inspector(folder, now, lease_ttl)
    rows = _scan(b)
    if not any(r["entry"].category == "format" or r["entry"].path.partition("/")[0] in ("workers", SLOTS)
               for r in rows):
        raise LinecasterError(f"{b.path} does not look like a broker's folder (no broker.json, workers/ or "
                              f"{SLOTS}/); nothing removed")
    removed: dict[str, list[dict]] = {c: [] for c in PURGED}
    for row in rows:
        category = _category(row["entry"])
        if category is not None:
            removed[category].append({"path": row["entry"].path, "age": round(row["age"], 3),
                                      "live": row["live"] is not False and category != "broker.json"})
    result = {"path": b.path, "dry_run": dry_run, "aborted": False, "removed": removed,
              "live_workers": sum(f["live"] for f in removed["heartbeats"]),
              "live_marks": sum(f["live"] for f in removed["marks"])}
    if dry_run or not any(removed.values()):
        return result
    if confirm is not None and not confirm(result):
        return {**result, "aborted": True}
    for c in reversed(PURGED):                                # broker.json last: an interrupted purge stays one
        for f in removed[c]:
            b._rm(f["path"])
    _remove_empty_folders(b)
    return result


def _remove_empty_folders(b: Broker) -> None:
    """Removes the folders left empty under the broker's folder (on storage that has folders), deepest first."""
    try:
        found = b.folder.find("", withdirs=True, detail=True)
    except (FileNotFoundError, OSError):
        return
    for path in sorted((p for p, info in found.items() if info.get("type") == "directory" and p),
                       key=lambda p: p.count("/"), reverse=True):
        try:
            b.folder.rmdir(path)
        except (FileNotFoundError, OSError):
            pass                                              # not empty: a file that is not the broker's


_SHARED: dict[tuple, Broker] = {}
_SHARED_LOCK = threading.Lock()
_LOCAL: list[str] = []


def shared(folder: str | None, run: str | None = None) -> Broker:
    """Returns this process's broker for ``folder``, made at the first use; None: a local folder of this process's own
    (no other worker shares it). A process that ends normally hands its slots over (``hand_over_shared``, at exit);
    one that is killed leaves them to expire.

    Args:
        folder: the broker's folder (any fsspec path), or None.
        run: what the heartbeat names as the run.
    """
    with _SHARED_LOCK:
        if folder is None:
            if not _LOCAL:
                import tempfile

                _LOCAL.append(tempfile.mkdtemp(prefix="linecaster-broker-"))
            folder = _LOCAL[0]
        key = (os.getpid(), folder)
        broker = _SHARED.get(key)
        if broker is None:
            if not _SHARED:                                   # a process that ends normally hands its slot over
                import atexit

                atexit.register(hand_over_shared)
            broker = _SHARED[key] = Broker(folder, run=run)
        return broker


def hand_over_shared() -> None:
    """Hands over the slots of this process's shared brokers (``Broker.hand_over``): at the end of a process whose
    worker slot another process may take next (a Ray task). A broker in a folder of this process's own (``shared``
    without a folder) is closed and its folder forgotten."""
    with _SHARED_LOCK:
        brokers = [b for (pid, _), b in _SHARED.items() if pid == os.getpid()]
        _SHARED.clear()
        local = list(_LOCAL)
        _LOCAL.clear()                                        # a process's own folder: nobody takes it over
    for broker in brokers:
        try:
            broker.close() if broker.path in local else broker.hand_over()
        except Exception as e:  # noqa: BLE001 - the slot then expires after the lease time
            logger.warning("broker {path}: slot not handed over: {error}", path=broker.path, error=e)


def resource_id(text: str) -> str:
    """Returns a credential-free, fixed-length id for ``text`` (a hash), for resources whose names are secret.

    Args:
        text: what names the resource (e.g. a proxy's host and port).
    """
    return hashlib.sha256(text.encode()).hexdigest()[:16]
