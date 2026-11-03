# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "linecaster",
#     "linecaster-kraken",
#     "linecaster-paddlex",
#     "linecaster-tesseract",
#     # direct, so the fork in [tool.uv.sources] applies (sources only apply to a script's own dependencies)
#     "kraken",
#     # PaddleX pins OpenCV's GUI build; this stub swaps in the headless build of the same version
#     "opencv-contrib-python",
#     "pytest>=8",
# ]
#
# [tool.uv]
# # the versions squiddleocr's goldens were recorded with (numerics: recognition, ONNX Runtime, CUDA, decoding);
# # the same list in every script (tests/test_scripts.py)
# constraint-dependencies = [
#     "lightning==2.6.6",
#     "onnxruntime-gpu==1.29.0",
#     "pillow==12.3.0",
#     "transformers==5.12.1",
#     "tokenizers==0.22.2",
#     "nvidia-cublas==13.1.1.3",
#     "nvidia-cuda-nvrtc==13.0.88",
#     "nvidia-cuda-runtime==13.0.96",
#     "nvidia-cudnn-cu13==9.24.0.43",
#     "nvidia-cufft==12.0.0.61",
#     "nvidia-curand==10.4.0.35",
#     "scipy==1.15.3",
#     "scikit-image==0.25.2",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# linecaster-kraken = { path = "../engines/kraken", editable = true }
# linecaster-paddlex = { path = "../engines/paddlex", editable = true }
# linecaster-tesseract = { path = "../engines/tesseract", editable = true }
# # kraken with the PP-OCRv6 code from our fork: upstream main (bb487219) plus the inference precision fix
# kraken = { git = "https://github.com/storytracer/kraken", rev = "3d235ee8" }
# opencv-contrib-python = { path = "../stubs/opencv-contrib-python" }
# ///
"""The engine packages in the catalogue (specs/catalog.md), without loading any model: every engine's ``Options``
mirror its constructor, capabilities use the vocabulary, every preset builds through ``InProcess.from_preset``,
and the installed catalogue (core + engines) verifies. Skipped in the core environment; with the engines:
``uv run tests/test_engines_catalog.py``."""
import inspect
from pathlib import Path

import pytest

for _pkg in ("linecaster_kraken", "linecaster_paddlex", "linecaster_tesseract"):
    pytest.importorskip(_pkg)

from linecaster.backends import InProcess, resolve  # noqa: E402
from linecaster.catalog.registry import Catalog, catalog, catalogue_dirs, engine_class, engine_kinds  # noqa: E402
from linecaster.catalog.schema import Capabilities  # noqa: E402

KINDS = {
    "kraken.recognition/1": "linecaster_kraken:KrakenRecognitionModel",
    "paddlex.layout/1": "linecaster_paddlex:PaddleLayoutModel",
    "paddlex.lines/1": "linecaster_paddlex:PaddleLineModel",
    "paddlex.recognition/1": "linecaster_paddlex:PaddleRecognitionModel",
    "paddlex.tables/1": "linecaster_paddlex:PaddleTableModel",
    "paddlex.formulas/1": "linecaster_paddlex:PaddleFormulaModel",
    "tesseract.recognition/1": "linecaster_tesseract:TesseractRecognitionModel",
}
ENGINE_PRESETS = sorted(pid for pid, (_, p) in catalog().presets.items() if p.engine.kind in KINDS)


def test_engines_are_registered_under_their_kinds():
    assert {k: v for k, v in engine_kinds().items() if k in KINDS} == KINDS
    for kind in KINDS:
        assert engine_class(kind).kind == kind


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_options_mirror_the_constructor(kind):
    cls = engine_class(kind)
    params = {name: p.default for name, p in inspect.signature(cls.__init__).parameters.items()
              if name not in ("self", "weights") and p.kind is not p.VAR_KEYWORD}
    assert "weights" in inspect.signature(cls.__init__).parameters
    fields = cls.Options.model_fields
    assert set(params) == set(fields)
    assert {name: f.default for name, f in fields.items()} == params
    assert all(f.description for f in fields.values()), [n for n, f in fields.items() if not f.description]
    model = cls()                                   # the defaults construct without loading a model
    assert model.options == cls.Options()
    with pytest.raises(ValueError):                 # unknown options are errors, in presets too
        cls.Options(no_such_option=1)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_capabilities_use_the_vocabulary(kind):
    cls = engine_class(kind)
    caps = Capabilities.model_validate(cls.capabilities)
    assert caps.unit in ("line", "region", "page") and caps.produces


def test_engine_catalogues_are_installed():
    dirs = catalogue_dirs()
    for pkg in ("linecaster_kraken", "linecaster_paddlex", "linecaster_tesseract"):
        assert any(d.parts[-2:] == (pkg, "catalog") for d in dirs), (pkg, dirs)
    assert len(ENGINE_PRESETS) == 18


def test_installed_catalogue_verifies():
    assert Catalog(catalogue_dirs()).verify() == []


@pytest.mark.parametrize("pid", ENGINE_PRESETS)
def test_preset_constructs_its_engine(pid):
    b = InProcess.from_preset(pid)
    p = catalog().preset(pid)
    assert b.preset == f"{pid}@{p.edition}" and b.preset_sha256.startswith("sha256:")
    assert b.kwargs["weights"]["model"] == p.model.id and b.kwargs["weights"]["revision"] == p.model.revision
    cls = resolve(b.spec)
    assert cls.kind == p.engine.kind and cls.step == p.step
    model = cls(**b.kwargs)                         # constructed, not loaded
    assert model.weights == b.kwargs["weights"]
    # the preset states every option but the device, so an edition does not depend on code defaults
    assert set(p.engine.options) == set(cls.Options.model_fields) - {"device"}
    assert model.options.model_dump(exclude={"device"}) == cls.Options(**p.engine.options).model_dump(exclude={"device"})
    assert Capabilities.model_validate(cls.capabilities).produces == p.capabilities.produces


def test_weights_must_name_the_model():
    from linecaster_kraken import KrakenRecognitionModel
    from linecaster_paddlex import PaddleLineModel
    from linecaster_tesseract import TesseractRecognitionModel

    def w(pid):
        return InProcess.from_preset(pid).kwargs["weights"]

    with pytest.raises(ValueError):
        KrakenRecognitionModel(model="tiny", weights=w("kraken-ppocrv6-medium"))
    with pytest.raises(ValueError):
        PaddleLineModel(model_name="PP-OCRv6_tiny_det", weights=w("pp-ocrv6-medium-det"))
    with pytest.raises(ValueError):
        TesseractRecognitionModel(data="fast", weights=w("tesseract-best-eng"))


def test_names_resolve_through_the_catalogue():
    from linecaster_kraken.models import size_weights
    from linecaster_paddlex.weights import catalogue_weights, model_id
    from linecaster_tesseract import models as tess

    for size in ("tiny", "small", "medium"):
        assert size_weights(size)["revision"] == catalog().preset(f"kraken-ppocrv6-{size}").model.revision
    assert model_id("PP-DocLayout_plus-L") == "pp-doclayout-plus-l-onnx"
    assert catalogue_weights("PP-FormulaNet_plus-L", "safetensors")["model"] == "pp-formulanet-plus-l-safetensors"
    assert catalogue_weights("PP-OCRv5_server_det") is None     # not in the catalogue: PaddleX downloads it
    assert {k: td.commit for k, td in tess.TESSDATA.items()} == {
        k: catalog().model(f"tessdata-{k}").pins[-1].revision for k in ("best", "fast")}


def test_layout_labels_are_the_codes_mapping():
    from linecaster_paddlex.layout import LABEL_MAP

    for pid in ("pp-doclayoutv3", "pp-doclayout-plus-l"):
        labels = catalog().preset(pid).labels
        assert labels and labels == {k: LABEL_MAP[k] for k in labels}
        assert "number" not in labels                # placed by position (page header or footer)


def test_layout_presets_state_the_model_defaults():
    from linecaster_paddlex.layout import MODEL_DEFAULTS

    for pid, name in (("pp-doclayoutv3", "PP-DocLayoutV3"), ("pp-doclayout-plus-l", "PP-DocLayout_plus-L")):
        o = engine_class("paddlex.layout/1").Options(**catalog().preset(pid).engine.options)
        assert (o.threshold, o.merge_mode) == (MODEL_DEFAULTS[name]["threshold"], MODEL_DEFAULTS[name]["merge_mode"])


def test_table_submodels_are_pinned_models():
    from linecaster_paddlex import PaddleTableModel
    from linecaster_paddlex.weights import model_id

    revs = catalog().preset("slanet-plus").engine.options["submodel_revisions"]
    assert set(revs) == set(PaddleTableModel.SUBMODELS)
    for name, rev in revs.items():
        catalog().model(model_id(name)).pin(rev)


def test_catalogue_files_ship_with_the_packages():
    """uv_build puts everything under the module folder into the wheel; the documents live there."""
    for d in catalogue_dirs()[1:]:
        if d.parts[-2] in ("linecaster_kraken", "linecaster_paddlex", "linecaster_tesseract"):
            assert (d / "__init__.py").exists() and (d / "catalog.lock").exists()
            assert list(d.glob("models/*/model.md")) and list(d.glob("presets/*.md"))
            assert Path(d).parent.name.startswith("linecaster_")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
