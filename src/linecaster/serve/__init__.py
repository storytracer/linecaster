"""``linecaster serve``: an OpenAI-style HTTP server for linecaster's engine models."""
from __future__ import annotations

import json
import sys

from .app import Hosted, build_app, serve

__all__ = ["Hosted", "build_app", "serve", "engine", "serve_command"]


def serve_command(models: list[dict], port: int = 8100, python: str | None = None, max_queue: int = 16,
                  script: str | None = None) -> list[str]:
    """The command line that starts ``linecaster serve`` for ``models`` (dicts with name, spec, kwargs): with
    ``script``, a pipeline's ``serve`` command, run by uv in the pipeline's environment
    (``uv run --script pipelines/transcribe_modular.py serve``); otherwise ``python`` (default this interpreter) with
    ``-m linecaster.cli serve``."""
    if script:
        cmd = ["uv", "run", "--quiet", "--script", str(script), "serve"]
    else:
        cmd = [python or sys.executable, "-m", "linecaster.cli", "serve"]
    return cmd + ["--port", str(port), "--max-queue", str(max_queue)] + model_args(models)


def model_args(models: list[dict]) -> list[str]:
    """``linecaster serve`` arguments for ``models``: ``--preset NAME=REF`` for a catalogue preset (the server
    resolves it and stamps its edition on every page; ``overrides`` go along as ``--kwargs`` and are merged
    over the preset's options), otherwise ``--model NAME=module:Class --kwargs NAME=JSON``."""
    out = []
    for m in models:
        if m.get("preset"):
            out += ["--preset", f"{m['name']}={m['preset']}"]
            if m.get("overrides"):
                out += ["--kwargs", f"{m['name']}={json.dumps(m['overrides'])}"]
        else:
            out += ["--model", f"{m['name']}={m['spec']}", "--kwargs", f"{m['name']}={json.dumps(m.get('kwargs', {}))}"]
    return out


def engine(models: list[dict], port: int = 8100, python: str | None = None, boot_timeout: int = 1800,
           max_queue: int = 16, script: str | None = None):
    """A saturate ``Engine`` that starts ``linecaster serve`` for ``models`` (from a server ``script``, or
    with ``python``; default this interpreter) and waits until every model is loaded. A context manager
    yielding the endpoint ``http://127.0.0.1:PORT/v1``."""
    from saturate import Engine

    # the trial request goes to the step route itself: 503 until every model is loaded, then 404 from
    # linecaster's handler, since no model serves the step "ready"
    return Engine("linecaster", port=port, boot_timeout=boot_timeout,
                  cmd=serve_command(models, port, python, max_queue, script), ready_route="/linecaster/ready",
                  ready_payload={}, ready_accept=lambda r: r.status_code == 404)
