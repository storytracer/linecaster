"""Where a block's model runs: in the pipeline's process, or behind a server reached through saturate.

An engine model (in ``engines/<engine>/``, its own package and environment) is a class with a
``step`` (layout, lines, recognition, ...), a ``name``, ``load()`` and ``__call__(image, transcription,
**params) -> Transcription``: it receives the page image (RGB uint8 array) and the transcription so
far, and returns it with its part added. The same class serves both backends:

* ``InProcess("linecaster_paddlex:PaddleLayoutModel", model_name="PP-DocLayoutV3")`` loads it in the
  worker (lazily, so a pickled pipeline carries only the spec);
* ``Served("http://127.0.0.1:8100/v1", model="layout")`` sends each page to ``linecaster serve``,
  which hosts the same class, through saturate.
"""
from .in_process import EngineModel, InProcess, resolve
from .served import Served

__all__ = ["EngineModel", "InProcess", "Served", "resolve"]
