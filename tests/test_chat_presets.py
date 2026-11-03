"""Chat presets (catalogue, engine chat/1): every preset resolves and builds its adapter, Hugging Face ids still
work, the edition and its hash reach ModelInfo, and the blocks take preset refs."""
from __future__ import annotations

import pickle

import pytest

from linecaster.backends import Served
from linecaster.blocks.chat import ChatPageStep, ChatRegionStep
from linecaster.blocks.serve import ServeChatModel
from linecaster.catalog.registry import catalog
from linecaster.models import ADAPTERS, KIND, ChatModel, adapter, chat_model, chat_presets, preset_ref

PRESETS = sorted(chat_presets())


def test_there_are_the_chat_presets():
    assert len(PRESETS) == 21
    assert {"dots-ocr", "lightonocr-2-1b", "lightonocr-2-1b-regions", "minicpm-ocr-1.0", "unlimited-ocr-2"} <= set(PRESETS)


@pytest.mark.parametrize("pid", PRESETS)
def test_every_preset_builds_its_adapter(pid):
    c = catalog()
    p = c.preset(pid)
    spec = chat_model(pid)
    assert isinstance(spec, ChatModel) and type(spec) is adapter(p.engine.options["adapter"])
    m = c.model(p.model.id)
    assert (spec.model, spec.revision) == (m.source.ref, p.model.revision)
    m.pin(spec.revision)                                       # pinned in the model document
    r = c.resolve(pid)
    assert (spec.preset, spec.preset_sha256) == (r.ref, r.sha256) and r.released
    assert spec.step == ("regions" if p.step == "recognition" else "page")
    assert (p.capabilities.unit == "region") == (p.step == "recognition")
    assert spec.server == p.serve.server and spec.serve_args == p.serve.flags and spec.job_image
    assert spec.sampling and isinstance(spec.settings(), dict)
    assert pickle.loads(pickle.dumps(spec)).settings() == spec.settings()        # datatrove pickles the pipeline
    assert p.provenance.derived_from and c.body(pid).strip()        # provenance and reasons


def test_every_adapter_is_used():
    used = {catalog().preset(pid).engine.options["adapter"] for pid in PRESETS}
    assert used == set(ADAPTERS)


@pytest.mark.parametrize("hub_id, page, regions", [
    ("lightonai/LightOnOCR-2-1B", "lightonocr-2-1b", "lightonocr-2-1b-regions"),
    ("rednote-hilab/dots.ocr", "dots-ocr", "dots-ocr"),
    ("openbmb/MiniCPM-OCR-1.0", "minicpm-ocr-1.0", "minicpm-ocr-1.0"),        # read only by region
])
def test_hugging_face_ids_name_a_preset(hub_id, page, regions):
    assert preset_ref(hub_id) == page and preset_ref(hub_id, prefer="recognition") == regions
    assert chat_model(hub_id).preset == f"{page}@1"
    assert preset_ref("dots-ocr@1") == "dots-ocr@1"
    with pytest.raises(KeyError, match="no chat preset"):
        preset_ref("nobody/nothing")


def test_an_explicit_edition_resolves_from_the_lock():
    spec = chat_model("dots-ocr@1")
    entry = catalog().dirs[0].lock.presets["dots-ocr@1"]
    assert spec.preset == "dots-ocr@1" and spec.preset_sha256 == entry.sha256
    with pytest.raises(KeyError):
        chat_model("dots-ocr@99")


def test_model_info_records_the_preset_edition():
    spec = chat_model("glm-ocr")
    body = {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}], "usage": {}}
    m = spec.parse(body, backend="served x").model[0]
    assert (m.preset, m.preset_sha256) == ("glm-ocr@1", spec.preset_sha256)
    assert m.name == "zai-org/GLM-OCR" and m.settings == spec.settings()


def test_blocks_take_preset_refs():
    page = ChatPageStep("dots-ocr", Served("http://127.0.0.1:1/v1", model="rednote-hilab/dots.ocr"))
    assert page.spec.preset == "dots-ocr@1"
    regions = ChatRegionStep("lightonocr-2-1b-regions", Served("http://127.0.0.1:1/v1", model="m"))
    assert regions.pad == 8 and regions.spec.page_longest == 1540 and regions.spec.served_name == "m"
    assert ChatRegionStep("minicpm-ocr-1.0", Served("http://127.0.0.1:1/v1", model="minicpm-ocr")).pad == 0
    serve = ServeChatModel("unlimited-ocr-2")
    assert serve.server == "sglang" and serve.spec.served_name == "Unlimited-OCR-2"


def test_served_name_and_draft_come_from_the_preset():
    m = chat_model("minicpm-ocr-1.0")
    assert m.served_name == "minicpm-ocr" and chat_model("minicpm-ocr-1.0", served_name="x").served_name == "x"
    assert m.draft_model == catalog().model("minicpm-ocr-1.0-dspark").source.ref
    assert not hasattr(chat_model("dots-ocr"), "draft_model")


def test_presets_are_chat_engine_presets():
    assert all(catalog().preset(pid).engine.kind == KIND for pid in PRESETS)
