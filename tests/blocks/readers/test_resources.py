"""Resources (``linecaster.blocks.readers.resources``, ``linecaster.blocks.writers.resources``, ``linecaster.net.policy``):
items' remote files fetched as served, one item per task, from URL templates or a resource table; each response
checked (XML, JSON, an image; an HTML page where another format was expected fails); copies at
``<kind>/<item>/<name>.<ext>`` with a record each; copies already there read back; host policies per host, with
``stop_on`` statuses that stop the run without a retry."""
import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

pytest.importorskip("pybookget")

from linecaster.blocks.readers.resources import ResourceReader, check, expected_format  # noqa: E402
from linecaster.blocks.writers.resources import ResourceFilesWriter, ResourceRecordWriter  # noqa: E402
from linecaster.errors import PipelineConfigError, ServerError  # noqa: E402
from linecaster.net.policy import HTTPPolicy  # noqa: E402
from linecaster.net.http import close_shared  # noqa: E402

FAST = {"retry_wait_min": 0, "retry_wait_max": 0, "max_retries": 2, "trust_env": False}
XML = b'<?xml version="1.0"?><record xmlns="http://www.loc.gov/MARC21/slim"><leader>x</leader></record>'


@pytest.fixture(autouse=True)
def fresh_fetchers():
    close_shared()
    yield
    close_shared()


@pytest.fixture
def server():
    """``/marc/<id>``: MARCXML (``bad``: an HTML page, ``blocked``: 429); ``/json/<id>``: JSON; requests counted."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append(self.path)
            kind, _, item = self.path.strip("/").partition("/")
            if item == "blocked":
                self.send_response(429)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if kind == "marc" and item != "bad":
                body, ctype = XML, "application/xml;charset=UTF-8"
            elif kind == "json":
                body, ctype = json.dumps({"item": item}).encode(), "application/json"
            else:
                body, ctype = b"<!DOCTYPE html><html><title>Just a moment...</title></html>", "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", f'"{item}"')
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{httpd.server_address[1]}", "seen": seen}
    httpd.shutdown()


def items_table(tmp_path, items):
    (tmp_path / "items").mkdir()
    pq.write_table(pa.table({"lccn": items, "page": list(range(len(items)))}), tmp_path / "items" / "p.parquet")
    return str(tmp_path / "items")


def run_all(reader, out, tasks=None):
    tasks = tasks or reader.auto_tasks()
    docs = []
    for rank in range(tasks):
        files, records = ResourceFilesWriter(str(out)), ResourceRecordWriter(str(out / "resources"))
        docs += list(records.run(files.run(reader.run(rank=rank, world_size=tasks), rank, tasks), rank, tasks))
    return docs


def records(out):
    return [json.loads(line) for p in sorted((out / "resources").iterdir()) for line in gzip.open(p, "rt")]


def test_templates_fetch_each_items_files_one_item_per_task(server, tmp_path):
    out = tmp_path / "out"
    reader = ResourceReader(items_table(tmp_path, ["a1", "a1", "b2", "c3"]), item_key="lccn", http=FAST,
                            templates={"marcxml": server["base"] + "/marc/{item}",
                                       "item-json": server["base"] + "/json/{item}"})
    assert reader.auto_tasks() == 3 and [reader.task_pages(r, 3) for r in range(3)] == [2, 2, 2]
    docs = run_all(reader, out)
    assert len(docs) == 6 and not any(d.metadata.get("errors") for d in docs)
    assert (out / "marcxml" / "a1" / "a1.xml").read_bytes() == XML
    assert json.loads((out / "item-json" / "b2" / "b2.json").read_text()) == {"item": "b2"}
    rec = next(r for r in records(out) if r["item"] == "c3" and r["kind"] == "marcxml")
    assert rec["source_uri"] == server["base"] + "/marc/c3" and rec["status"] == 200 and rec["etag"] == '"c3"'
    assert rec["uri"] == str(out / "marcxml" / "c3" / "c3.xml") and len(rec["sha256"]) == 64 and not rec["reused"]


def test_an_html_page_where_xml_was_expected_is_the_items_error(server, tmp_path):
    out = tmp_path / "out"
    reader = ResourceReader(items_table(tmp_path, ["bad"]), item_key="lccn", http=FAST,
                            templates={"marcxml": server["base"] + "/marc/{item}"})
    reader.max_page_errors = None
    (doc,) = run_all(reader, out)
    assert doc.metadata["errors"][0]["error"].startswith("html: an HTML page")
    assert not (out / "marcxml").exists()                              # no copy of an error page
    assert records(out)[0]["error"].startswith("ValueError: html")


def test_a_resource_table_names_its_resources(server, tmp_path):
    (tmp_path / "res").mkdir()
    pq.write_table(pa.table({"book": ["x", "x", "x"], "kind": ["marcxml", "item-json", "item-json"],
                             "url": [server["base"] + "/marc/x", server["base"] + "/json/x1",
                                     server["base"] + "/json/x2"]}), tmp_path / "res" / "r.parquet")
    out = tmp_path / "out"
    docs = run_all(ResourceReader(str(tmp_path / "res"), item_key="book", http=FAST), out)
    assert len(docs) == 3
    assert sorted(p.name for p in (out / "item-json" / "x").iterdir()) == ["x1.json", "x2.json"]  # the URL's name
    assert (out / "marcxml" / "x" / "x.xml").exists()


def test_copies_already_there_are_read_back_instead_of_fetched(server, tmp_path):
    out = tmp_path / "out"
    (out / "marcxml" / "a1").mkdir(parents=True)
    (out / "marcxml" / "a1" / "a1.xml").write_bytes(XML)
    reader = ResourceReader(items_table(tmp_path, ["a1"]), item_key="lccn", http=FAST, reuse_folder=str(out),
                            templates={"marcxml": server["base"] + "/marc/{item}",
                                       "item-json": server["base"] + "/json/{item}"})
    docs = run_all(reader, out)
    assert server["seen"] == ["/json/a1"]                              # only the missing one
    reused = next(r for r in records(out) if r["kind"] == "marcxml")
    assert reused["reused"] and reused["sha256"] and reused["uri"].endswith("marcxml/a1/a1.xml")
    assert len(docs) == 2


def policy_file(tmp_path, text):
    path = tmp_path / "http-policy.yaml"
    path.write_text(text)
    return str(path)


def test_a_status_in_stop_on_stops_the_run_without_a_retry(server, tmp_path):
    hosts = policy_file(tmp_path, "hosts:\n  127.0.0.1: {stop_on: [429], rate_limits: ['600/60']}\n")
    reader = ResourceReader(items_table(tmp_path, ["blocked"]), item_key="lccn", http=FAST, http_policy=hosts,
                            templates={"marcxml": server["base"] + "/marc/{item}"})
    with pytest.raises(ServerError, match="HTTP 429"):
        run_all(reader, tmp_path / "out")
    assert server["seen"] == ["/marc/blocked"]                         # not retried


def test_stop_on_html_stops_the_run_on_a_captcha_page(server, tmp_path):
    hosts = policy_file(tmp_path, "hosts:\n  127.0.0.1: {stop_on: [html]}\n")
    reader = ResourceReader(items_table(tmp_path, ["bad"]), item_key="lccn", http=FAST, http_policy=hosts,
                            templates={"marcxml": server["base"] + "/marc/{item}"})
    with pytest.raises(ServerError, match="stop_on: html"):
        run_all(reader, tmp_path / "out")


def test_the_http_policy_root_then_the_runs_options_then_the_hosts_entry(tmp_path):
    policy = HTTPPolicy(policy_file(tmp_path, """
rate_limits: ["60/60"]
max_retries: 7
proxies: root.txt
proxy_blocks: s3://b/proxy-blocks
stop_on: [429]
hosts:
  tile.loc.gov: {rate_limits: ["150/60", "3/1"], proxies: p.txt}
  lccn.loc.gov: {rate_limits: ["25/60"], direct: true, max_retries: 0, stop_on: [html]}
"""), base={"proxy_file": "run.txt", "user_agent": "HF-Research/1.0"})
    tile = policy.http_for("https://tile.loc.gov/storage-services/x.jp2")
    lccn = policy.http_for("https://lccn.loc.gov/02011712/marcxml")
    other = policy.http_for("https://example.org/x")
    assert tile["rate_limits"] == [(150, 60.0), (3, 1.0)] and tile["proxy_file"] == "p.txt"   # the host's entry wins
    assert other["rate_limits"] == [(60, 60.0)] and other["proxy_file"] == "run.txt"         # the run's over the root
    assert other["max_retries"] == tile["max_retries"] == 7 and lccn["max_retries"] == 0
    assert all(c["proxy_blocks"] == "s3://b/proxy-blocks" for c in (tile, lccn, other))
    assert lccn["rate_limits"] == [(25, 60.0)] and "proxy_file" not in lccn and lccn["trust_env"] is False
    assert other["stop_on"] == [429] and lccn["stop_on"] == []                # an entry replaces the root's field
    assert policy.stops_on_html("https://lccn.loc.gov/x") and not policy.stops_on_html("https://example.org/x")
    assert all(c["user_agent"] == "HF-Research/1.0" for c in (tile, lccn, other))
    assert "lccn.loc.gov: 25/60, direct, 0 retries, stops on html" in policy.describe()
    assert "other hosts: 60/60, through proxies, 7 retries, stops on 429" in policy.describe()
    assert policy.rate_limited()


def test_the_http_policy_root_alone_and_its_checks(tmp_path):
    policy = HTTPPolicy(policy_file(tmp_path, "max_retries: 2\nattempt_timeout: 60\n"), base={"max_retries": 4})
    assert policy.http_for("https://a.org/x") == {"max_retries": 4, "attempt_timeout": 60}   # the run's option wins
    assert policy.describe() == "every host: no rate limit, 2 retries" and not policy.rate_limited()
    with pytest.raises(PipelineConfigError, match="unknown speed"):
        HTTPPolicy(policy_file(tmp_path, "hosts:\n  a.org: {speed: 3}\n"))
    with pytest.raises(PipelineConfigError, match="unknown proxy_blocks"):        # a folder for the whole run
        HTTPPolicy(policy_file(tmp_path, "hosts:\n  a.org: {proxy_blocks: x}\n"))
    with pytest.raises(PipelineConfigError, match="`default:` is gone"):
        HTTPPolicy(policy_file(tmp_path, "default: {rate_limits: [\"60/60\"]}\n"))
    with pytest.raises(PipelineConfigError, match="max_retries is a whole number"):
        HTTPPolicy(policy_file(tmp_path, "max_retries: many\n"))


@pytest.mark.parametrize("data, ctype, expected, problem", [
    (XML, "application/xml", "xml", None),
    (b"<html><body>busy</body></html>", "text/html", "xml", "html"),
    (b"{oops", "application/json", "json", "not json"),
    (b"", "application/xml", None, "not xml"),
])
def test_check(data, ctype, expected, problem):
    result = check(data, ctype, expected)
    assert result is None if problem is None else result.startswith(problem)
    assert expected_format("marcxml", "https://lccn.loc.gov/1/marcxml") == "xml"
    assert expected_format("item-json", "https://www.loc.gov/item/1/?fo=json") == "json"


def test_the_command_line_builds_the_resource_harvest(tmp_path):
    from linecaster.runtime import run

    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(["--items", items_table(tmp_path, ["a1", "b2"]), "OUT", "--item-key", "lccn",
                                     "--resource", "marcxml=https://lccn.loc.gov/{item}/marcxml",
                                     "--max-items", "1"]))
    a.has_engines = False
    reader = run.reader(a, reuse_folder="OUT")
    assert isinstance(reader, ResourceReader) and reader.templates == {"marcxml": "https://lccn.loc.gov/{item}/marcxml"}
    run.allocate(a, [reader])
    assert a.tasks == 1                                                # --max-items 1: one item, one task
    for argv in (["--items", "t", "OUT"], ["--items", "t", "OUT", "--item-key", "x", "--resource", "m=no-item"]):
        with pytest.raises(SystemExit):
            run.check(ap, ap.parse_args(argv))


def test_the_harvest_pipeline_runs_through_the_builder_and_counts_files(server, tmp_path, capsys):
    from linecaster.runtime.builder import build
    from linecaster.runtime.console import Progress
    from linecaster.runtime.local import LocalExecutor

    out = tmp_path / "out"
    reader = ResourceReader(items_table(tmp_path, ["a1", "bad", "c3"]), item_key="lccn", http=FAST,
                            reuse_folder=str(out), templates={"marcxml": server["base"] + "/marc/{item}"})
    reader.max_page_errors = None
    plan = build([reader, ResourceFilesWriter(str(out)), ResourceRecordWriter(str(out / "resources"))],
                 tasks=3, run_folder=str(out), observers=[Progress()])
    assert [type(b).__name__ for b in plan.stages[0].blocks] == [
        "ResourceReader", "RejectWriter", "ResourceFilesWriter", "ResourceRecordWriter"]
    LocalExecutor(plan.stages[0].pipeline, tasks=3, workers=1, logging_dir=str(out / "logs"), out=str(out),
                  reader=reader, title="harvest").run()
    err = capsys.readouterr().err
    assert "3 files in 3 tasks, 1 worker" in err and "harvest done: 3 files (1 failed)" in err
    assert "task 1/3 done: 1 files" in err and "file bad/marcxml/bad failed in ResourceReader" in err
    assert sorted(p.name for p in (out / "marcxml").iterdir()) == ["a1", "c3"]
    rejected = [json.loads(line) for p in (out / "rejects").iterdir() for line in p.open()]
    assert [(r["key"], r["field"]) for r in rejected] == [("bad/marcxml/bad", "resource")]


def fake_proxy(body: bytes, ctype: str, status: int = 200):
    """An 'http proxy' answering every absolute-URI request itself with ``status`` and ``body``; requests counted."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append(self.path)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, seen


def test_an_html_page_through_a_proxy_blocks_that_proxy_for_its_hosts_ttl(tmp_path):
    """One proxy sends a block page (HTML), the other the records: every record arrives, the blocking proxy is left
    out for the host's blacklist_ttl (72 h), and the breaker does not pause."""
    blocking, blocked_seen = fake_proxy(b"<!DOCTYPE html><html><title>No Connections Available</title></html>",
                                        "text/html;charset=UTF-8")
    good, good_seen = fake_proxy(XML, "application/xml")
    try:
        (tmp_path / "proxies.txt").write_text(
            f"127.0.0.1:{blocking.server_address[1]}\n127.0.0.1:{good.server_address[1]}\n")
        hosts = policy_file(tmp_path, f"hosts:\n  catalog.test: {{proxies: {tmp_path / 'proxies.txt'}, "
                                     "blacklist_ttl: 72h}\n")
        out = tmp_path / "out"
        reader = ResourceReader(items_table(tmp_path, ["a1", "b2", "c3"]), item_key="lccn", http=FAST, http_policy=hosts,
                                templates={"marcxml": "http://catalog.test/{item}/marcxml"})
        docs = run_all(reader, out)
        assert not any(d.metadata.get("errors") for d in docs) and len(docs) == 3
        assert sorted(p.name for p in (out / "marcxml").iterdir()) == ["a1", "b2", "c3"]
        assert len(blocked_seen) == 1 and len(good_seen) == 3       # blocked once, then left out
        fetcher = reader._last
        ttl = [p["ttl_remaining_seconds"] for pool in fetcher._proxies.blacklist_snapshot().values() for p in pool
               if p["ttl_remaining_seconds"] is not None]
        assert len(ttl) == 1 and 72 * 3600 - 60 < ttl[0] <= 72 * 3600
        assert not fetcher.breaker.paused
    finally:
        blocking.shutdown()
        good.shutdown()


def test_blacklist_settings_per_host(tmp_path):
    from linecaster.net.policy import seconds

    hosts = HTTPPolicy(policy_file(tmp_path, "hosts:\n  lccn.loc.gov: {proxies: p.txt, blacklist_ttl: 72h, "
                                              "blacklist_threshold: 2}\n"))
    config = hosts.http_for("https://lccn.loc.gov/1/marcxml")
    assert config["proxy_blacklist_ttl"] == 259200 and config["proxy_blacklist_threshold"] == 2
    assert (seconds("30m", "x"), seconds(45, "x"), seconds("3d", "x")) == (1800, 45, 259200)
    with pytest.raises(PipelineConfigError, match="duration"):
        HTTPPolicy(policy_file(tmp_path, "hosts:\n  a.org: {blacklist_ttl: soon}\n"))


def test_a_status_in_blacklist_on_leaves_its_proxy_out_and_goes_on_through_the_next(tmp_path):
    """A host's blacklist_on: [403]: the proxy that got the 403 is left out and the items come through the other."""
    refusing, refused_seen = fake_proxy(b"<html>Forbidden</html>", "text/html", status=403)
    good, good_seen = fake_proxy(XML, "application/xml")
    try:
        (tmp_path / "proxies.txt").write_text(
            f"127.0.0.1:{refusing.server_address[1]}\n127.0.0.1:{good.server_address[1]}\n")
        hosts = policy_file(tmp_path, f"hosts:\n  catalog.test: {{proxies: {tmp_path / 'proxies.txt'}, "
                                     "blacklist_on: [403]}\n")
        out = tmp_path / "out"
        reader = ResourceReader(items_table(tmp_path, ["a1", "b2", "c3"]), item_key="lccn", http=FAST, http_policy=hosts,
                                templates={"marcxml": "http://catalog.test/{item}/marcxml"})
        docs = run_all(reader, out)
        assert not any(d.metadata.get("errors") for d in docs) and len(docs) == 3
        assert len(refused_seen) == 1 and len(good_seen) == 3
        assert reader._last.proxies_in_rotation() == (1, 2)
    finally:
        refusing.shutdown()
        good.shutdown()


def test_blacklist_on_in_a_hosts_file(tmp_path):
    hosts = HTTPPolicy(policy_file(tmp_path, "hosts:\n  www.loc.gov: {proxies: p.txt, blacklist_on: [403, 451]}\n"))
    assert hosts.http_for("https://www.loc.gov/item/1/")["proxy_blacklist_on"] == [403, 451]
    plain = HTTPPolicy(policy_file(tmp_path, "hosts:\n  a.org: {}\n"))
    assert "proxy_blacklist_on" not in plain.http_for("https://a.org/")
    with pytest.raises(PipelineConfigError, match="error statuses"):
        HTTPPolicy(policy_file(tmp_path, "hosts:\n  a.org: {blacklist_on: [200]}\n"))
    with pytest.raises(PipelineConfigError, match="403 both in stop_on and blacklist_on"):
        HTTPPolicy(policy_file(tmp_path, "hosts:\n  a.org: {blacklist_on: [403], stop_on: [403]}\n"))


def _markers(folder, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = sorted(folder.rglob("*.json")) if folder.exists() else []
        if found:
            return found
        time.sleep(0.05)
    return []


def test_a_proxy_block_is_marked_and_honoured_after_a_restart(tmp_path):
    """The proxy that sent a block page is marked in the proxy-blocks folder; a fresh fetcher (another worker, or the
    run started again) leaves it out from its first request."""
    blocking, blocked_seen = fake_proxy(b"<!DOCTYPE html><html>blocked</html>", "text/html")
    good, good_seen = fake_proxy(XML, "application/xml")
    try:
        (tmp_path / "proxies.txt").write_text(
            f"127.0.0.1:{blocking.server_address[1]}\n127.0.0.1:{good.server_address[1]}\n")
        hosts = policy_file(tmp_path, f"hosts:\n  catalog.test: {{proxies: {tmp_path / 'proxies.txt'}, "
                                     "blacklist_ttl: 72h}\n")
        blocks = tmp_path / "proxy-blocks"
        http = {**FAST, "proxy_blocks": str(blocks)}
        template = {"marcxml": "http://catalog.test/{item}/marcxml"}
        run_all(ResourceReader(items_table(tmp_path, ["a1", "b2", "c3"]), item_key="lccn", http=http, http_policy=hosts,
                               templates=template), tmp_path / "out")
        assert len(blocked_seen) == 1
        (marker,) = _markers(blocks)
        assert marker.parent.parent.name == "catalog.test" and json.loads(marker.read_text())["ttl"] > 71 * 3600
        close_shared()                                       # as a new process would start
        (tmp_path / "items").rename(tmp_path / "items-1")
        docs = run_all(ResourceReader(items_table(tmp_path, ["d4", "e5"]), item_key="lccn", http=http, http_policy=hosts,
                                      templates=template), tmp_path / "out")
        assert not any(d.metadata.get("errors") for d in docs)
        assert len(blocked_seen) == 1 and len(good_seen) == 5
    finally:
        blocking.shutdown()
        good.shutdown()


def test_every_proxy_marked_blocked_stops_the_run_at_its_first_request(tmp_path):
    from linecaster.net.proxy_blocks import ProxyBlocks

    proxies = ["127.0.0.1:9", "127.0.0.1:10"]
    (tmp_path / "proxies.txt").write_text("\n".join(proxies) + "\n")
    elsewhere = ProxyBlocks(str(tmp_path / "proxy-blocks"))
    for p in proxies:
        elsewhere.write("catalog.test", f"http://{p}", 72 * 3600)
    hosts = policy_file(tmp_path, f"hosts:\n  catalog.test: {{proxies: {tmp_path / 'proxies.txt'}}}\n")
    reader = ResourceReader(items_table(tmp_path, ["a1"]), item_key="lccn", http_policy=hosts,
                            http={**FAST, "proxy_blocks": str(tmp_path / "proxy-blocks")},
                            templates={"marcxml": "http://catalog.test/{item}/marcxml"})
    with pytest.raises(ServerError, match=r"no proxy left for catalog\.test.*first returns in 7[12] h"):
        run_all(reader, tmp_path / "out")


def test_the_http_policy_option(tmp_path):
    from linecaster.runtime import run

    policy = policy_file(tmp_path, 'max_retries: 3\nhosts:\n  lccn.loc.gov: {rate_limits: ["25/60"]}\n')
    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(["--items", items_table(tmp_path, ["a1", "b2"]), "--item-key", "lccn", "OUT",
                                     "--resource", "marcxml=https://lccn.loc.gov/{item}/marcxml",
                                     "--http-policy", policy]))
    a.has_engines = False
    reader = run.reader(a)
    assert reader.http_policy == policy and reader.http["default_proxy_blocks"] == "OUT/logs/proxy-blocks"
    run.allocate(a, [reader])
    assert a.workers == 1                                  # the file sets rate limits, which hold per worker
    assert run.rate_note(a) == "HTTP policy per worker: lccn.loc.gov: 25/60, 3 retries; other hosts: no rate limit, " \
                               "3 retries"
    with pytest.raises(SystemExit):
        run.check(ap, ap.parse_args(["--items", "d", "--item-key", "lccn", "OUT", "--resource", "m=u/{item}",
                                     "--http-policy", policy_file(tmp_path, "default: {}\n")]))


def test_blocks_do_not_use_up_attempts(tmp_path):
    """max_retries 0 (a single attempt): three proxies send block pages, and the item still comes through the fourth."""
    blocking = [fake_proxy(b"<!DOCTYPE html><html>blocked</html>", "text/html") for _ in range(3)]
    good, good_seen = fake_proxy(XML, "application/xml")
    try:
        (tmp_path / "proxies.txt").write_text(
            "".join(f"127.0.0.1:{s.server_address[1]}\n" for s, _ in blocking) + f"127.0.0.1:{good.server_address[1]}\n")
        hosts = policy_file(tmp_path, f"proxies: {tmp_path / 'proxies.txt'}\nmax_retries: 0\n")
        reader = ResourceReader(items_table(tmp_path, ["a1"]), item_key="lccn", http=FAST, http_policy=hosts,
                                templates={"marcxml": "http://catalog.test/{item}/marcxml"})
        (doc,) = run_all(reader, tmp_path / "out")
        assert not doc.metadata.get("errors") and len(good_seen) == 1
        assert [len(seen) for _, seen in blocking] == [1, 1, 1] and reader._last.proxies_in_rotation() == (1, 4)
    finally:
        for s, _ in blocking:
            s.shutdown()
        good.shutdown()


def test_a_timeout_through_a_proxy_leaves_it_in_rotation(tmp_path):
    """A slow answer (past the deadline) is the server's, not the proxy's: retried, and the proxy stays in."""
    import time

    seen = []

    class Slow(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append(self.path)
            if len(seen) == 1:
                time.sleep(1.5)                              # past the 0.3 s deadline: the attempt is cut
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(XML)))
            self.end_headers()
            self.wfile.write(XML)

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        (tmp_path / "proxies.txt").write_text(f"127.0.0.1:{proxy.server_address[1]}\n")
        reader = ResourceReader(items_table(tmp_path, ["a1"]), item_key="lccn",
                                templates={"marcxml": "http://catalog.test/{item}/marcxml"},
                                http={**FAST, "proxy_file": str(tmp_path / "proxies.txt"), "attempt_timeout": 0.3,
                                      "attempt_min_rate": None})
        (doc,) = run_all(reader, tmp_path / "out")
        assert not doc.metadata.get("errors") and len(seen) == 2
        assert reader._last.proxies_in_rotation() == (1, 1)
    finally:
        proxy.shutdown()


def test_a_harvest_on_ray_runs_on_cpus(tmp_path):
    """A pipeline without engines (pipelines/harvest.py) gets datatrove's RayPipelineExecutor, no GPU per task."""
    pytest.importorskip("ray")
    from linecaster.blocks.writers.rejects import RejectWriter
    from linecaster.runtime import run

    ap = run.parser(None)
    out = str(tmp_path / "out")
    a = run.check(ap, ap.parse_args(["--items", items_table(tmp_path, ["a1", "b2"]), "--item-key", "lccn", out,
                                     "--resource", "json=https://www.loc.gov/item/{item}/?fo=json", "--on", "ray",
                                     "--tasks", "2", "--cpus-per-task", "1", "--mem-per-cpu-gb", "2"]))
    a.has_engines = False
    blocks = [run.reader(a), RejectWriter(f"{out}/rejects"), ResourceFilesWriter(out),
              ResourceRecordWriter(f"{out}/resources")]
    executor = run._executors(a, run.build_plan(a, blocks), out, None, ["linecaster"])
    assert type(executor).__name__ == "RayPipelineExecutor" and executor.gpus_per_task == 0
    assert (executor.cpus_per_task, executor.workers, run.executor_name(a)) == (1, 2, "RayPipelineExecutor")
