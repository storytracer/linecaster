"""``Chat``: a chat preset's VLM behind an OpenAI-compatible server (vLLM, SGLang, a hosted endpoint), reached
through saturate on ``/chat/completions``."""
from __future__ import annotations

from typing import Any

from ..runtime.secrets import EnvVar
from .served import check_secrets, request_headers

#: the port ``ChatModelServer`` starts its server on by default; ``Chat`` without an endpoint asks there
CHAT_PORT = 8000


class Chat:
    """Runs a chat preset's VLM (engine ``chat.v1``) behind an OpenAI-compatible server, reached through saturate.

    The server is vLLM, SGLang or a hosted endpoint, on ``/chat/completions``. The preset's adapter
    (``linecaster.adapters``) builds each request and parses each completion; saturate keeps a window of requests
    in flight, adapted to the server's queue gauges and 429s. Secrets are read in the task, when the block's client
    opens (``warm_up()`` reads them first); a key given as text is refused (``PipelineConfigError``).

    Args:
        preset: the chat preset (``id``, ``id@edition``, or a model's Hugging Face id: its preset with unit
            ``prefer``) or a configured adapter (``linecaster.adapters.chat_model``).
        endpoint: the server's ``.../v1`` base URL; ``None``: the task's ``ChatModelServer`` on loopback port
            ``CHAT_PORT`` (8000).
        served_name: the name the server hosts the model under; ``None``: the preset's, else the Hub id.
        max_window: the most requests in flight.
        initial_window: the requests in flight at the start; saturate adapts the window between it and
            ``max_window``.
        read_timeout: seconds per request before it fails (the page's error).
        api_key: an ``EnvVar`` naming the key (never the key itself), sent as ``Authorization: Bearer <key>``;
            ``None``: no authorization header.
        headers: headers sent with every request, values plain or ``EnvVar``.
        prefer: the unit of the preset a Hugging Face id picks when the model has several: ``page`` or ``region``.

    Example:
        from linecaster.backends import Chat
        from linecaster.blocks.recognition import PageRecognizer

        PageRecognizer(Chat("lightonocr-2-1b@1", "http://127.0.0.1:8000/v1", max_window=48, initial_window=8))
    """

    served = True
    #: the engine of chat presets
    engine = "chat.v1"

    def __init__(self, preset, endpoint: str | None = None, served_name: str | None = None, max_window: int = 32,
                 initial_window: int = 4, read_timeout: float = 600.0, api_key: EnvVar | None = None,
                 headers: dict | None = None, prefer: str = "page"):
        from ..adapters import ChatAdapter, chat_model

        check_secrets("Chat", api_key, headers)
        if isinstance(preset, ChatAdapter):
            adapter = preset
            if served_name:
                adapter.served_name = served_name
        else:
            adapter = chat_model(preset, served_name=served_name, prefer=prefer)
        self.adapter = adapter
        self.endpoint = endpoint or f"http://127.0.0.1:{CHAT_PORT}/v1"
        self.max_window, self.initial_window, self.read_timeout = max_window, initial_window, read_timeout
        self.api_key, self.headers = api_key, headers

    @property
    def preset(self) -> str | None:
        """The preset edition (``id@edition``)."""
        return self.adapter.preset

    @property
    def preset_sha256(self) -> str | None:
        return self.adapter.preset_sha256

    @property
    def model(self) -> str:
        """The name the server hosts the model under (what each request names)."""
        return self.adapter.served_name

    def request_headers(self) -> dict[str, str]:
        """The headers every request carries, secrets read now (in the task)."""
        return request_headers(self.api_key, self.headers)

    def warm_up(self) -> None:
        """The secrets are read (a missing one fails the task before its first page); the client opens with the
        block's run."""
        self.request_headers()

    def describe(self) -> str:
        return f"served {self.endpoint} ({self.model})"

    def to_dict(self) -> dict[str, Any]:
        """The backend as the run record names it: the adapter (preset edition and its hash, model, revision, adapter
        class, served name), the endpoint, the window and timeout, and the secrets by name (``{"env": NAME}``)."""
        from ..blocks.base.block import plain

        out = {"backend": "chat", **self.adapter.to_dict(), "endpoint": self.endpoint, "max_window": self.max_window,
               "initial_window": self.initial_window, "read_timeout": self.read_timeout}
        for k in ("api_key", "headers"):
            if getattr(self, k) is not None:
                out[k] = getattr(self, k)
        return plain(out)

    def __repr__(self) -> str:
        return f"Chat({self.preset!r}, endpoint={self.endpoint!r})"
