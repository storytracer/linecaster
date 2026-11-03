"""``linecaster serve``: an OpenAI-style HTTP server for linecaster's engine models."""
from __future__ import annotations

import json
import sys

from .app import Hosted, build_app, serve

__all__ = ["Hosted", "build_app", "serve", "engine", "serve_command"]


def serve_command(models: list[dict], port: int = 8100, python: str | None = None, max_queue: int = 16,
                  script: str | None = None) -> list[str]:
    """The command line that starts ``linecaster serve`` for ``models`` (dicts with name, spec, kwargs): with
    ``script``, a server script run by uv in its own environment (``uv run --script servers/kraken-paddlex.py``);
    otherwise ``python`` (default this interpreter) with ``-m linecaster.cli serve``."""
    if script:
        cmd = ["uv", "run", "--quiet", "--script", str(script)]
    else:
        cmd = [python or sys.executable, "-m", "linecaster.cli", "serve"]
    cmd += ["--port", str(port), "--max-queue", str(max_queue)]
    for m in models:
        cmd += ["--model", f"{m['name']}={m['spec']}", "--kwargs", f"{m['name']}={json.dumps(m.get('kwargs', {}))}"]
    return cmd


def engine(models: list[dict], port: int = 8100, python: str | None = None, boot_timeout: int = 1800,
           max_queue: int = 16, script: str | None = None):
    """A saturate ``Engine`` that starts ``linecaster serve`` for ``models`` (from a server ``script``, or
    with ``python``; default this interpreter) and waits until every model is loaded. A context manager
    yielding the endpoint ``http://127.0.0.1:PORT/v1``."""
    from saturate import Engine

    return Engine("linecaster", port=port, boot_timeout=boot_timeout,
                  cmd=serve_command(models, port, python, max_queue, script), ready_route="/models", ready_payload={})
