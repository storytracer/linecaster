"""``linecaster serve``: an OpenAI-style HTTP server for linecaster's engine models."""
from __future__ import annotations

import json
import sys

from .app import Hosted, build_app, serve

__all__ = ["Hosted", "build_app", "serve", "engine", "serve_command"]


def serve_command(models: list[dict], port: int = 8100, python: str | None = None, max_queue: int = 16) -> list[str]:
    """The command line that starts ``linecaster serve`` for ``models`` (dicts with name, spec, kwargs)."""
    cmd = [python or sys.executable, "-m", "linecaster.cli", "serve", "--port", str(port), "--max-queue", str(max_queue)]
    for m in models:
        cmd += ["--model", f"{m['name']}={m['spec']}", "--kwargs", f"{m['name']}={json.dumps(m.get('kwargs', {}))}"]
    return cmd


def engine(models: list[dict], port: int = 8100, python: str | None = None, boot_timeout: int = 1800,
           max_queue: int = 16):
    """A saturate ``Engine`` that starts ``linecaster serve`` for ``models`` (with ``python``, the engine
    environment's interpreter; default this one) and waits until every model is loaded. A context
    manager yielding the endpoint ``http://127.0.0.1:PORT/v1``."""
    from saturate import Engine

    return Engine("linecaster", port=port, boot_timeout=boot_timeout,
                  cmd=serve_command(models, port, python, max_queue), ready_route="/models", ready_payload={})
