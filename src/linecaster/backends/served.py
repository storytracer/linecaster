"""``Served``: the engine runs behind ``linecaster serve`` (or any server speaking its routes), reached
through saturate."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Served:
    """The engine runs behind ``linecaster serve`` (or any server speaking its routes), reached through
    saturate: ``endpoint`` is the server's ``.../v1`` base, ``model`` the name it hosts the model under."""

    endpoint: str
    model: str
    max_window: int = 32
    initial_window: int = 4
    read_timeout: float = 600.0
    served = True

    def describe(self) -> str:
        return f"served {self.endpoint} ({self.model})"
