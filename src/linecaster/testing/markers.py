"""linecaster's pytest markers and the hooks that skip what this machine cannot run.

A ``conftest.py`` takes the hooks over by importing them (``from linecaster.testing.markers import
pytest_configure, pytest_collection_modifyitems``): the markers are registered, and tests marked ``gpu`` are
skipped without a CUDA device, tests marked ``network`` without the network (or with ``HF_HUB_OFFLINE=1``). pytest
is imported by the hooks only."""
from __future__ import annotations

import os
import socket
from functools import lru_cache

#: marker -> its meaning
MARKERS = {
    "gpu": "needs a CUDA device; skipped without one",
    "network": "downloads model weights or reaches the internet; skipped without the network",
    "slow": "takes over about 10 s",
    "parity": "compares outputs against the goldens",
}
#: where the network check connects (Hugging Face, where the weights come from)
PROBE = ("huggingface.co", 443)


@lru_cache(maxsize=1)
def has_gpu() -> bool:
    """Returns whether a CUDA device is visible: torch's view when torch is installed, else ``nvidia-smi``'s."""
    try:
        import torch
    except ImportError:
        import shutil
        import subprocess

        smi = shutil.which("nvidia-smi")
        if smi is None or os.environ.get("CUDA_VISIBLE_DEVICES") in ("", "-1"):
            return False
        try:
            return subprocess.run([smi, "-L"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return bool(torch.cuda.is_available())


@lru_cache(maxsize=1)
def has_network(timeout: float = 3.0) -> bool:
    """Returns whether Hugging Face can be reached (a TCP connection), unless ``HF_HUB_OFFLINE`` is set.

    Args:
        timeout: seconds to wait for the connection.
    """
    if os.environ.get("HF_HUB_OFFLINE", "").lower() in ("1", "true", "yes"):
        return False
    try:
        with socket.create_connection(PROBE, timeout=timeout):
            return True
    except OSError:
        return False


def pytest_configure(config) -> None:
    """Registers linecaster's markers (``MARKERS``).

    Args:
        config: pytest's config.
    """
    for name, meaning in MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {meaning}")


def pytest_collection_modifyitems(config, items) -> None:
    """Skips the tests marked ``gpu`` without a CUDA device and those marked ``network`` without the network.

    The device and the network are looked at only when a collected test carries the marker.

    Args:
        config: pytest's config.
        items: the collected tests.
    """
    import pytest

    for marker, available, why in (("gpu", has_gpu, "no CUDA device"), ("network", has_network, "no network")):
        marked = [item for item in items if item.get_closest_marker(marker) is not None]
        if marked and not available():
            for item in marked:
                item.add_marker(pytest.mark.skip(reason=why))


__all__ = ["MARKERS", "has_gpu", "has_network", "pytest_collection_modifyitems", "pytest_configure"]
