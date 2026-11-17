"""linecaster: modular text recognition as datatrove pipelines.

    from linecaster import Pipeline, Component, Page, Transcription

``Pipeline`` is a list of components, checked and run as one; ``Component`` is what a component of your own builds
on; ``Page`` and ``Transcription`` are the page record and what a source said about a page. They are loaded when
first used, so importing ``linecaster`` stays light. The catalog is ``linecaster.catalog.catalog()``.
"""
__version__ = "0.12.0"

_EXPORTS = {"Pipeline": "linecaster.pipeline", "Component": "linecaster.core.component", "Page": "linecaster.data",
            "Transcription": "linecaster.data"}
__all__ = ["Component", "Page", "Pipeline", "Transcription", "__version__"]


def __getattr__(name: str):
    if name in _EXPORTS:
        import importlib

        value = globals()[name] = getattr(importlib.import_module(_EXPORTS[name]), name)
        return value
    raise AttributeError(f"module 'linecaster' has no attribute {name!r}")
