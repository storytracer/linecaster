"""The workers of a run through proxies (``linecaster.runtime.run.allocate``): one per available proxy, the proxies in
the file less those blocked or broken in the broker and those held by another run's live workers (the run's own
earlier leases count as available), never capped by the CPUs; divided by ``proxies_per_worker``; one worker with a
rate-limited host without proxies, or a list shared fairly; ``--workers`` overrides; the run says why."""
import time

import pytest

from linecaster.broker import Broker
from linecaster.net.proxies import KIND, proxy_id
from linecaster.runtime import run

PROXIES = [f"10.0.0.{i}:8080" for i in range(7)]


def options(tmp_path, *argv):
    (tmp_path / "proxies.txt").write_text("".join(f"{p}\n" for p in PROXIES))
    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(["--items", "items.parquet", "--item-key", "id", "OUT", "--tasks", "100",
                                     *[x.replace("PROXIES", str(tmp_path / "proxies.txt")) for x in argv]]))
    a.has_engines = False
    return a


def policy(tmp_path, text: str) -> str:
    (tmp_path / "policy.yaml").write_text(text.replace("PROXIES", str(tmp_path / "proxies.txt")))
    return str(tmp_path / "policy.yaml")


@pytest.fixture
def no_cpus(monkeypatch):
    monkeypatch.setattr(run.os, "cpu_count", lambda: 2)                     # the proxies decide, not the CPUs


def test_a_first_launch_runs_a_worker_per_proxy(tmp_path, no_cpus):
    a = options(tmp_path, "--proxies", "PROXIES", "--rate-limit", "150/60", "--broker", str(tmp_path / "broker"))
    run.allocate(a, [])
    assert a.workers == 7 and run.workers_note(a) == "7 proxies available → 7 workers, 1 proxy each"
    assert run.run_notes(a)[0] == run.workers_note(a)
    few = options(tmp_path, "--proxies", "PROXIES", "--tasks", "3", "--broker", str(tmp_path / "broker"))
    run.allocate(few, [])
    assert few.workers == 3 and run.workers_note(few) == "7 proxies available, 3 tasks → 3 workers, 1 proxy each"
    given = options(tmp_path, "--proxies", "PROXIES", "--workers", "5")
    run.allocate(given, [])
    assert given.workers == 5 and run.workers_note(given) is None


def test_blocked_proxies_and_other_runs_leases_are_not_available(tmp_path, no_cpus):
    broker = str(tmp_path / "broker")
    ids = [proxy_id(p) for p in PROXIES]
    blocker = Broker(broker, worker="x-0")
    blocker.mark(KIND, ids[0], "tile.loc.gov", time.time() + 600, status=429)          # blocked at a host
    blocker.mark(KIND, ids[1], "*", time.time() + 600, status="broken")               # broken
    other = Broker(broker, machine="n", run="ELSEWHERE", worker_index=(0, 1))
    assert other.claim(KIND, ids[2])                                                    # another run's
    own = Broker(broker, machine="m", run="OUT", worker_index=(0, 1))
    assert own.claim(KIND, ids[3])                                                      # this run's earlier lease
    a = options(tmp_path, "--proxies", "PROXIES", "--rate-limit", "150/60", "--broker", broker)
    run.allocate(a, [])
    assert a.workers == 4
    assert run.workers_note(a) == ("4 proxies available (7 in the list, 2 blocked or broken, 1 held by other runs) "
                                   "→ 4 workers, 1 proxy each")
    hosts = policy(tmp_path, f"broker: {broker}\nhosts:\n  www.loc.gov: {{proxies: PROXIES, rate_limits: [\"5/1\"]}}\n")
    known = options(tmp_path, "--http-policy", hosts)
    run.allocate(known, [])
    assert known.workers == 5                                     # its only host: the block at tile.loc.gov is not


def test_a_rate_limited_host_without_proxies_keeps_one_worker(tmp_path, no_cpus):
    a = options(tmp_path, "--http-policy", policy(tmp_path, "hosts:\n  a.org: {proxies: PROXIES, rate_limits: "
                                                            "[\"5/1\"]}\n  b.org: {rate_limits: [\"5/1\"], direct: "
                                                            "true}\n"))
    run.allocate(a, [])
    assert a.workers == 1 and run.workers_note(a) is None


def test_up_to_n_per_worker_divides_the_available_proxies(tmp_path, no_cpus):
    a = options(tmp_path, "--http-policy", policy(tmp_path, "proxies: PROXIES\nrate_limits: [\"5/1\"]\n"
                                                            "proxies_per_worker: 3\n"))
    run.allocate(a, [])
    assert a.workers == 3 and run.workers_note(a) == "7 proxies available → 3 workers, up to 3 each"   # ceil(7 / 3)
    shared = options(tmp_path, "--http-policy", policy(tmp_path, "proxies: PROXIES\nrate_limits: [\"5/1\"]\n"
                                                                 "proxies_per_worker: share\n"))
    run.allocate(shared, [])
    assert shared.workers == 1 and run.workers_note(shared) is None                 # a fair share: as before


def test_on_hf_jobs_the_proxies_do_not_set_the_workers(tmp_path, no_cpus):
    """Each worker of an HF Jobs run is a Job: a proxy list never turns into a Job per proxy."""
    a = options(tmp_path, "--proxies", "PROXIES", "--rate-limit", "150/60", "--broker", str(tmp_path / "broker"),
                "--on", "hf-jobs", "--commit", "abc1234")
    run.allocate(a, [])
    assert a.workers == 1
