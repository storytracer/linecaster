"""``linecaster serve``: an OpenAI-style HTTP server for linecaster's engine models."""
from .app import Hosted, build_app, serve

__all__ = ["Hosted", "build_app", "serve", "engine"]


def engine(config: str, port: int = 8100, python: str = "python", boot_timeout: int = 1800):
    """A saturate ``Engine`` that starts ``linecaster serve --config CONFIG`` (with ``python``, the engine
    environment's interpreter) and waits until every model is loaded. Use it as a context manager;
    it yields the endpoint (``http://127.0.0.1:PORT/v1``)."""
    from saturate import Engine

    return Engine("linecaster", port=port, boot_timeout=boot_timeout,
                  cmd=[python, "-m", "linecaster.cli", "serve", "--config", config, "--port", str(port)],
                  ready_route="/models", ready_payload={})
