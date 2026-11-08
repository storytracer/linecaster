"""Proxy blocks shared through a folder, as datatrove shares finished tasks through completion markers: every worker of
a run (local, Slurm, Ray, HF Jobs), and every later run pointed at the same folder, leaves out the proxies any of them
found blocked.

A block is a marker written once and never changed::

    <folder>/<host>/<proxy id>/<blocked at>-<n>-<worker>.json    {"ttl": 259200, "status": "429", "worker": ...}

The proxy id is a hash of the proxy's host and port, so no credential reaches the folder. A marker's block lasts
``ttl`` seconds from the marker's modification time as the storage reports it (the writer's clock where it reports
none), so the machines' clocks do not matter. A proxy is left out while any of its markers lasts; a second marker
appears only where another worker sent a request through the proxy before it had read the first, which started the
server's block again. Markers are read once (they never change) and deleted by whoever sees them expired.

``HTTPFetcher`` writes a marker when resilient-httpx leaves a proxy out (``on_blacklist``) and reads a host's markers
at its first request there and every ``POLL_SECONDS`` after (``--proxy-blocks``; default ``OUT/logs/proxy-blocks``).
Between two reads another worker may still send a request or two through a proxy just blocked.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import threading
import time
import uuid
from datetime import datetime

from loguru import logger

#: how often a fetcher reads the markers of the hosts it has sent requests to
POLL_SECONDS = 30.0


def proxy_id(proxy: str) -> str:
    """A proxy's name in the folder: a hash of its host and port, without scheme or credentials."""
    address = proxy.split("://", 1)[-1].rsplit("@", 1)[-1].rstrip("/").lower()
    return hashlib.sha256(address.encode()).hexdigest()[:16]


def _modified(info: dict) -> float | None:
    """A listing entry's modification time (seconds since the epoch) as the storage reports it, or None."""
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


class ProxyBlocks:
    """The block markers in ``folder`` (any fsspec path): ``write`` one, ``live`` the blocks of a host."""

    def __init__(self, folder: str):
        from datatrove.io import get_datafolder

        self.path = folder
        self.folder = get_datafolder(folder)
        self.worker = f"{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._count = itertools.count()                     # a name never repeats, even within a millisecond
        self._lock = threading.Lock()
        self._until: dict[str, tuple[str, float]] = {}      # marker path -> (proxy id, end in seconds since the epoch)

    def write(self, host: str, proxy: str, ttl: float, status: str | None = None) -> str:
        """A new marker: ``proxy`` blocked at ``host`` for ``ttl`` seconds from now. Returns its path."""
        now = time.time()
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now)) + f"{int(now % 1 * 1000):03d}Z"
        path = f"{host}/{proxy_id(proxy)}/{stamp}-{next(self._count)}-{self.worker}.json"
        record = {"ttl": round(ttl, 3), "blocked_at": now, "status": status, "worker": self.worker}
        self.folder.makedirs(f"{host}/{proxy_id(proxy)}", exist_ok=True)
        with self.folder.open(path, "w") as f:
            json.dump(record, f)
        with self._lock:
            self._until[path] = (proxy_id(proxy), now + ttl)
        return path

    def live(self, host: str, others_only: bool = True) -> dict[str, float]:
        """The proxies blocked at ``host``: proxy id -> seconds the block still lasts (the longest of its markers).
        ``others_only``: leave out this process's own markers (it knows its blocks). Expired markers are deleted."""
        try:
            listing = self.folder.find(host, detail=True)
        except FileNotFoundError:
            return {}
        now, out, expired = time.time(), {}, []
        for path, info in listing.items():
            if not path.endswith(".json") or (others_only and path.endswith(f"-{self.worker}.json")):
                continue
            with self._lock:
                known = self._until.get(path)
            if known is None:
                known = self._read(path, info)
                if known is None:
                    continue
                with self._lock:
                    self._until[path] = known
            pid, until = known
            if until <= now:
                expired.append(path)
            else:
                out[pid] = max(out.get(pid, 0.0), until - now)
        for path in expired:
            try:
                self.folder.rm(path)
            except (FileNotFoundError, OSError):
                pass                                        # deleted by another worker meanwhile
            with self._lock:
                self._until.pop(path, None)
        return out

    def _read(self, path: str, info: dict) -> tuple[str, float] | None:
        try:
            with self.folder.open(path) as f:
                record = json.load(f)
            ttl = float(record["ttl"])
        except FileNotFoundError:
            return None                                     # expired and deleted by another worker meanwhile
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("proxy block marker {path} unreadable, ignored: {error}", path=path, error=e)
            return None
        start = _modified(info) or float(record.get("blocked_at") or time.time())
        return path.split("/")[-2], start + ttl
