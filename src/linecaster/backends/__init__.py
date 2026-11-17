"""Where a component's engine runs: in the pipeline's process, or behind a server reached through saturate.

An engine (in ``engines/<engine>/``, its own package and environment) is a class with an ``engine_id``
(``kraken.recognition.v1``), a ``step`` (layout, lines, recognition, ...), ``capabilities``, an ``Options`` model
(its keyword arguments), ``load()`` and ``__call__(image, transcription, **params) -> Transcription``: it
receives the page image (RGB uint8 array) and the transcription so far, and returns it with its part added.
The same class serves both backends:

* ``InProcess("linecaster_paddlex:PaddleLayoutEngine", model_name="PP-DocLayoutV3")`` loads it in the
  worker (lazily, so a pickled pipeline carries only the spec);
* ``Served("http://127.0.0.1:8100/v1", model="layout")`` sends each page to ``linecaster serve``,
  which hosts the same class, through saturate.

The third backend is for VLMs: ``Chat("dots-ocr", endpoint="http://127.0.0.1:8000/v1")`` reads pages (or regions)
with a chat preset's model behind an OpenAI-compatible server (vLLM, SGLang, a hosted endpoint), through saturate
as well; the preset's adapter (``linecaster.engines.chat``) builds the requests and parses the completions.
"""
from linecaster.backends.chat import Chat
from linecaster.backends.in_process import EngineModel, InProcess, resolve
from linecaster.backends.served import Served

def backend_from_dict(data: dict):
    """The backend a ``to_dict()`` describes (``{"backend": "in-process" | "served" | "chat", ...}``): the engine
    and options, or the endpoint and its settings, as recorded; secrets come back as ``EnvVar`` by name.

    Args:
        data: a backend's ``to_dict()``.

    Example:
        backend = backend_from_dict(InProcess("pkg:Engine", size=3).to_dict())
    """
    from linecaster.errors import PipelineConfigError
    from linecaster.execution.secrets import EnvVar

    def secret(v):
        return EnvVar(v["env"]) if isinstance(v, dict) and set(v) == {"env"} else v

    kind = data.get("backend")
    window = {k: data[k] for k in ("max_window", "initial_window", "read_timeout") if k in data}
    secrets = {"api_key": secret(data.get("api_key")),
               "headers": {k: secret(v) for k, v in data["headers"].items()} if data.get("headers") else None}
    if kind == "in-process":
        backend = InProcess(data["engine"], **(data.get("options") or {}))
        backend.preset, backend.preset_sha256 = data.get("preset"), data.get("preset_sha256")
        backend.overrides = data.get("overrides")
        return backend
    if kind == "served":
        return Served(data["endpoint"], model=data["model"], preset=data.get("preset"), engine=data.get("engine"),
                      **window, **secrets)
    if kind == "chat":
        return Chat(data["preset"], data.get("endpoint"), served_name=data.get("served_name"), **window, **secrets,
                    overrides=data.get("overrides"))
    raise PipelineConfigError(f"unknown backend {kind!r} (in-process, served or chat)")


__all__ = ["Chat", "EngineModel", "InProcess", "Served", "backend_from_dict", "resolve"]
