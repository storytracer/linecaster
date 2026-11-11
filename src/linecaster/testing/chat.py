"""A fake OpenAI-compatible chat server on loopback, for tests of the ``Chat`` backend and the chat recognizers."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def completion(content: str | None, finish: str | None = "stop", usage: dict | None = None) -> dict:
    """Returns a ``/chat/completions`` response body with one choice.

    Args:
        content: the message's content (``None``: none).
        finish: the choice's ``finish_reason``.
        usage: the response's ``usage``; ``None``: 10 prompt and 3 completion tokens.
    """
    return {"id": "fake", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3} if usage is None else usage}


@dataclass
class FakeChatServer:
    """A running fake chat server, as ``fake_chat_server`` yields it.

    Args:
        url: its base URL, ``http://127.0.0.1:<port>/v1``.
        requests: the bodies of the requests it answered, in order.
    """

    url: str
    requests: list[dict] = field(default_factory=list)


@contextmanager
def fake_chat_server(answer: Callable[[dict], str | dict] | None = None,
                     models: list[dict] | None = None) -> Iterator[FakeChatServer]:
    """Runs an OpenAI-compatible chat server on loopback that answers ``/v1/chat/completions`` from a function.

    ``answer`` gets each request's body and returns the content of the completion (a string, wrapped by
    ``completion``) or the whole response body (a dict). With ``models``, ``GET /v1/models`` lists them (as vLLM
    does, e.g. ``{"id": "m", "max_model_len": 18000}``). Other routes answer 404 (saturate's gauge probe then runs
    blind). The server binds ``127.0.0.1`` on a free port and stops when the block ends.

    Args:
        answer: the function that answers; ``None``: every request is answered ``"text"``.
        models: the entries of ``GET /v1/models``; ``None``: that route answers 404 too.

    Example:
        from linecaster.backends import Chat
        from linecaster.blocks.recognition import PageRecognizer

        with fake_chat_server(lambda body: "a page") as server:
            pages = list(PageRecognizer(Chat("lightonocr-2-1b", server.url)).run(iter(docs)))
    """
    reply = answer or (lambda body: "text")
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802 - saturate's engine probe: no gauges here (blind mode)
            if models is not None and self.path == "/v1/models":
                data = json.dumps({"object": "list", "data": models}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path != "/v1/chat/completions":
                self.send_response(404)
                self.end_headers()
                return
            requests.append(body)
            out = reply(body)
            data = json.dumps(out if isinstance(out, dict) else completion(out)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield FakeChatServer(f"http://127.0.0.1:{server.server_address[1]}/v1", requests)
    finally:
        server.shutdown()
        server.server_close()
