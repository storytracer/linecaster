"""Resources (``linecaster.blocks.readers.resources``, ``linecaster.blocks.writers.resources``, ``linecaster.net.hosts``):
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
from linecaster.net.hosts import HostPolicies  # noqa: E402
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


def hosts_file(tmp_path, text):
    path = tmp_path / "hosts.yaml"
    path.write_text(text)
    return str(path)


def test_a_status_in_stop_on_stops_the_run_without_a_retry(server, tmp_path):
    hosts = hosts_file(tmp_path, "hosts:\n  127.0.0.1: {stop_on: [429], rate_limits: ['600/60']}\n")
    reader = ResourceReader(items_table(tmp_path, ["blocked"]), item_key="lccn", http=FAST, hosts=hosts,
                            templates={"marcxml": server["base"] + "/marc/{item}"})
    with pytest.raises(ServerError, match="HTTP 429"):
        run_all(reader, tmp_path / "out")
    assert server["seen"] == ["/marc/blocked"]                         # not retried


def test_stop_on_html_stops_the_run_on_a_captcha_page(server, tmp_path):
    hosts = hosts_file(tmp_path, "hosts:\n  127.0.0.1: {stop_on: [html]}\n")
    reader = ResourceReader(items_table(tmp_path, ["bad"]), item_key="lccn", http=FAST, hosts=hosts,
                            templates={"marcxml": server["base"] + "/marc/{item}"})
    with pytest.raises(ServerError, match="stop_on: html"):
        run_all(reader, tmp_path / "out")


def test_host_policies_lay_each_hosts_settings_over_the_runs(tmp_path):
    hosts = HostPolicies(hosts_file(tmp_path, """
hosts:
  tile.loc.gov: {rate_limits: ["150/60", "3/1"], proxies: p.txt}
  lccn.loc.gov: {rate_limits: ["25/60"], direct: true, stop_on: [429, html]}
default: {rate_limits: ["60/60"]}
"""), base={"proxy_file": "run.txt", "user_agent": "HF-Research/1.0"})
    tile = hosts.http_for("https://tile.loc.gov/storage-services/x.jp2")
    lccn = hosts.http_for("https://lccn.loc.gov/02011712/marcxml")
    other = hosts.http_for("https://example.org/x")
    assert tile["rate_limits"] == [(150, 60.0), (3, 1.0)] and tile["proxy_file"] == "p.txt"
    assert lccn["rate_limits"] == [(25, 60.0)] and "proxy_file" not in lccn and lccn["trust_env"] is False
    assert lccn["stop_on"] == [429] and hosts.stops_on_html("https://lccn.loc.gov/x")
    assert other["rate_limits"] == [(60, 60.0)] and other["proxy_file"] == "run.txt"
    assert all(c["user_agent"] == "HF-Research/1.0" for c in (tile, lccn, other))
    assert "lccn.loc.gov: 25/60, direct, stops on 429, html" in hosts.describe()
    with pytest.raises(PipelineConfigError, match="unknown"):
        HostPolicies(hosts_file(tmp_path, "hosts:\n  a.org: {speed: 3}\n"))


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
