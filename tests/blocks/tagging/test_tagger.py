"""The ``Tagger``: a tagging engine on every page by preset or engine spec, its contract by what the engine reads, the
page image decoded only for the model tagger, the page's id in its review items."""
import json

import pytest

from linecaster.backends import InProcess
from linecaster.blocks.base.page import page_of
from linecaster.blocks.tagging import Tagger
from linecaster.errors import PipelineConfigError
from linecaster.testing import sample_documents
from linecaster.testing.chat import fake_chat_server


def _parts(block):
    c = block.contract()
    return sorted(p.name for p in c.reads), sorted(p.name for p in c.adds)


def test_the_geometry_tagger_by_preset():
    block = Tagger("geometry-tags")
    assert _parts(block) == (["lines", "regions"], ["tags"]) and not block.reads_image
    docs = list(block.run(iter(sample_documents(2))))
    t = page_of(docs[0]).transcriptions["ocr_new"]
    a = t.annotators[-1]
    assert a.step == "tagging" and a.preset == "geometry-tags" and a.preset_sha256.startswith("sha256:")
    assert {c.scheme for c in t.classifications} >= {"rotated", "multi_column"}


def test_a_preset_of_another_step_is_refused():
    with pytest.raises(PipelineConfigError, match="typography preset"):
        Tagger("ratios")


def test_the_model_tagger_by_engine_spec(tmp_path):
    answers = {"a": "degraded", "b": "not_degraded"}
    with fake_chat_server(lambda body: json.dumps({"reason": "r", "answer": answers[body["model"]]})) as server:
        block = Tagger(InProcess("linecaster.engines:ChatTaggingEngine", schemes=["degraded"],
                                 panel=[{"model": "a", "url": server.url}, {"model": "b", "url": server.url}],
                                 cache_dir=str(tmp_path / "cache"), review=str(tmp_path / "review")))
        assert _parts(block) == (["image", "regions"], ["tags"]) and block.reads_image
        docs = list(block.run(iter(sample_documents(1))))
        assert len(server.requests) == 2
    t = page_of(docs[0]).transcriptions["ocr_new"]
    assert t.annotators[-1].measurements["undecided"] == {"degraded": 1}
    item = json.loads(next((tmp_path / "review").glob("*.jsonl")).read_text(encoding="utf-8"))
    assert item["page"] == docs[0].id and item["target"] == "text_0"
