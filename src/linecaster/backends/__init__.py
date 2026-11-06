"""Where a block's engine runs: in the pipeline's process, or behind a server reached through saturate.

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
as well; the preset's adapter (``linecaster.adapters``) builds the requests and parses the completions.
"""
from .chat import Chat
from .in_process import EngineModel, InProcess, resolve
from .served import Served

__all__ = ["Chat", "EngineModel", "InProcess", "Served", "resolve"]
