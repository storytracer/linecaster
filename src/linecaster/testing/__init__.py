"""Test helpers for engine packages, derivatives and linecaster's own tests.

* sample pages: ``sample_page`` (a synthetic page image with printed lines at known boxes, ``sample_boxes``),
  ``sample_png``, ``sample_layout`` (its regions and lines), ``sample_document`` and ``sample_documents`` (its
  datatrove documents), ``sample_transcription`` (a realistic transcription exercising every serializer feature);
* script samples: ``SCRIPT_SAMPLES``, ``script_page`` and ``script_image``, pages in twelve writing systems and all
  four writing directions, drawn with an installed font (``linecaster.testing.scripts``);
* fake engines, one per model step, deterministic CPU code: ``FakeLayoutEngine``, ``FakeLineEngine``,
  ``FakeRecognitionEngine``, ``FakePageEngine`` (a page engine), ``FakeTableEngine``, ``FakeFormulaEngine``,
  registered under ``fake.<step>[.<variant>].v1`` by ``register_fakes()``; ``fake_chat_server()``, an
  OpenAI-compatible server on loopback that answers from a function, with ``completion()`` for its answers;
  ``fake_service()``, an HTTP service on loopback that answers given routes from functions (a vendor's service);
* conformance: ``check_engine`` (the engine protocol) and ``check_block`` (the block conventions), with the
  comparisons they use (``transcription_changes``, ``page_changes``, and ``overwritten``: what a call changed of the
  annotations that were there);
* pytest: the markers and the hooks that skip ``gpu`` and ``network`` tests where they cannot run
  (``linecaster.testing.markers``).

Importing it loads neither datatrove's executors nor torch nor any engine; pytest only where a helper needs it.
"""
from linecaster.testing.chat import FakeChatServer, completion, fake_chat_server
from linecaster.testing.conformance import check_block, check_engine, overwritten, page_changes, transcription_changes
from linecaster.testing.fakes import (FAKE_ENGINES, FakeFormulaEngine, FakeLayoutEngine, FakeLineEngine, FakePageEngine,
                    FakeRecognitionEngine, FakeTableEngine, register_fakes)
from linecaster.testing.samples import (SAMPLE_LINES, box, sample_boxes, sample_document, sample_documents, sample_layout, sample_page,
                      sample_png, sample_transcription)
from linecaster.testing.scripts import SCRIPT_SAMPLES, ScriptSample, script_image, script_page
from linecaster.testing.service import FakeService, fake_service

__all__ = [
    "FAKE_ENGINES", "SAMPLE_LINES", "SCRIPT_SAMPLES", "FakeChatServer", "FakeFormulaEngine", "FakeLayoutEngine", "FakeLineEngine",
    "FakePageEngine", "FakeRecognitionEngine", "FakeService", "FakeTableEngine", "ScriptSample", "box", "check_block",
    "check_engine", "completion", "fake_chat_server", "fake_service", "overwritten", "page_changes", "register_fakes",
    "sample_boxes", "sample_document", "sample_documents", "sample_layout", "sample_page", "sample_png",
    "sample_transcription", "script_image", "script_page", "transcription_changes",
]
