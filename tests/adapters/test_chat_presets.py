"""Chat presets (catalog, engine chat.v1): every preset resolves and builds its adapter, Hugging Face ids still
work, the edition and its hash reach the annotator, and the blocks take preset refs."""
from __future__ import annotations

import pickle

import pytest

from linecaster.adapters import ADAPTERS, ENGINE, ChatAdapter, adapter, chat_model, chat_presets, preset_ref
from linecaster.backends import Chat
from linecaster.blocks.recognition.chat import PageRecognizer, RegionRecognizer
from linecaster.blocks.servers.serve import ChatModelServer
from linecaster.catalog.registry import catalog
from linecaster.errors import CatalogError

PRESETS = sorted(chat_presets())


def test_there_are_the_chat_presets():
    assert len(PRESETS) == 23
    assert {"dots-ocr", "lightonocr-2-1b", "lightonocr-2-1b-regions", "minicpm-ocr-1.0", "unlimited-ocr-2",
            "lightonocr-3-0.8b", "lightonocr-3-4b", "lightonocr-3-0.8b-plain", "lightonocr-3-4b-plain"} <= set(PRESETS)


@pytest.mark.parametrize("pid", PRESETS)
def test_every_preset_builds_its_adapter(pid):
    c = catalog()
    p = c.preset(pid)
    spec = chat_model(pid)
    assert isinstance(spec, ChatAdapter) and type(spec) is adapter(p.options["adapter"])
    m = c.model(p.model.id)
    assert (spec.model, spec.revision) == (m.source.ref, p.model.revision)
    m.pin(spec.revision)                                       # pinned in the model entry
    r = c.resolve(pid)
    assert (spec.preset, spec.preset_sha256) == (r.ref, r.sha256)
    assert p.step == spec.step == "recognition" and spec.unit == p.capabilities.unit in ("page", "region")
    assert spec.server == p.serve.server and spec.serve_args == p.serve.flags and spec.job_image
    assert spec.sampling and isinstance(spec.settings(), dict)
    assert pickle.loads(pickle.dumps(spec)).settings() == spec.settings()        # datatrove pickles the pipeline
    assert p.provenance.derived_from and c.body(pid).strip()        # provenance and reasons


def test_every_adapter_is_used():
    used = {catalog().preset(pid).options["adapter"] for pid in PRESETS}
    assert used == set(ADAPTERS)


@pytest.mark.parametrize("hub_id, page, regions", [
    ("lightonai/LightOnOCR-2-1B", "lightonocr-2-1b", "lightonocr-2-1b-regions"),
    ("rednote-hilab/dots.ocr", "dots-ocr", "dots-ocr"),
    ("openbmb/MiniCPM-OCR-1.0", "minicpm-ocr-1.0", "minicpm-ocr-1.0"),        # read only by region
])
def test_hugging_face_ids_name_a_preset(hub_id, page, regions):
    assert preset_ref(hub_id) == page and preset_ref(hub_id, prefer="region") == regions
    assert chat_model(hub_id).preset == page
    assert preset_ref("dots-ocr") == "dots-ocr"
    with pytest.raises(CatalogError, match="no chat preset"):
        preset_ref("nobody/nothing")


def test_a_reference_with_an_edition_resolves_to_this_release_with_a_warning():
    """Catalog entries carry no edition since 0.10: ``dots-ocr@1`` (a record from before) is this release's
    ``dots-ocr``, with a warning; its hash is the one the index lists."""
    from linecaster.catalog.registry import EditionWarning

    with pytest.warns(EditionWarning, match="dots-ocr@1"):
        spec = chat_model("dots-ocr@1")
    assert spec.preset == "dots-ocr"
    assert spec.preset_sha256 == catalog().dirs[0].read_index()["presets"]["dots-ocr"]
    with pytest.raises(CatalogError):
        chat_model("nobody-knows")


def test_the_annotator_records_the_preset_edition():
    spec = chat_model("glm-ocr")
    body = {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}], "usage": {}}
    m = spec.parse(body, backend="served x").annotators[0]
    assert (m.preset, m.preset_sha256) == ("glm-ocr", spec.preset_sha256)
    assert (m.name, m.engine) == ("zai-org/GLM-OCR", "chat.v1") and m.settings == spec.settings()


def test_blocks_take_preset_refs():
    page = PageRecognizer(Chat("dots-ocr", "http://127.0.0.1:1/v1"))
    assert page.adapter.preset == "dots-ocr" and page.backend.model == "rednote-hilab/dots.ocr"
    regions = RegionRecognizer(Chat("lightonocr-2-1b-regions", "http://127.0.0.1:1/v1", served_name="m"))
    assert regions.pad == 8 and regions.adapter.page_longest == 1540 and regions.adapter.served_name == "m"
    assert RegionRecognizer("minicpm-ocr-1.0").pad == 0
    # a preset by name: Chat on the task's ChatModelServer; a Hugging Face id picks the preset of the block's unit
    assert PageRecognizer("lightonocr-2-1b").backend.endpoint == "http://127.0.0.1:8000/v1"
    assert RegionRecognizer("lightonai/LightOnOCR-2-1B").adapter.preset == "lightonocr-2-1b-regions"
    assert PageRecognizer("lightonai/LightOnOCR-2-1B").adapter.preset == "lightonocr-2-1b"
    serve = ChatModelServer("unlimited-ocr-2")
    assert serve.server == "sglang" and serve.spec.served_name == "Unlimited-OCR-2"


def test_served_name_and_draft_come_from_the_preset():
    m = chat_model("minicpm-ocr-1.0")
    assert m.served_name == "minicpm-ocr" and chat_model("minicpm-ocr-1.0", served_name="x").served_name == "x"
    assert m.draft_model == catalog().model("minicpm-ocr-1.0-dspark").source.ref
    assert not hasattr(chat_model("dots-ocr"), "draft_model")


def test_presets_are_chat_engine_presets():
    assert all(catalog().preset(pid).engine == ENGINE for pid in PRESETS)
