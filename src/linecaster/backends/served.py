"""``Served``: the engine runs behind ``linecaster serve`` (or any server speaking its routes), reached
through saturate."""
from __future__ import annotations

from dataclasses import dataclass

from ..errors import PipelineConfigError
from ..runtime.secrets import EnvVar, resolve


def check_secrets(backend: str, api_key, headers) -> None:
    """A backend's ``api_key`` must be an ``EnvVar``, its ``headers`` strings or ``EnvVar``s."""
    if api_key is not None and not isinstance(api_key, EnvVar):
        raise PipelineConfigError(f"{backend}(api_key=...) takes EnvVar(NAME), not the key: a key in the pipeline "
                                  "would be pickled with it and recorded")
    for k, v in (headers or {}).items():
        if not isinstance(v, (str, EnvVar)):
            raise PipelineConfigError(f"{backend}(headers=...): {k} is {type(v).__name__}, not a string or an EnvVar")


def request_headers(api_key: EnvVar | None, headers: dict | None) -> dict[str, str]:
    """``headers`` with the secrets read now (in the task), and ``api_key`` as ``Authorization: Bearer <key>``."""
    out = {k: resolve(v) for k, v in (headers or {}).items()}
    if api_key is not None:
        out["Authorization"] = f"Bearer {api_key.resolve()}"
    return out


@dataclass
class Served:
    """The engine runs behind ``linecaster serve`` (or any server speaking its routes), reached through
    saturate: ``endpoint`` is the server's ``.../v1`` base, ``model`` the name it hosts the model under.

    ``api_key`` (an ``EnvVar``, never the key itself) is sent as ``Authorization: Bearer <key>``; ``headers`` go
    with every request (values plain or ``EnvVar``). Both are read in the task, when the block's client opens."""

    endpoint: str
    model: str
    max_window: int = 32
    initial_window: int = 4
    read_timeout: float = 600.0
    #: the catalog preset (id@edition) and the engine (module:Class) the server hosts under ``model``, when known:
    #: the block's contract takes its parts from them
    preset: str | None = None
    engine: str | None = None
    api_key: EnvVar | None = None
    headers: dict | None = None
    served = True

    def __post_init__(self):
        check_secrets("Served", self.api_key, self.headers)

    def request_headers(self) -> dict[str, str]:
        """The headers every request carries, secrets read now (in the task)."""
        return request_headers(self.api_key, self.headers)

    def warm_up(self) -> None:
        """The secrets are read (a missing one fails the task before its first page); nothing else to load: the
        client opens with the block's run."""
        self.request_headers()

    def to_dict(self) -> dict:
        """The backend as the run record names it: endpoint, the served model's name, the window and timeout, the
        preset and engine when known, and the secrets by name (``{"env": NAME}``)."""
        out = {"backend": "served", "endpoint": self.endpoint, "model": self.model, "max_window": self.max_window,
               "initial_window": self.initial_window, "read_timeout": self.read_timeout}
        for k in ("preset", "engine", "api_key", "headers"):
            if getattr(self, k) is not None:
                out[k] = getattr(self, k)
        from ..blocks.base.block import plain

        return plain(out)

    def describe(self) -> str:
        return f"served {self.endpoint} ({self.model})"
