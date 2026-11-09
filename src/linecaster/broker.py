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
theirs. There is no exclusive create: two claims at once are told apart by listing. A holder that finds an earlier
valid lease than its own at a renew (only after it went more than ``LEASE_TTL`` without one) gives the resource up.

A **mark** says that something holds for a resource in a scope (a host, or ``*`` for every scope) until a time: it
lasts ``ttl`` seconds from its file's modification time. Marks are written once and never changed; whoever sees one
expired deletes it.

The **worker identity** is a datatrove worker slot, not a process: on Ray every task is a new process, and leases tied
to processes would change hands with every task. At its first use a process claims the lowest free slot of its
machine (``slots/<machine>/<n>``, a lease held by the process) and is the worker ``<machine>-<n>`` from then on; a
later process on the same machine that claims the same slot once it is free is the same worker again, and holds (and
renews) that worker's leases, which are named after the worker. A process that ends hands its slot over
(``hand_over``) and leaves its other leases to the slot's next process; leases nobody renews expire after
``LEASE_TTL``.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger

#: the broker's format, in ``broker.json``
FORMAT = "linecaster.broker/1"
#: a lease (and a heartbeat) is valid this long after it was last written
LEASE_TTL = 180.0
#: how often ``keep_alive`` renews the leases and the heartbeat
RENEW_SECONDS = 60.0
#: the kind of the worker slots
SLOTS = "slots"
#: the scope of a mark that holds in every scope
EVERY_SCOPE = "*"
_STAMP = len("20261109T101500123Z")


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
        worker: this worker's identity; None (the default) claims the lowest free slot of this machine at the first
            use (``worker``).
        clock: the time now, seconds since the epoch (``time.time``); compared with the storage's modification times
            and written into names.
        machine: this machine's name (default ``machine_name()``).
        run: what the heartbeat names as the worker's run (e.g. the output folder); informational.
        lease_ttl: how long a lease and a heartbeat stay valid without a renew (``LEASE_TTL``).
        renew_seconds: how often ``keep_alive`` renews (``RENEW_SECONDS``).
    """

    _instances = itertools.count()

    def __init__(self, folder, worker: str | None = None, clock: Callable[[], float] = time.time,
                 machine: str | None = None, run: str | None = None, lease_ttl: float = LEASE_TTL,
                 renew_seconds: float = RENEW_SECONDS):
        from datatrove.io import get_datafolder

        self.folder = get_datafolder(folder)
        self.path = folder if isinstance(folder, str) else self.folder.path
        self.clock, self.lease_ttl, self.renew_seconds = clock, lease_ttl, renew_seconds
        self.machine = _safe(machine) if machine else machine_name()
        self.run = run
        self._worker = _safe(worker) if worker else None
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
        use (the lowest free one of its machine)."""
        with self._lock:
            if self._worker is None:
                self._init_folder()
                self._claim_slot()
                self.heartbeat()
            return self._worker

    def _claim_slot(self) -> None:
        taken = set()
        for path, info in self._list(f"{SLOTS}/{self.machine}").items():
            n, _, rest = path[len(SLOTS) + len(self.machine) + 2:].partition("/leases/")
            if rest and self._age(info) < self.lease_ttl:
                taken.add(n)
        for n in itertools.count():
            if str(n) in taken:
                continue
            name = self._claim(SLOTS, f"{self.machine}/{n}", self._token)
            if name is not None:
                self._slot = (f"{self.machine}/{n}", name)
                self._worker = f"{self.machine}-{n}"
                logger.debug("broker {path}: this process is worker {worker}", path=self.path, worker=self._worker)
                return

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
            name = path.rpartition("/")[2]
            if not name.endswith(".json"):
                continue
            if self._age(info) < self.lease_ttl:
                live.append(name[:-5])
            else:
                self._rm(path)
        return sorted(live)

    # ------------------------------------------------------------------ leases

    def _lease_name(self, holder: str) -> str:
        return f"{_stamp(self.clock())}-{holder}.json"

    def _valid(self, listing: dict[str, dict], prefix: str, own: str | None = None) -> list[tuple[str, str, str]]:
        """The valid leases under ``prefix`` (a resource's ``leases/``) as (claimed, holder, name), earliest first;
        ``own`` (a name) counts as valid whatever its age (it was just written). Expired ones are deleted."""
        out = []
        for path, info in listing.items():
            name = path.rpartition("/")[2]
            if not path.startswith(prefix) or not name.endswith(".json") or len(name) < _STAMP + 6:
                continue
            if name != own and self._age(info) >= self.lease_ttl:
                self._rm(path)
                continue
            out.append((name[:_STAMP], name[_STAMP + 1:-5], name))
        return sorted(out)

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
            rid, sep, name = path[len(kind) + 1:].partition("/leases/")
            if not sep or not name.endswith(mine) or (kind, rid) in self._held:
                continue
            prefix = f"{kind}/{rid}/leases/"
            valid = self._valid({p: i for p, i in listing.items() if p.startswith(prefix)}, prefix)
            if valid and valid[0][2] == name:
                self._held[(kind, rid)] = name
                logger.debug("broker {path}: worker {worker} holds {kind}/{rid} again", path=self.path,
                             worker=self._worker, kind=kind, rid=rid)

    def renew(self) -> list[tuple[str, str]]:
        """Renews this process's slot, every lease this worker holds and its heartbeat. Gives up a resource whose
        lease file is gone (it went without a renew past the lease time and another worker deleted it as expired) or
        whose earliest valid lease is no longer its own. Returns the (kind, id) given up."""
        self.worker
        with self._lock:
            held = dict(self._held)
            slot = self._slot
        if slot is not None:
            self._write(f"{SLOTS}/{slot[0]}/leases/{slot[1]}", {"holder": self._token, "renewed": self.clock()})
        lost = []
        for kind in sorted({k for k, _ in held}):
            listing = self._list(kind)
            for (k, rid), name in held.items():
                if k != kind:
                    continue
                path = f"{kind}/{rid}/leases/{name}"
                if path not in listing:
                    lost.append((kind, rid))
                    continue
                self._write(path, {"holder": self._worker, "renewed": self.clock()})
                prefix = f"{kind}/{rid}/leases/"
                valid = self._valid({p: i for p, i in listing.items() if p.startswith(prefix)}, prefix, own=name)
                if valid and valid[0][2] != name:
                    lost.append((kind, rid))
        self.heartbeat()
        for kind, rid in lost:
            logger.warning("broker {path}: worker {worker} lost {kind}/{rid} (no renew within the lease time); it "
                           "gives it up", path=self.path, kind=kind, rid=rid, worker=self._worker)
            self.release(kind, rid)
        return lost

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
            rest = path[len(kind) + 1:]
            for part in ("/leases/", "/marks/"):
                rid, sep, tail = rest.partition(part)
                if sep:
                    scope = tail.partition("/")[0] if part == "/marks/" else ""
                    groups.setdefault((rid, part, scope), {})[path] = info
                    break
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


_SHARED: dict[tuple, Broker] = {}
_SHARED_LOCK = threading.Lock()
_LOCAL: list[str] = []


def shared(folder: str | None, run: str | None = None) -> Broker:
    """Returns this process's broker for ``folder``, made at the first use; None: a local folder of this process's own
    (no other worker shares it).

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
