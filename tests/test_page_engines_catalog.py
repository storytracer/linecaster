# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "linecaster",
#     "linecaster-indra",
#     "linecaster-services",
#     "linecaster-surya",
#     "pytest>=8",
# ]
#
# [tool.uv]
# # surya-ocr 0.23.0 declares pillow<11, and linecaster needs Pillow>=11: the override wins (NOTES.md: the four board
# # models). torch is surya-ocr's (>=2.7,<3), not pinned: no kraken here
# override-dependencies = [
#     "pillow==12.3.0",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# linecaster-indra = { path = "../engines/indra", editable = true }
# linecaster-services = { path = "../engines/services", editable = true }
# linecaster-surya = { path = "../engines/surya", editable = true }
# ///
"""The page engine packages in the catalog (docs/reference/catalog.md), in the environment of
``pipelines/transcribe_page.py`` (the same pins), without loading any model: every engine's ``Options`` mirror its
constructor, capabilities use the vocabulary, every preset builds through ``InProcess.from_preset`` and states its
options, and the installed catalog (core + engines) verifies. Skipped in the core environment; with the engines:
``uv run tests/test_page_engines_catalog.py``, and an engine package's tests with
``uv run tests/test_page_engines_catalog.py engines/<engine>/tests``."""
import inspect

import pytest

for _pkg in ("linecaster_indra", "linecaster_services", "linecaster_surya"):
    pytest.importorskip(_pkg)

from linecaster.backends import InProcess, resolve  # noqa: E402
from linecaster.catalog.registry import Catalog, catalog, engine_class, engine_ids  # noqa: E402
from linecaster.catalog.schema import Capabilities  # noqa: E402

ENGINES = {
    "indra.recognition.v1": "linecaster_indra:IndraRecognitionEngine",
    "falcon.recognition.v1": "linecaster_services:FalconRecognitionEngine",
    "oxr.recognition.v1": "linecaster_services:OxrRecognitionEngine",
    "surya.recognition.v1": "linecaster_surya:SuryaRecognitionEngine",
}
#: options a preset leaves to the deployment: where the engine's service is, and how long a request may take
OPERATIONAL = {"endpoint", "timeout"}
ENGINE_PRESETS = sorted(pid for pid, (_, p) in catalog().presets.items() if p.engine in ENGINES)


def test_engines_are_registered_under_their_ids():
    assert {k: v for k, v in engine_ids().items() if k in ENGINES} == ENGINES
    for engine in ENGINES:
        assert engine_class(engine).engine_id == engine


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_options_mirror_the_constructor(engine):
    cls = engine_class(engine)
    params = {name: p.default for name, p in inspect.signature(cls.__init__).parameters.items()
              if name not in ("self", "weights") and p.kind is not p.VAR_KEYWORD}
    assert "weights" in inspect.signature(cls.__init__).parameters
    fields = cls.Options.model_fields
    assert set(params) == set(fields)
    assert {name: f.get_default(call_default_factory=True) for name, f in fields.items()} == params
    assert all(f.description for f in fields.values())
    assert cls().options == cls.Options()          # the defaults construct without loading a model
    with pytest.raises(ValueError):
        cls.Options(no_such_option=1)


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_capabilities_read_whole_pages(engine):
    caps = Capabilities.model_validate(engine_class(engine).capabilities)
    assert caps.unit == "page" and {"lines", "text"} <= set(caps.produces)


def test_the_catalog_verifies_with_the_engines_installed():
    assert ENGINE_PRESETS == ["falcon-ocr", "indra-ocr", "oxr-1.0", "surya-ocr-2.5"]
    assert Catalog().verify() == []


@pytest.mark.parametrize("pid", ENGINE_PRESETS)
def test_preset_constructs_its_engine(pid):
    b = InProcess.from_preset(pid)
    p = catalog().preset(pid)
    assert b.preset == f"{pid}@{p.edition}" and b.kwargs["weights"]["revision"] == p.model.revision
    cls = resolve(b.spec)
    assert cls.engine_id == p.engine and cls.step == p.step
    model = cls(**b.kwargs)                         # constructed, not loaded
    assert model.weights == b.kwargs["weights"]
    # the preset states every option but where its service is, so an edition does not depend on code defaults
    assert set(p.options) == set(cls.Options.model_fields) - OPERATIONAL
    assert Capabilities.model_validate(cls.capabilities).produces == p.capabilities.produces


if __name__ == "__main__":     # with arguments: those tests instead (an engine package's: engines/<engine>/tests)
    import sys

    raise SystemExit(pytest.main([*(sys.argv[1:] or [__file__]), "-q", "-p", "no:cacheprovider"]))
