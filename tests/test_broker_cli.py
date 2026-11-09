"""The broker's folder as a whole (``linecaster.broker.survey_all``, ``clean``, ``purge``) and ``linecaster broker``:
what a status counts as live, stale, held, free, blocked and broken; what ``clean`` removes by default (only what has
expired), with ``leases`` (every heartbeat and lease: the cleanup after a hard kill) and with ``marks``; ``purge``
(everything of the layout); the confirmation, refused without a terminal. A killed process is a broker that is
dropped without ``hand_over`` or ``close``; time passes by moving the files' modification times back (``age``)."""
import io
import json
import time

import pytest

from linecaster import cli
from linecaster.broker import LEASE_TTL, Broker, clean, purge, survey_all
from linecaster.errors import LinecasterError

from test_broker import age


def files(folder) -> set[str]:
    return {str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def folder(tmp_path):
    """A broker with a stale worker ``n-0`` (killed over 3 minutes ago: its slot, its lease of proxy ``a`` and a
    block of ``a`` expired) and a live worker ``m-0`` (killed just now: it holds ``b``, ``c`` is blocked at one host,
    ``d`` is broken)."""
    dead = Broker(str(tmp_path), machine="n", run="earlier")
    assert dead.worker == "n-0" and dead.claim("proxies", "a")
    dead.mark("proxies", "a", "old.example.org", time.time() + 10, status=429)
    age(tmp_path, LEASE_TTL + 10)
    live = Broker(str(tmp_path), machine="m", run="out")
    assert live.worker == "m-0" and live.claim("proxies", "b")
    live.mark("proxies", "c", "example.org", time.time() + 600, status=429)
    live.mark("proxies", "d", "*", time.time() + 900, status="broken")
    return tmp_path


def test_status_counts_live_stale_held_free_blocked_and_broken(folder):
    now = time.time()
    report = survey_all(str(folder), now=now)
    assert report["format"] == "linecaster.broker/1"
    assert [(w["worker"], w["machine"], w["run"], w["live"]) for w in report["workers"]] == [
        ("m-0", "m", "out", True), ("n-0", "n", "earlier", False)]
    assert report["slots"] == {"m": {"live": 1, "stale": 0}, "n": {"live": 0, "stale": 1}}
    proxies = report["kinds"]["proxies"]
    assert {k: proxies[k] for k in ("resources", "held", "free", "holders", "expired_marks")} == {
        "resources": 4, "held": {"live": 1, "stale": 1}, "free": 2, "holders": {"m-0": 1}, "expired_marks": 1}
    assert list(proxies["blocked"]) == ["example.org"] and proxies["blocked"]["example.org"]["resources"] == 1
    assert now + 590 < proxies["blocked"]["example.org"]["until"] <= now + 601
    assert proxies["broken"]["resources"] == 1 and proxies["broken"]["until"] > now + 890
    later = survey_all(str(folder), now=now + LEASE_TTL + 1)            # nobody renews: everything is stale
    assert not any(w["live"] for w in later["workers"]) and later["kinds"]["proxies"]["held"]["live"] == 0
    assert json.dumps(report)                                           # JSON values only


def test_clean_by_default_removes_only_what_expired(folder):
    before = files(folder)
    result = clean(str(folder))
    gone = before - files(folder)
    assert {c: len(f) for c, f in result["removed"].items()} == {"heartbeats": 1, "slots": 1, "leases": 1, "marks": 1}
    assert gone == {f["path"] for fs in result["removed"].values() for f in fs} and not result["live"]
    assert "workers/n-0.json" in gone and not any(p.startswith(("slots/m/", "proxies/b/", "proxies/c/",
                                                                 "proxies/d/", "workers/m-0")) for p in gone)
    report = survey_all(str(folder))
    assert [w["worker"] for w in report["workers"]] == ["m-0"] and report["slots"] == {"m": {"live": 1, "stale": 0}}
    assert report["kinds"]["proxies"]["resources"] == 3 and "broker.json" in files(folder)


def test_clean_leases_after_a_hard_kill_frees_the_slots_and_the_proxies(folder):
    """The point of the command: a relaunch right after a kill gets slot 0 and claims the proxies at once."""
    assert Broker(str(folder), machine="m").worker == "m-1"             # without it: a new slot ...
    assert not Broker(str(folder), worker="x-0").claim("proxies", "b")  # ... and the proxy held for 3 minutes
    clean(str(folder), leases=True, confirm=lambda live: True)
    left = files(folder)
    assert not any(p.startswith(("workers/", "slots/")) or "/leases/" in p for p in left)
    assert {p.split("/marks/")[0] for p in left if "/marks/" in p} == {"proxies/c", "proxies/d"}   # blocks stay
    relaunch = Broker(str(folder), machine="m")
    assert relaunch.worker == "m-0" and relaunch.claim("proxies", "b")


def test_clean_marks_removes_the_live_marks(folder):
    clean(str(folder), marks=True)
    assert not any("/marks/" in p for p in files(folder))
    assert any(p.startswith("proxies/b/leases/") for p in files(folder))    # live leases stay


def test_clean_dry_run_and_a_refused_confirmation_remove_nothing(folder):
    before = files(folder)
    result = clean(str(folder), leases=True, marks=True, dry_run=True)
    assert files(folder) == before and len(result["live"]) == 5        # heartbeat, slot, lease, 2 marks
    asked = []
    result = clean(str(folder), leases=True, confirm=lambda live: asked.append(live) or False)
    assert result["aborted"] and files(folder) == before
    assert {f["path"].split("/")[0] for f in asked[0]} == {"workers", "slots", "proxies"}


def test_clean_and_purge_refuse_a_folder_that_is_not_a_broker(tmp_path):
    (tmp_path / "data" / "leases").mkdir(parents=True)
    (tmp_path / "data" / "leases" / "20261109T101500123Z-x.json").write_text("{}")
    with pytest.raises(LinecasterError, match="not a broker"):
        clean(str(tmp_path))
    with pytest.raises(LinecasterError, match="does not look like a broker"):
        purge(str(tmp_path))
    assert len(files(tmp_path)) == 1


def test_purge_empties_the_folder_and_a_new_broker_starts_on_it(folder):
    (folder / "notes.txt").write_text("not the broker's")
    before = files(folder)
    result = purge(str(folder), dry_run=True)
    assert files(folder) == before and result["live_workers"] == 1 and result["live_marks"] == 2
    assert purge(str(folder), confirm=lambda r: False)["aborted"] and files(folder) == before
    result = purge(str(folder))
    assert files(folder) == {"notes.txt"} and len(result["removed"]["broker.json"]) == 1
    assert [p.name for p in folder.iterdir()] == ["notes.txt"]         # its folders too
    fresh = Broker(str(folder), machine="m")
    assert fresh.worker == "m-0" and fresh.claim("proxies", "b") and (folder / "broker.json").exists()


# ---------------------------------------------------------------------- the command


@pytest.fixture
def no_terminal(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


def test_cli_status(folder, capsys):
    cli.main(["broker", "status", str(folder)])
    out = capsys.readouterr().out
    assert "workers: 1 live, 1 stale" in out and "slots: 1 live, 1 stale" in out and "example.org" in out
    assert "proxies: 4 known" in out
    cli.main(["broker", "status", str(folder), "--json"])
    assert json.loads(capsys.readouterr().out)["kinds"]["proxies"]["free"] == 2


def test_cli_clean(folder, capsys, no_terminal):
    cli.main(["broker", "clean", str(folder)])                          # nothing live: no question
    assert "removed: 1 heartbeats, 1 slots, 1 leases, 1 marks" in capsys.readouterr().out
    before = files(folder)
    with pytest.raises(SystemExit) as e:
        cli.main(["broker", "clean", str(folder), "--leases"])
    assert e.value.code == 1 and files(folder) == before
    assert "refused" in capsys.readouterr().err
    cli.main(["broker", "clean", str(folder), "--leases", "--dry-run"])
    assert "would remove workers/m-0.json (live)" in capsys.readouterr().out and files(folder) == before
    cli.main(["broker", "clean", str(folder), "--leases", "--yes"])
    assert not any("/leases/" in p for p in files(folder))


def test_cli_clean_asks_on_a_terminal(folder, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda question: "y")
    cli.main(["broker", "clean", str(folder), "--leases"])
    assert not any(p.startswith("workers/") for p in files(folder))


def test_cli_purge(folder, tmp_path_factory, capsys, no_terminal):
    before = files(folder)
    with pytest.raises(SystemExit) as e:
        cli.main(["broker", "purge", str(folder)])
    assert e.value.code == 1 and files(folder) == before
    assert "live: 1 workers, 2 marks" in capsys.readouterr().err
    cli.main(["broker", "purge", str(folder), "--dry-run"])
    assert files(folder) == before
    cli.main(["broker", "purge", str(folder), "--yes"])
    assert files(folder) == set()
    other = tmp_path_factory.mktemp("other")
    (other / "keep.txt").write_text("x")
    with pytest.raises(SystemExit) as e:
        cli.main(["broker", "purge", str(other), "--yes"])
    assert e.value.code == 1 and files(other) == {"keep.txt"}
