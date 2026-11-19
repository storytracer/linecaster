"""Paged answers (``ResourceReader``'s ``follow``): a resource whose pages each name the next one (a search API's
HAL ``_links.next``, a cursor), fetched one page after the other and each kept as served; an answer that broke off
goes on from its copies, and starts again when the server's cursor has run out. And the two settings that make a
harvest polite to one small server: ``max_in_flight`` and ``retry_jitter`` (``linecaster.net``)."""
import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from linecaster.components.readers.resources import ResourceReader, next_url
from linecaster.components.writers.resources import ResourceFilesWriter, ResourceRecordWriter
from linecaster.errors import PipelineConfigError
from linecaster.net.http import HTTPConfig, HTTPFetcher, close_shared
from linecaster.net.policy import HTTPPolicy

FAST = {"retry_wait_min": 0, "retry_wait_max": 0, "max_retries": 1, "trust_env": False}
PAGES = 4


@pytest.fixture(autouse=True)
def fresh_fetchers():
    close_shared()
    yield
    close_shared()


@pytest.fixture
def api():
    """``/search?q=...``: the first of ``PAGES`` pages; each page names the next as ``_links.next.href``, a relative
    link with the cursor of this session (``state["session"]``: a link of another session is 404, a cursor that ran
    out). ``/loop``: a page that names itself. ``/text``: no JSON. ``/slow/<id>``: 0.3 s; requests at once counted."""
    state = {"seen": [], "session": 1, "now": 0, "most": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            with lock:
                state["seen"].append(self.path)
                state["now"] += 1
                state["most"] = max(state["most"], state["now"])
            try:
                status, body, ctype = 200, b"", "application/json"
                path = self.path
                if path.startswith("/search"):
                    page = 1
                elif path.startswith("/scroll/"):
                    _, _, session, page = path.split("/")
                    page = int(page)
                    if int(session) != state["session"]:
                        status, page = 404, 0
                elif path.startswith("/slow/"):
                    time.sleep(0.3)
                    body, page = b"{}", 0
                elif path == "/loop":
                    body, page = json.dumps({"_links": {"next": {"href": "/loop"}}}).encode(), 0
                else:
                    body, ctype, page = b"not json at all", "application/json", 0
                if page:
                    links = {"self": {"href": path}}
                    if page < PAGES:
                        links["next"] = {"href": f"/scroll/{state['session']}/{page + 1}"}
                    body = json.dumps({"page": page, "_embedded": {"items": [{"id": f"{page}-{i}"} for i in range(3)]},
                                       "_links": links}).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            finally:
                with lock:
                    state["now"] -= 1

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    state["base"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()


def table(tmp_path, rows):
    (tmp_path / "items").mkdir(exist_ok=True)
    pq.write_table(pa.table({"query": [r[0] for r in rows], "kind": [r[1] for r in rows], "url": [r[2] for r in rows],
                             "name": [r[0] for r in rows]}), tmp_path / "items" / "q.parquet")
    return str(tmp_path / "items")


def run_all(reader, out):
    docs = []
    for rank in range(reader.auto_tasks()):
        n = reader.auto_tasks()
        files, records = ResourceFilesWriter(str(out)), ResourceRecordWriter(str(out / "resources"))
        docs += list(records.run(files.run(reader.run(rank=rank, world_size=n), rank, n), rank, n))
    return docs


def records(out):
    return [json.loads(line) for p in sorted((out / "resources").iterdir()) for line in gzip.open(p, "rt")]


def search(api, tmp_path, **kw):
    return ResourceReader(table(tmp_path, [("books", "search", api["base"] + "/search?q=books&size=3")]),
                          item_key="query", name_key="name", follow={"search": "_links.next.href"}, http=FAST, **kw)


def test_a_paged_answer_is_followed_page_after_page_and_every_page_kept_as_served(api, tmp_path):
    out = tmp_path / "out"
    docs = run_all(search(api, tmp_path), out)
    assert api["seen"] == ["/search?q=books&size=3", "/scroll/1/2", "/scroll/1/3", "/scroll/1/4"]   # in order
    assert len(docs) == PAGES and not any(d.metadata.get("errors") for d in docs)
    files = sorted(p.name for p in (out / "search" / "books").iterdir())
    assert files == [f"books_{n:05d}.json" for n in range(1, PAGES + 1)]
    third = json.loads((out / "search" / "books" / "books_00003.json").read_text())
    assert third["page"] == 3 and third["_links"]["next"]["href"] == "/scroll/1/4"       # the body as served
    recs = sorted(records(out), key=lambda r: r["page"])
    assert [r["page"] for r in recs] == [1, 2, 3, 4] and "followed_from" not in recs[0]
    assert recs[2]["source_uri"] == api["base"] + "/scroll/1/3"                          # the relative link, joined
    assert recs[2]["followed_from"] == api["base"] + "/scroll/1/2" and recs[2]["status"] == 200 and recs[2]["fetched"]


def test_an_answer_that_broke_off_goes_on_from_its_copies(api, tmp_path):
    out = tmp_path / "out"
    run_all(search(api, tmp_path), out)
    for n in (3, 4):                                                   # as if it had stopped after page 2
        (out / "search" / "books" / f"books_{n:05d}.json").unlink()
    api["seen"].clear()
    docs = run_all(search(api, tmp_path, reuse_folder=str(out)), out)
    assert api["seen"] == ["/scroll/1/3", "/scroll/1/4"]               # pages 1 and 2 read back, the rest fetched
    assert [d.metadata["resource"]["reused"] for d in docs] == [True, True, False, False]
    assert len(list((out / "search" / "books").iterdir())) == PAGES


def test_when_the_cursor_has_run_out_the_answer_is_fetched_again_from_its_first_page(api, tmp_path):
    out = tmp_path / "out"
    run_all(search(api, tmp_path), out)
    (out / "search" / "books" / "books_00004.json").unlink()
    api["seen"].clear()
    api["session"] = 2                                                 # the server forgot the first cursor
    reader = search(api, tmp_path, reuse_folder=str(out))
    docs = run_all(reader, out)
    assert api["seen"][0] == "/scroll/1/4"                             # the link the copy named: gone
    assert api["seen"][-PAGES:] == ["/search?q=books&size=3", "/scroll/2/2", "/scroll/2/3", "/scroll/2/4"]
    fetched = [d for d in docs if not d.metadata.get("errors")][-PAGES:]
    assert [d.metadata["resource"]["page"] for d in fetched] == [1, 2, 3, 4]
    assert not any(d.metadata["resource"]["reused"] for d in fetched)
    last = json.loads((out / "search" / "books" / "books_00004.json").read_text())
    assert last["_links"]["self"]["href"] == "/scroll/2/4"             # the new session's pages replaced the old


@pytest.mark.parametrize("path, said", [("/loop", "names a page already fetched"), ("/text", "not json")])
def test_a_page_that_does_not_lead_on_fails_the_resource_there(api, tmp_path, path, said):
    out = tmp_path / "out"
    reader = ResourceReader(table(tmp_path, [("q", "search", api["base"] + path)]), item_key="query",
                            name_key="name", follow={"search": "_links.next.href"}, http=FAST)
    reader.max_page_errors = None
    docs = run_all(reader, out)
    errors = [e["error"] for d in docs for e in d.metadata.get("errors", [])]
    assert len(errors) == 1 and said in errors[0]
    assert len(api["seen"]) <= 2                                       # it does not go round and round


def test_next_url_reads_dotted_paths_and_joins_relative_links():
    page = json.dumps({"_links": {"next": {"href": "?cursor=abc"}}, "pages": [{"next": "https://b.example.org/2"}],
                       "end": None, "empty": "", "n": 3}).encode()
    assert next_url(page, "_links.next.href", "https://a.example.org/s?q=1") == "https://a.example.org/s?cursor=abc"
    assert next_url(page, "pages.0.next", "https://a.example.org/s") == "https://b.example.org/2"
    for nothing in ("_links.prev.href", "end", "empty", "pages.4.next", "n.x"):
        assert next_url(page, nothing, "https://a.example.org/s") is None
    with pytest.raises(ValueError, match="not a URL"):
        next_url(page, "n", "https://a.example.org/s")
    with pytest.raises(PipelineConfigError, match="JSON path"):
        ResourceReader("x", item_key="i", follow={"search": "."})


def test_max_in_flight_sends_one_request_after_the_other(api, tmp_path):
    (tmp_path / "items").mkdir()
    pq.write_table(pa.table({"id": ["a", "b"]}), tmp_path / "items" / "i.parquet")
    kinds = {k: api["base"] + "/slow/{item}-" + k for k in ("one", "two", "three")}

    def most(http):
        close_shared()
        api["most"] = 0
        reader = ResourceReader(str(tmp_path / "items"), item_key="id", templates=kinds, http={**FAST, **http})
        assert len(list(reader.run(rank=0, world_size=1))) == 6
        return api["most"]

    assert most({"rate_limits": [(50, 1)]}) > 1                        # the limits space the starts, no more
    assert most({"rate_limits": [(50, 1)], "max_in_flight": 1}) == 1
    assert HTTPFetcher(rate_limits=[(50, 1)], max_in_flight=2, trust_env=False).max_ahead == 2
    with pytest.raises(ValueError, match="at least 1"):
        HTTPConfig(max_in_flight=0)


def test_retry_jitter_lengthens_a_wait_by_a_random_share_and_never_shortens_it():
    fetcher = HTTPFetcher(retry_wait_min=2, retry_wait_max=60, retry_jitter=0.5, trust_env=False)
    waits = [fetcher._backoff(2, None) for _ in range(200)]
    assert all(4 <= w <= 6 for w in waits) and len({round(w, 3) for w in waits}) > 50
    plain = HTTPFetcher(retry_wait_min=2, retry_wait_max=60, trust_env=False)
    assert {plain._backoff(n, None) for n in (1, 2, 3)} == {2, 4, 8}   # none by default


def test_the_policy_takes_both_settings_per_host_and_says_them(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("retry_jitter: 0.5\nhosts:\n  catalog.example.org:\n    rate_limits: ['1/1']\n    max_in_flight: 1\n")
    policy = HTTPPolicy(str(path))
    here, elsewhere = policy.http_for("https://catalog.example.org/x"), policy.http_for("https://other.example.org/x")
    assert here["max_in_flight"] == 1 and here["retry_jitter"] == 0.5
    assert "max_in_flight" not in elsewhere and elsewhere["retry_jitter"] == 0.5
    assert "1 in flight at most" in policy.describe() and "50% longer at random" in policy.describe()
    for bad, said in (("max_in_flight: 0", "max_in_flight is a whole number"), ("retry_jitter: -1", "retry_jitter is")):
        path.write_text(bad + "\n")
        with pytest.raises(PipelineConfigError, match=said):
            HTTPPolicy(str(path))


def test_the_command_line_takes_follow():
    from linecaster.execution import run
    from linecaster.templates import harvest

    plan = run.describe(harvest, ["--items", "q.parquet", "--item-key", "query", "OUT", "--name-key", "name",
                                  "--follow", "search=_links.next.href"])
    reader = plan.stages[0].components[0]
    assert reader.follow == {"search": "_links.next.href"}
