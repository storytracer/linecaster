"""A fake HTTP service on loopback, for tests of engines that call a vendor's service and of ``ServiceServer``."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class FakeService:
    """A running fake service, as ``fake_service`` yields it.

    Args:
        url: its base URL, ``http://127.0.0.1:<port>``.
        requests: the requests it answered, in order: ``(method, path, body)``, the body as JSON for a JSON
            request, as its form fields for a multipart one (``{name: text, or (filename, bytes)}``), else ``None``.
    """

    url: str
    requests: list[tuple[str, str, object]] = field(default_factory=list)


def _form(data: bytes, content_type: str) -> dict:
    """A ``multipart/form-data`` body as ``{name: text, or (filename, bytes)}`` (a repeated name: a list)."""
    from email.parser import BytesParser
    from email.policy import HTTP

    msg = BytesParser(policy=HTTP).parsebytes(f"Content-Type: {content_type}\r\n\r\n".encode() + data)
    out: dict = {}
    for part in msg.iter_parts():
        name, filename = part.get_param("name", header="content-disposition"), part.get_filename()
        payload = part.get_payload(decode=True)
        value = (filename, payload) if filename else payload.decode()
        if name in out:
            out[name] = (out[name] if isinstance(out[name], list) else [out[name]]) + [value]
        else:
            out[name] = value
    return out


@contextmanager
def fake_service(routes: dict[str, Callable[[object], object]]) -> Iterator[FakeService]:
    """Runs an HTTP service on loopback that answers the routes it is given from functions.

    ``routes`` maps ``"METHOD /path"`` (``"GET /health"``, ``"POST /v1/parse/sync"``) to a function that gets the
    request's body (JSON, a multipart form as ``{name: text, or (filename, bytes)}``, or ``None``) and returns the
    answer: a dict (``200`` with it as JSON) or ``(status, dict)``. Any other route answers 404. The service binds
    ``127.0.0.1`` on a free port and stops when the block ends.

    Args:
        routes: ``"METHOD /path"`` -> the function that answers it.

    Example:
        with fake_service({"GET /health": lambda body: {}, "POST /parse": lambda body: {"text": "a page"}}) as s:
            engine = MyServiceEngine(endpoint=s.url)
    """
    requests: list[tuple[str, str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _answer(self, method: str) -> None:
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else b""
            kind = self.headers.get("Content-Type") or ""
            body = (json.loads(data) if data and "json" in kind else _form(data, kind) if "multipart" in kind
                    else None)
            fn = routes.get(f"{method} {self.path}")
            if fn is None:
                self.send_response(404)
                self.end_headers()
                return
            requests.append((method, self.path, body))
            out = fn(body)
            status, out = out if isinstance(out, tuple) else (200, out)
            payload = json.dumps(out).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802
            self._answer("GET")

        def do_POST(self):  # noqa: N802
            self._answer("POST")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield FakeService(f"http://127.0.0.1:{server.server_address[1]}", requests)
    finally:
        server.shutdown()
        server.server_close()
