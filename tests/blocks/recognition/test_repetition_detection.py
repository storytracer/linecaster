"""vLLM's repetition detection as a chat option (``repetition_detection``): on by default wherever the preset's server
takes it, sent with every request where it is on and never where it is off, its defaults and ``--set`` fields, refused
for servers that would ignore it, recorded in the fingerprint; a completion that vLLM ended as ``repetition`` is
stored, counted and never repaired."""
from __future__ import annotations

import base64
import io
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from linecaster.adapters import RepetitionDetection, chat_model
from linecaster.backends import Chat
from linecaster.blocks.base.page import new_page_document, page_of
from linecaster.blocks.recognition.chat import PageRecognizer
from linecaster.data import FINISH_REASONS
from linecaster.errors import PipelineConfigError
from linecaster.testing import fake_chat_server
from linecaster.testing.chat import completion

PRESET = "lightonocr-3-0.8b@3"          # vLLM 0.30.0; repairs at 8192, then 12288
DEFAULTS = {"min_pattern_size": 8, "max_pattern_size": 100, "min_count": 16}
#: page width -> the fake model: finishes, needs more room than 4096 tokens, or loops (which vLLM's check ends)
STOPS, LONG, LOOPS = 300, 400, 500


def image(w: int, h: int = 600) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), 200).save(buf, format="PNG")
    return buf.getvalue()


def sent_width(body: dict) -> int:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size[0]


def answer(body: dict) -> dict:
    """A server with vLLM's check: a loop ends as ``repetition`` when the request asks for detection, else at the cap."""
    w, cap = sent_width(body), body["max_tokens"]
    if w == STOPS:
        return completion("short page", usage={"prompt_tokens": 3000, "completion_tokens": 50})
    if w == LONG:
        if cap > 4096:
            return completion("| long | table |\n" * 3, usage={"prompt_tokens": 3000, "completion_tokens": 5000})
        return completion("| long |\n", finish="length", usage={"prompt_tokens": 3000, "completion_tokens": cap})
    if body.get("repetition_detection"):
        return completion("Plate 4\n" + "| row |\n" * 10, finish="repetition",
                          usage={"prompt_tokens": 3000, "completion_tokens": 127})
    return completion("| row |\n" * 100, finish="length", usage={"prompt_tokens": 3000, "completion_tokens": cap})


def recognize(server, **overrides):
    step = PageRecognizer(Chat(PRESET, server.url, max_window=4, overrides=overrides or None))
    docs = [new_page_document(n, image(w)) for n, w in (("stops", STOPS), ("long", LONG), ("loops", LOOPS))]
    return step, {d.id: page_of(d).transcriptions["ocr_new"] for d in step.run(iter(docs))}


def test_on_by_default_where_the_server_takes_it_and_the_field_goes_with_every_request():
    """Every preset served by vLLM 0.17.0 or later sends the defaults with its first request and every repair; a preset
    on SGLang sends nothing; ``false`` turns it off, ``true`` is the default and no override."""
    from linecaster.adapters import chat_presets
    from linecaster.catalog.registry import catalog

    for ref in chat_presets():
        a = chat_model(ref)
        assert (a.sampling.get("repetition_detection") == DEFAULTS) == a.takes_repetition_detection, ref
        assert a.takes_repetition_detection == (catalog().resolve(ref).content["serve"]["server"] == "vllm"), ref
    on = chat_model(PRESET)
    body = on.request(image(STOPS))
    assert body["repetition_detection"] == DEFAULTS and on.settings()["sampling"]["repetition_detection"] == DEFAULTS
    assert on.repair_request(body, 8192)["repetition_detection"] == DEFAULTS
    off = chat_model(PRESET).apply_overrides({"repetition_detection": False})
    assert off.request(image(STOPS)).keys() == body.keys() - {"repetition_detection"}
    assert off.overrides == {"repetition_detection": None} and "repetition_detection" not in off.settings()["sampling"]
    assert chat_model(PRESET).apply_overrides({"repetition_detection": True}).overrides == {}
    assert "repetition_detection" not in chat_model("unlimited-ocr-2").sampling


def test_fields_over_the_defaults_and_bad_values_refused():
    a = chat_model(PRESET).apply_overrides({"repetition_detection.min_count": 12})
    assert a.sampling["repetition_detection"] == {**DEFAULTS, "min_count": 12}
    a = chat_model(PRESET).apply_overrides({"repetition_detection": {"max_pattern_size": 50},
                                            "repetition_detection.min_pattern_size": 2})
    assert a.sampling["repetition_detection"] == {"min_pattern_size": 2, "max_pattern_size": 50, "min_count": 16}
    for bad in ({"repetition_detection.min_count": 1}, {"repetition_detection.min_pattern_size": 200},
                {"repetition_detection.window": 3}, {"repetition_detection": "yes"}):
        with pytest.raises(PipelineConfigError, match="repetition_detection"):
            chat_model(PRESET).apply_overrides(bad)
    assert RepetitionDetection().model_dump() == DEFAULTS


def test_refused_where_the_server_would_ignore_the_field():
    """vLLM before 0.17.0 and SGLang (like any server that does not know a field) would ignore it: refused, also when a
    preset sets it."""
    with pytest.raises(PipelineConfigError, match=r"needs vLLM 0\.17\.0 or later; the preset's server is sglang"):
        chat_model("unlimited-ocr-2").apply_overrides({"repetition_detection": True})
    a = chat_model(PRESET)
    old = type(a)(replace(_preset(a), serve={**_preset(a).serve, "version": "0.16.0"}))
    with pytest.raises(PipelineConfigError, match="vllm 0.16.0"):
        old.apply_overrides({"repetition_detection": True})
    on = _preset(a)
    on = replace(on, settings={**on.settings, "sampling": {**on.settings["sampling"], "repetition_detection": {}}})
    assert type(a)(on).sampling["repetition_detection"] == DEFAULTS          # a preset's own, defaults filled in
    with pytest.raises(PipelineConfigError, match="vllm 0.16.0"):
        type(a)(replace(on, serve={**on.serve, "version": "0.16.0"}))


def _preset(adapter):
    from linecaster.adapters import ChatPreset
    from linecaster.catalog.registry import catalog

    r = catalog().resolve(PRESET)
    c = r.content
    return ChatPreset(ref=r.ref, sha256=r.sha256, repo=adapter.model, revision=adapter.revision,
                      options=dict(c.get("options") or {}), settings=dict(c.get("settings") or {}),
                      serve=dict(c.get("serve") or {}))


def test_the_setting_is_in_the_fingerprint_and_the_step_record():
    """On by default, so not in the preset: the adapter's record (and so ``pipeline_sha256``) names it while it is on."""
    from linecaster.blocks.recognition import PageRecognizer
    from linecaster.runtime import provenance

    a = chat_model(PRESET)
    assert a.to_dict()["repetition_detection"] == DEFAULTS and "overrides" not in a.to_dict()
    assert a.step_info().settings["sampling"]["repetition_detection"] == DEFAULTS
    off = chat_model(PRESET).apply_overrides({"repetition_detection": False})
    assert "repetition_detection" not in off.to_dict()
    on_block, off_block = (PageRecognizer(Chat(x, "http://127.0.0.1:8000/v1")) for x in (a, off))
    assert provenance.functional_block(on_block) != provenance.functional_block(off_block)
    assert provenance.functional_block(on_block)["params"]["backend"]["repetition_detection"] == DEFAULTS
    assert "repetition" in FINISH_REASONS


def test_a_loop_vllm_ended_is_stored_counted_and_never_repaired():
    """With detection on (the default) the looping page ends as ``repetition`` after one request (no repair), the long
    page still gets its repair; off, the loop runs to the cap and through both repairs."""
    with fake_chat_server(answer) as server:
        step, out = recognize(server)
    widths = [sent_width(b) for b in server.requests]
    assert widths.count(LOOPS) == 1 and widths.count(LONG) == 2 and widths.count(STOPS) == 1
    assert all(b["repetition_detection"] == DEFAULTS for b in server.requests)
    loops = out["loops"]
    assert loops.extra["finish_reason"] == "repetition" and loops.text.startswith("Plate 4\n| row |")
    assert loops.steps[0].measurements["finish_reason"] == "repetition" and "passes" not in loops.extra
    assert out["long"].extra["kept"] == 2
    assert step.stats["finish_repetition"].total == 1 and step.stats["finish_length"].total == 1
    with fake_chat_server(answer) as server:
        step, out = recognize(server, repetition_detection=False)
    assert [sent_width(b) for b in server.requests].count(LOOPS) == 3      # off: the first request and both repairs
    assert out["loops"].extra["finish_reason"] == "length" and "repetition_detection" not in server.requests[0]


def test_transcribe_vlm_turns_it_off_with_a_flag_and_takes_fields(tmp_path: Path):
    from linecaster.pipelines import transcribe_vlm as shape
    from linecaster.runtime import run

    def sets(*argv):
        a = run.parse(["IMAGES", "OUT", "--recognition", PRESET, *argv], shape.__doc__, shape.options,
                      shape.PIPELINE, shape.SLOTS)
        return shape.sets(a).get("recognition", {})

    assert sets() == {}
    assert sets("--no-repetition-detection") == {"repetition_detection": False}
    assert sets("--set", "recognition.repetition_detection.min_count=12") == {"repetition_detection.min_count": 12}
    assert sets("--set", "recognition.repetition_detection=true", "--no-repetition-detection") == {
        "repetition_detection": True}                                      # --set wins
