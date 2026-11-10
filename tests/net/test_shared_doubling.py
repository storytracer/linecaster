"""The doubling of a proxy's blocks travels with the proxy through the broker (``linecaster.net.proxies.ProxyPool``):
each mark records its last wait without ``Retry-After`` (``last_wait``) and is kept that long past its end
(``keep``), so a worker that claims a released proxy continues the doubling where the last owner left it. It starts
again after a successful response through the proxy at that host (the ended marks are deleted, so the next owner
starts again too) or once the quiet period has passed (as long as the last wait, after the last block ended). The
same holds for a broken proxy's time out (scope ``*``).

The marks stay compatible both ways: a mark of an earlier version (without ``last_wait`` and ``keep``) starts the
doubling at 60 s, and an earlier version reads a newer mark's end from its ``ttl`` as before, ignoring the new fields.

Two workers are two brokers on one folder; the storage keeps the brokers' clock (``ClockedBroker``), so time passes
by moving the clock."""
import json
import os
import re
import time

import pytest

from linecaster.broker import EVERY_SCOPE, FORMAT, Broker, clean, survey_all
from linecaster.net.proxies import KIND, ProxyPool, proxy_id

HOST = "images.library.test"
PROXY = "http://user:secret@10.0.0.1:8080"
PID = proxy_id(PROXY)


class Wall:
    """Seconds since the epoch, moved by hand."""

    def __init__(self):
        self.t = float(int(time.time()))

    def __call__(self) -> float:
        return self.t


class ClockedBroker(Broker):
    """A broker whose storage keeps the broker's clock: what it writes gets the clock's time as its modification
    time, so the marks of other workers end on that clock too. Leases never expire (nothing renews them here)."""

    def __init__(self, folder, worker: str, clock: Wall):
        super().__init__(folder, worker=worker, clock=clock, lease_ttl=1e9)

    def _write(self, path: str, record: dict) -> None:
        super()._write(path, record)
        t = self.clock()
        os.utime(os.path.join(self.folder.path, path), (t, t))


def pool(tmp_path, name: str, wall: Wall) -> ProxyPool:
    broker = ClockedBroker(str(tmp_path), name, wall)
    broker._init_folder()
    broker.heartbeat()
    return ProxyPool(broker, [PROXY], keep_alive=False, per_worker=1)


def mark_files(tmp_path, scope: str = HOST) -> list:
    folder = tmp_path / KIND / PID / "marks" / scope
    return sorted(folder.iterdir()) if folder.exists() else []


def last_mark(tmp_path, scope: str = HOST) -> dict:
    """The newest mark's record (names sort by their end)."""
    return json.loads(mark_files(tmp_path, scope)[-1].read_text())


def block(p: ProxyPool, wall: Wall, tmp_path, scope: str = HOST) -> float:
    """Claims the proxy for ``p`` and blocks it at ``scope`` without Retry-After (``*``: broken at once); returns the
    block's length."""
    assert p.fill(HOST, force=True) == 1, "the proxy should be free to claim"
    if scope == EVERY_SCOPE:
        p.broken(PROXY, after=1, first=300, cap=3600)
    else:
        p.block(PROXY, scope, status=429)
    return round(last_mark(tmp_path, scope)["ttl"])


def until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_worker_that_claims_a_released_proxy_continues_its_doubling(tmp_path):
    """Worker a blocks the proxy (60 s) and releases it; worker b claims it when the block ends and is blocked again:
    120 s, not 60. Then a again, 100 s after that block ended (within its quiet period, 120 s): 240 s. Each mark
    records the doubling and is kept that long past its end."""
    wall = Wall()
    a, b = pool(tmp_path, "a-0", wall), pool(tmp_path, "b-0", wall)
    assert block(a, wall, tmp_path) == 60 and a.held() == 0                    # released: blocked where a fetches
    assert {k: last_mark(tmp_path)[k] for k in ("last_wait", "keep", "status", "worker")} == {
        "last_wait": 60.0, "keep": 60.0, "status": 429, "worker": "a-0"}
    assert b.fill(HOST, force=True) == 0                                         # the block holds for b too
    wall.t += 60
    assert block(b, wall, tmp_path) == 120
    wall.t += 120 + 100
    assert block(a, wall, tmp_path) == 240
    assert last_mark(tmp_path)["last_wait"] == 240.0 and last_mark(tmp_path)["worker"] == "a-0"


def test_a_successful_response_starts_the_doubling_again_for_the_next_owner_too(tmp_path):
    """b claims the proxy after a's block and carries a successful response from the host: its doubling starts
    again, and the ended marks are deleted from the broker, so a, claiming it next, starts at 60 s."""
    wall = Wall()
    a, b = pool(tmp_path, "a-0", wall), pool(tmp_path, "b-0", wall)
    assert block(a, wall, tmp_path) == 60
    wall.t += 60
    assert b.fill(HOST, force=True) == 1
    b.answered(PROXY, HOST)
    until(lambda: not mark_files(tmp_path))                                     # deleted in a thread
    b.broker.release(KIND, PID)                                                  # given back
    b._owned.discard(PID)
    assert block(a, wall, tmp_path) == 60


def test_an_answer_for_a_request_sent_before_the_block_keeps_the_doubling(tmp_path):
    wall = Wall()
    a = pool(tmp_path, "a-0", wall)
    assert block(a, wall, tmp_path) == 60
    a.answered(PROXY, HOST)                                                      # its block still holds
    wall.t += 60
    assert block(a, wall, tmp_path) == 120


def test_the_doubling_starts_again_after_its_quiet_period(tmp_path):
    """Nobody blocked at the host for longer than the last wait after the last block ended: 60 s again; the mark was
    kept that long and is gone."""
    wall = Wall()
    a, b = pool(tmp_path, "a-0", wall), pool(tmp_path, "b-0", wall)
    assert block(a, wall, tmp_path) == 60
    wall.t += 60 + 61
    assert block(b, wall, tmp_path) == 60
    assert len(mark_files(tmp_path)) == 1                                        # the old one deleted, past its keep


def test_a_broken_proxys_time_out_doubles_across_workers_too(tmp_path):
    wall = Wall()
    a, b = pool(tmp_path, "a-0", wall), pool(tmp_path, "b-0", wall)
    assert block(a, wall, tmp_path, EVERY_SCOPE) == 300
    wall.t += 300
    assert block(b, wall, tmp_path, EVERY_SCOPE) == 600
    b.answered(PROXY)                                                            # sent before it broke: kept
    assert len(mark_files(tmp_path, EVERY_SCOPE)) == 2
    wall.t += 600
    b.answered(PROXY)                                                            # any answer through it
    until(lambda: not mark_files(tmp_path, EVERY_SCOPE))
    assert block(a, wall, tmp_path, EVERY_SCOPE) == 300


# ---------------------------------------------------------------- compatibility of the marks, both ways


def old_mark(tmp_path, wall: Wall, ttl: float, scope: str = HOST) -> str:
    """A mark as linecaster 0.4.0 wrote it: the same path, a record without ``last_wait`` and ``keep``."""
    until_ = wall.t + ttl
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(until_)) + f"{int(until_ % 1 * 1000):03d}Z"
    folder = tmp_path / KIND / PID / "marks" / scope
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp}-old-0.0.json"
    path.write_text(json.dumps({"ttl": ttl, "until": until_, "worker": "old-0", "status": 429}))
    os.utime(path, (wall.t, wall.t))
    (tmp_path / "broker.json").write_text(json.dumps({"format": FORMAT, "created": wall.t}))
    return str(path)


def end_as_0_4_0(path) -> float:
    """A mark's end as linecaster 0.4.0 reads it (``Broker._mark_end``): the record's ``ttl`` from the file's
    modification time; it knows nothing else of the record, and deletes the mark once that end has passed."""
    with open(path) as f:
        record = json.load(f)
    return os.stat(path).st_mtime + float(record["ttl"])


def test_a_mark_of_an_earlier_version_holds_and_starts_the_doubling_at_60_s(tmp_path):
    """A newer worker reading an older mark (no ``last_wait``): the block holds until its end, and the next block
    starts the doubling at 60 s, whatever the older mark's length."""
    wall = Wall()
    old_mark(tmp_path, wall, 120)
    b = pool(tmp_path, "b-0", wall)
    assert b.fill(HOST, force=True) == 0 and b.outlook(HOST)[0] == pytest.approx(120)
    wall.t += 120
    assert block(b, wall, tmp_path) == 60


def test_an_earlier_version_reads_a_newer_marks_end_and_ignores_its_new_fields(tmp_path):
    """The newer mark keeps 0.4.0's path layout and record (``ttl``, ``until``, ``worker``, ``status``), so 0.4.0
    reads its end as the newer worker does; ``last_wait`` and ``keep`` are fields it ignores. When it deletes the mark
    at its end (it knows no ``keep``), a newer worker starts the doubling at 60 s again."""
    wall = Wall()
    a = pool(tmp_path, "a-0", wall)
    block(a, wall, tmp_path)
    wall.t += 60
    block(pool(tmp_path, "b-0", wall), wall, tmp_path)                           # 120 s, keep 120
    (path,) = [p for p in mark_files(tmp_path) if json.loads(p.read_text())["worker"] == "b-0"]
    assert re.fullmatch(r"\d{8}T\d{6}\d{3}Z-b-0\.\d+\.json", path.name)
    record = json.loads(path.read_text())
    assert set(record) == {"ttl", "until", "worker", "status", "last_wait", "keep"}
    assert end_as_0_4_0(path) == pytest.approx(record["until"]) == pytest.approx(wall.t + 120)
    assert json.loads((tmp_path / "broker.json").read_text())["format"] == FORMAT == "linecaster.broker/1"
    wall.t += 120
    for p in mark_files(tmp_path):                                               # 0.4.0 deletes it at its end
        if end_as_0_4_0(p) <= wall.t:
            p.unlink()
    assert block(pool(tmp_path, "c-0", wall), wall, tmp_path) == 60


def test_clean_keeps_a_kept_mark_and_status_does_not_count_it_expired(tmp_path):
    wall = Wall()
    a = pool(tmp_path, "a-0", wall)
    block(a, wall, tmp_path)                                                     # ends in 60 s, kept 60 s more
    kept = wall.t + 90
    assert survey_all(str(tmp_path), now=kept)["kinds"][KIND]["expired_marks"] == 0
    assert clean(str(tmp_path), now=kept)["removed"]["marks"] == []
    assert len(clean(str(tmp_path), now=wall.t + 121)["removed"]["marks"]) == 1
    assert mark_files(tmp_path) == []


def test_clean_with_marks_removes_kept_marks_too(tmp_path):
    wall = Wall()
    block(pool(tmp_path, "a-0", wall), wall, tmp_path)
    removed = clean(str(tmp_path), marks=True, now=wall.t + 90)["removed"]["marks"]
    assert len(removed) == 1 and mark_files(tmp_path) == []
