"""The repair pass of the chat page recognizer: a page whose completion stopped at ``max_tokens`` is sent once more
with a larger cap, against fake OpenAI-compatible servers (through saturate, as in production); inline, over page
records (``repair_only``) and through ``pipelines/transcribe_vlm.py``'s shape; off by default."""
from __future__ import annotations

import base64
import gzip
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.backends import Chat
from linecaster.blocks.base.page import new_page_document, page_of
from linecaster.blocks.recognition.chat import PageRecognizer, RegionRecognizer
from linecaster.errors import PipelineConfigError
from linecaster.runtime import provenance, run
from linecaster.testing import fake_chat_server
from linecaster.testing.chat import completion

PRESET = "lightonocr-3-0.8b@2"
MODEL = "lightonai/LightOnOCR-3-0.8B"
PROMPT_TOKENS = 3000
#: page width -> what the fake model does with it: stops at once, stops when given more room, or loops
STOPS, LONG, LOOPS = 300, 400, 500


def image(w: int, h: int = 600) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), 200).save(buf, format="PNG")
    return buf.getvalue()


def sent_width(body: dict) -> int:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size[0]


def answer(body: dict) -> dict:
    """The fake model: ``first``/``second`` by the cap; a long page needs more than 4096 tokens, a loop never ends."""
    w, cap = sent_width(body), body["max_tokens"]
    usage = {"prompt_tokens": PROMPT_TOKENS}
    if w == STOPS:
        return completion("short page", usage={**usage, "completion_tokens": 50})
    if w == LONG and cap > 4096:
        return completion("| long | table |\n" * 3, usage={**usage, "completion_tokens": 5000})
    return completion("| row |\n" * (2 if cap <= 4096 else 4), finish="length",
                      usage={**usage, "completion_tokens": cap})


def docs():
    return [new_page_document("stops", image(STOPS)), new_page_document("long", image(LONG)),
            new_page_document("loops", image(LOOPS))]


def recognize(server, **overrides):
    step = PageRecognizer(Chat(PRESET, server.url, max_window=4, overrides=overrides or None))
    out = {d.id: page_of(d).transcriptions["ocr_new"] for d in step.run(iter(docs()))}
    return step, out


def by_width(server) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for body in server.requests:
        out.setdefault(sent_width(body), []).append(body)
    return out


def stats(step) -> dict[str, float]:
    return {k: step.stats[k].total for k in ("finish_length", "repair_sent", "repair_stop", "repair_length",
                                              "repair_kept", "repair_skipped", "repair_errors", "repair_not_needed")
            if step.stats[k].total}


# --------------------------------------------------------------------------------------------- inline
def test_a_page_that_stopped_at_max_tokens_is_sent_once_more_and_keeps_a_finished_repair():
    with fake_chat_server(answer, models=[{"id": MODEL, "max_model_len": 18000}]) as server:
        step, t = recognize(server, repair_max_tokens=8192)
    sent = by_width(server)
    assert {w: len(bodies) for w, bodies in sent.items()} == {STOPS: 1, LONG: 2, LOOPS: 2}    # never a third
    for w in (LONG, LOOPS):
        first, second = sent[w]
        # the same request (the same image and prompt, the same top_p), the cap and the temperature raised
        assert {k: v for k, v in second.items() if k not in ("max_tokens", "temperature")} == {
            k: v for k, v in first.items() if k not in ("max_tokens", "temperature")}
        assert (first["max_tokens"], first["temperature"], first["top_p"]) == (4096, 0.2, 0.9)
        assert (second["max_tokens"], second["temperature"], second["top_p"]) == (8192, 0.1, 0.9)

    long, loops, stops = t["long"], t["loops"], t["stops"]
    assert long.extra["kept"] == 2 and long.text == "| long | table |\n" * 3          # the repair finished: kept
    assert (long.extra["raw"], long.extra["finish_reason"]) == (long.text, "stop")
    assert [p["finish_reason"] for p in long.extra["passes"]] == ["length", "stop"]
    assert long.extra["passes"][0] == {"raw": "| row |\n| row |\n", "finish_reason": "length",
                                       "prompt_tokens": PROMPT_TOKENS, "completion_tokens": 4096, "max_tokens": 4096,
                                       "temperature": 0.2, "top_p": 0.9, "preset": PRESET}
    assert long.extra["passes"][1] == {"raw": long.text, "finish_reason": "stop", "prompt_tokens": PROMPT_TOKENS,
                                       "completion_tokens": 5000, "max_tokens": 8192, "temperature": 0.1,
                                       "top_p": 0.9, "preset": PRESET}
    (m,) = long.steps
    assert m.measurements == {"prompt_tokens": 2 * PROMPT_TOKENS, "completion_tokens": 9096, "finish_reason": "stop",
                              "pass_prompt_tokens": [PROMPT_TOKENS, PROMPT_TOKENS],
                              "pass_completion_tokens": [4096, 5000], "decoder": m.measurements["decoder"]}
    assert m.measurements["decoder"].startswith("Pillow ")       # the request's pixels (no GPU decodes a PNG)
    assert m.settings["repair"] == {"max_tokens": [8192], "temperature": 0.1} and m.preset == PRESET
    assert m.settings["sampling"] == {"max_tokens": 4096, "temperature": 0.2, "top_p": 0.9}

    # the repair stopped at its cap too: the first completion stays, even though the repair's is longer
    assert loops.extra["kept"] == 1 and loops.text == "| row |\n| row |\n"
    assert (loops.extra["raw"], loops.extra["finish_reason"]) == (loops.text, "length")
    assert [(p["finish_reason"], p["max_tokens"]) for p in loops.extra["passes"]] == [("length", 4096),
                                                                                       ("length", 8192)]
    assert loops.extra["passes"][1]["raw"] == "| row |\n" * 4
    assert loops.steps[0].measurements["pass_completion_tokens"] == [4096, 8192]

    # a page that stopped by itself is recorded as without the repair pass
    assert "passes" not in stops.extra and "kept" not in stops.extra
    assert stops.steps[0].measurements == {"prompt_tokens": PROMPT_TOKENS, "completion_tokens": 50,
                                           "finish_reason": "stop", "decoder": m.measurements["decoder"]}
    assert stats(step) == {"finish_length": 2, "repair_sent": 2, "repair_stop": 1, "repair_length": 1,
                           "repair_kept": 1}
    assert step.stats["completion_tokens"].total == 50 + 4096 + 5000 + 4096 + 8192


def test_the_repair_cap_is_what_the_served_context_leaves_and_none_is_sent_without_room():
    # the server's max_model_len: 11000 - 3000 prompt tokens leaves 8000, less than repair_max_tokens
    with fake_chat_server(answer, models=[{"id": MODEL, "max_model_len": 11000}]) as server:
        step, t = recognize(server, repair_max_tokens=8192)
    assert [b["max_tokens"] for b in by_width(server)[LONG]] == [4096, 8000]
    assert t["long"].extra["passes"][1]["max_tokens"] == 8000              # the cap actually used
    # 7000 - 3000 = 4000, not above the first request's 4096: no repair, the page keeps its first completion
    with fake_chat_server(answer, models=[{"id": MODEL, "max_model_len": 7000}]) as server:
        step, t = recognize(server, repair_max_tokens=8192)
    assert len(server.requests) == 3
    assert stats(step) == {"finish_length": 2, "repair_skipped": 2}
    assert t["long"].extra["kept"] == 1 and len(t["long"].extra["passes"]) == 1
    assert t["long"].steps[0].measurements["pass_completion_tokens"] == [4096]
    # without /models the preset's --max-model-len (18000) is the context
    with fake_chat_server(answer) as server:
        recognize(server, repair_max_tokens=12288)
    assert [b["max_tokens"] for b in by_width(server)[LONG]] == [4096, 12288]


def test_a_failed_repair_leaves_the_first_completion():
    def fails_second(body):
        if body["max_tokens"] > 4096:
            return {"object": "error"}                                      # no choices: the repair's error
        return answer(body)

    with fake_chat_server(fails_second) as server:
        step, t = recognize(server, repair_max_tokens=8192)
    assert t["long"].extra["kept"] == 1 and t["long"].extra["finish_reason"] == "length"
    assert len(t["long"].extra["passes"]) == 1                              # a later --repair-only tries again
    assert stats(step) == {"finish_length": 2, "repair_sent": 2, "repair_errors": 2}


def test_the_repair_pass_is_off_by_default():
    with fake_chat_server(answer) as server:
        step, t = recognize(server)
    assert len(server.requests) == 3                                        # one request per page
    for page in t.values():
        assert set(page.extra) == {"raw", "finish_reason"}
        (m,) = page.steps
        assert set(m.measurements) == {"prompt_tokens", "completion_tokens", "finish_reason", "decoder"}
        assert "repair" not in m.settings
    assert stats(step) == {"finish_length": 2}
    # the run record and the hash: no options over the preset, the same functional block as before the repair pass
    off = PageRecognizer(Chat(PRESET))
    assert "overrides" not in off.to_dict()["params"]["backend"]
    assert "repair_only" not in provenance.functional_block(off)["params"]
    assert provenance.functional_block(PageRecognizer(Chat(PRESET, overrides={"repair_max_tokens": 0}))) == \
        provenance.functional_block(off)
    on = provenance.functional_block(PageRecognizer(Chat(PRESET, overrides={"repair_max_tokens": 8192})))
    assert on["params"]["backend"]["overrides"] == {"repair_max_tokens": 8192} and on != provenance.functional_block(off)


# ------------------------------------------------------------------------------------------ validation
def test_the_options_are_checked():
    with pytest.raises(PipelineConfigError, match=r"repair_max_tokens \(4096\) must rise, .*the first larger than "
                                                   r"max_tokens"):
        chat_model(PRESET, overrides={"repair_max_tokens": 4096})
    with pytest.raises(PipelineConfigError, match="must rise"):
        chat_model(PRESET, overrides={"repair_max_tokens": [8192, 8192]})
    with pytest.raises(PipelineConfigError, match="must rise"):
        chat_model(PRESET, overrides={"repair_max_tokens": 8192, "max_tokens": 9000})
    with pytest.raises(PipelineConfigError, match="no_such_option"):
        chat_model(PRESET, overrides={"no_such_option": 1})
    with pytest.raises(PipelineConfigError, match="repair_max_tokens"):
        chat_model(PRESET, overrides={"repair_max_tokens": "many"})
    a = chat_model(PRESET, overrides={"max_tokens": 5000, "temperature": 0, "top_p": 1, "repair_max_tokens": 9000,
                                      "repair_temperature": 0.0})
    assert a.sampling == {"max_tokens": 5000, "temperature": 0.0, "top_p": 1.0}
    assert (a.repair_max_tokens, a.repair_temperature) == (9000, 0.0)
    assert a.overrides == {"max_tokens": 5000, "temperature": 0.0, "top_p": 1.0, "repair_max_tokens": 9000,
                           "repair_temperature": 0.0}
    assert chat_model(PRESET, overrides={"max_tokens": 4096, "repair_temperature": 0.1}).overrides == {}
    with pytest.raises(PipelineConfigError, match="repair_only needs"):
        PageRecognizer(Chat(PRESET), repair_only=True)
    with pytest.raises(PipelineConfigError, match="whole pages"):
        RegionRecognizer(Chat("lightonocr-2-1b-regions", overrides={"repair_max_tokens": 8192}))


def test_a_warning_when_the_repair_cap_and_a_page_do_not_fit_the_context():
    from loguru import logger

    seen = []
    sink = logger.add(lambda m: seen.append(m.record["message"]), level="WARNING")
    try:
        PageRecognizer(Chat(PRESET, overrides={"repair_max_tokens": 12288}))             # 12288 + 4160 <= 18000
        assert seen == []
        PageRecognizer(Chat("lightonocr-3-0.8b@1", overrides={"repair_max_tokens": 12288}))   # > 16384
    finally:
        logger.remove(sink)
    assert len(seen) == 1 and "16384" in seen[0] and "repair_skipped" in seen[0]


# -------------------------------------------------------------------------- the pipeline shape
def _images(folder: Path) -> str:
    folder.mkdir(parents=True)
    for name, w in (("stops", STOPS), ("long", LONG), ("loops", LOOPS)):
        (folder / f"{name}.png").write_bytes(image(w))
    return str(folder)


def _run(*argv):
    from linecaster.pipelines import transcribe_vlm as shape

    a = run.parse(list(argv), shape.__doc__, shape.options, shape.PIPELINE, shape.SLOTS)
    pipeline, _ = shape.pipeline(a, __file__)
    run.run(a, pipeline, __file__, argv=list(argv))
    return a


def _records(out: str) -> dict[str, dict]:
    rows = {}
    for f in sorted(Path(out, "pages").glob("*.jsonl.gz")):
        with gzip.open(f, "rt") as fh:
            rows.update({(r := json.loads(line))["id"]: r for line in fh if line.strip()})
    return rows


def _stage_block(out: str, name: str) -> dict:
    from linecaster.catalog import yamlio

    rec = yamlio.load(Path(out, "run.yaml").read_text())
    return rec, next(b for b in rec["pipeline"][0]["blocks"] if b["block"] == name)


def test_transcribe_vlm_sets_the_options_and_records_them(tmp_path: Path):
    from linecaster.pipelines import transcribe_vlm as shape

    images = _images(tmp_path / "images")
    with fake_chat_server(answer, models=[{"id": MODEL, "max_model_len": 18000}]) as server:
        out = str(tmp_path / "on")
        _run(images, out, "--recognition", PRESET, "--recognition-endpoint", server.url,
             "--set", "recognition.repair_max_tokens=8192")
    rec, block = _stage_block(out, "PageRecognizer")
    assert block["params"]["backend"]["overrides"] == {"repair_max_tokens": 8192}
    records = _records(out)
    long = records["long"]["page"]["transcriptions"]["ocr_new"]
    assert long["extra"]["kept"] == 2 and long["steps"][0]["settings"]["repair"]["max_tokens"] == [8192]
    assert records["loops"]["page"]["transcriptions"]["ocr_new"]["extra"]["kept"] == 1
    assert len(server.requests) == 5

    def hash_of(*sets):
        argv = ["IN", "OUT", "--recognition", PRESET, *[x for s in sets for x in ("--set", s)]]
        return provenance.pipeline_sha256(run.describe(shape, argv))

    plain = hash_of()
    assert rec["pipeline_sha256"] == hash_of("recognition.repair_max_tokens=8192") != plain
    assert hash_of("recognition.repair_max_tokens=0") == plain                # the preset's own value: no change
    # max_tokens, temperature and top_p are settable too, and reach the requests
    with fake_chat_server(answer) as server:
        _run(images, str(tmp_path / "sampling"), "--recognition", PRESET, "--recognition-endpoint", server.url,
             "--set", "recognition.max_tokens=3000", "--set", "recognition.temperature=0",
             "--set", "recognition.top_p=1")
    assert {(b["max_tokens"], b["temperature"], b["top_p"]) for b in server.requests} == {(3000, 0, 1)}
    with pytest.raises(PipelineConfigError, match="no step 'lines'"):
        hash_of("lines.x=1")
    with pytest.raises(PipelineConfigError, match="bogus"):
        hash_of("recognition.bogus=1")
    with pytest.raises(PipelineConfigError, match="must rise"):
        hash_of("recognition.repair_max_tokens=100")
    with pytest.raises(PipelineConfigError, match="--repair-only reads page records"):
        run.describe(shape, ["IN", "OUT", "--recognition", PRESET, "--repair-only",
                             "--set", "recognition.repair_max_tokens=8192"])


def test_repair_only_over_page_records(tmp_path: Path):
    images = _images(tmp_path / "images")
    first = str(tmp_path / "first")
    with fake_chat_server(answer) as server:          # an earlier run without the repair pass (or linecaster 0.5)
        _run(images, first, "--recognition", PRESET, "--recognition-endpoint", server.url)
    before = _records(first)
    assert "passes" not in before["long"]["page"]["transcriptions"]["ocr_new"]["extra"]

    repaired = str(tmp_path / "repaired")
    with fake_chat_server(answer) as server:
        _run(repaired, "--pages", f"{first}/pages", "--repair-only", "--recognition", PRESET,
             "--recognition-endpoint", server.url, "--set", "recognition.repair_max_tokens=8192")
    # only the two pages that stopped at max_tokens, only their repair requests
    assert sorted((sent_width(b), b["max_tokens"], b["temperature"], b["top_p"]) for b in server.requests) == [
        (LONG, 8192, 0.1, 0.9), (LOOPS, 8192, 0.1, 0.9)]
    after = _records(repaired)
    assert after["stops"] == before["stops"]                                   # passed through: the same record
    long = after["long"]["page"]["transcriptions"]["ocr_new"]
    assert long["extra"]["kept"] == 2 and long["extra"]["finish_reason"] == "stop"
    first_pass = before["long"]["page"]["transcriptions"]["ocr_new"]
    assert long["extra"]["passes"][0] == {"raw": first_pass["extra"]["raw"], "finish_reason": "length",
                                          "prompt_tokens": PROMPT_TOKENS, "completion_tokens": 4096,
                                          "max_tokens": 4096, "temperature": 0.2, "top_p": 0.9, "preset": PRESET}
    assert long["extra"]["passes"][1]["max_tokens"] == 8192
    assert long["steps"][0]["measurements"]["pass_completion_tokens"] == [4096, 5000]
    assert after["long"]["text"] == long["extra"]["raw"]
    loops = after["loops"]["page"]["transcriptions"]["ocr_new"]
    assert loops["extra"]["kept"] == 1
    assert loops["extra"]["raw"] == before["loops"]["page"]["transcriptions"]["ocr_new"]["extra"]["raw"]
    assert [p["finish_reason"] for p in loops["extra"]["passes"]] == ["length", "length"]
    rec, block = _stage_block(repaired, "PageRecognizer")
    assert block["params"]["repair_only"] is True

    # a second repair-only run: every page has had its repair, nothing is sent, every record stays
    again = str(tmp_path / "again")
    with fake_chat_server(answer) as server:
        _run(again, "--pages", f"{repaired}/pages", "--repair-only", "--recognition", PRESET,
             "--recognition-endpoint", server.url, "--set", "recognition.repair_max_tokens=8192")
    assert server.requests == [] and _records(again) == after


def test_repair_only_takes_a_page_with_one_pass_and_records_the_inline_way(tmp_path: Path):
    """A run with the repair pass but no room for it (one pass recorded) is repaired later, with more room."""
    images = _images(tmp_path / "images")
    first = str(tmp_path / "first")
    with fake_chat_server(answer, models=[{"id": MODEL, "max_model_len": 7000}]) as server:
        _run(images, first, "--recognition", PRESET, "--recognition-endpoint", server.url,
             "--set", "recognition.repair_max_tokens=8192")
    assert len(_records(first)["long"]["page"]["transcriptions"]["ocr_new"]["extra"]["passes"]) == 1
    later = str(tmp_path / "later")
    with fake_chat_server(answer, models=[{"id": MODEL, "max_model_len": 18000}]) as server:
        _run(later, "--pages", f"{first}/pages", "--repair-only", "--recognition", PRESET,
             "--recognition-endpoint", server.url, "--set", "recognition.repair_max_tokens=8192")
    assert len(server.requests) == 2
    long = _records(later)["long"]["page"]["transcriptions"]["ocr_new"]
    assert long["extra"]["kept"] == 2 and len(long["extra"]["passes"]) == 2


# ----------------------------------------------------------------------------------- RegionRecognizer
def test_the_region_recognizer_is_unchanged():
    from linecaster.blocks.base.page import set_page
    from linecaster.data.transcription import Region, Transcription

    d = new_page_document("a", image(2000, 3000))
    page = page_of(d)
    page.transcriptions["ocr_new"] = Transcription(regions=[
        Region(id="r1", label="text", polygon=[[0, 0], [800, 0], [800, 400], [0, 400]], bbox=[0, 0, 800, 400],
               reading_order=0)])
    set_page(d, page)
    with fake_chat_server(lambda body: completion("x x x", finish="length")) as server:
        step = RegionRecognizer(Chat("lightonocr-2-1b-regions", server.url, max_window=2))
        (out,) = list(step.run(iter([d])))
    assert len(server.requests) == 1 and step.stats["finish_length"].total == 1
    (line,) = page_of(out).transcriptions["ocr_new"].lines
    assert line.extra == {"raw": "x x x", "finish_reason": "length"}
    assert set(provenance.functional_block(step)["params"]) == {"backend", "transcription", "labels", "pad",
                                                                "primary", "skip_on_error"}


# ----------------------------------------------------------------------------------- several repair passes
#: page width -> a page that needs more than 8192 tokens: it finishes only with the third cap
LONGER = 600


def escalating(body: dict) -> dict:
    """The fake model of ``answer``, plus a page that finishes only above 8192 tokens."""
    w, cap = sent_width(body), body["max_tokens"]
    if w == LONGER and cap > 8192:
        return completion("| longer | table |\n" * 5, usage={"prompt_tokens": PROMPT_TOKENS, "completion_tokens": 9000})
    return answer(body)


def test_repairs_escalate_while_a_page_stops_at_its_cap_and_keep_the_first_that_finished():
    """``repair_max_tokens: [8192, 12288]``: a page that stops at 4096 is sent with 8192; if that stops at its cap
    too, with 12288; never more. A page that finishes at 8192 gets no third request; one that loops gets all three
    and keeps its first completion."""
    pages = [*docs(), new_page_document("longer", image(LONGER))]
    with fake_chat_server(escalating, models=[{"id": MODEL, "max_model_len": 18000}]) as server:
        step = PageRecognizer(Chat(PRESET, server.url, max_window=4,
                                   overrides={"repair_max_tokens": [8192, 12288]}))
        out = {d.id: page_of(d).transcriptions["ocr_new"] for d in step.run(iter(pages))}
        sent = by_width(server)
    caps = {w: [b["max_tokens"] for b in bodies] for w, bodies in sent.items()}
    assert caps == {STOPS: [4096], LONG: [4096, 8192], LOOPS: [4096, 8192, 12288], LONGER: [4096, 8192, 12288]}
    assert all(b["temperature"] == 0.1 for w in (LONG, LOOPS, LONGER) for b in sent[w][1:])
    longer, loops, long = out["longer"], out["loops"], out["long"]
    assert [p["finish_reason"] for p in longer.extra["passes"]] == ["length", "length", "stop"]
    assert longer.extra["kept"] == 3 and longer.text == "| longer | table |\n" * 5
    assert [p["max_tokens"] for p in longer.extra["passes"]] == [4096, 8192, 12288]
    assert [p["finish_reason"] for p in loops.extra["passes"]] == ["length"] * 3 and loops.extra["kept"] == 1
    assert loops.text == "| row |\n" * 2                                   # its first completion stays
    assert long.extra["kept"] == 2 and len(long.extra["passes"]) == 2
    assert longer.steps[0].settings["repair"] == {"max_tokens": [8192, 12288], "temperature": 0.1}
    assert longer.steps[0].measurements["pass_completion_tokens"] == [4096, 8192, 9000]
    assert stats(step) == {"finish_length": 3, "repair_sent": 5, "repair_stop": 2, "repair_length": 3,
                           "repair_kept": 2}


def test_a_later_repair_the_context_leaves_no_room_for_is_not_sent():
    """Each cap is at most the context minus the page's prompt; a pass whose cap is then not above the one before
    is not sent."""
    with fake_chat_server(escalating, models=[{"id": MODEL, "max_model_len": 3000 + 8192}]) as server:
        step = PageRecognizer(Chat(PRESET, server.url, max_window=4,
                                   overrides={"repair_max_tokens": [8192, 12288]}))
        out = {d.id: page_of(d).transcriptions["ocr_new"] for d in step.run(iter([new_page_document(
            "longer", image(LONGER))]))}
        sent = by_width(server)
    assert [b["max_tokens"] for b in sent[LONGER]] == [4096, 8192]          # 12288 cut to 8192: no room above
    assert out["longer"].extra["kept"] == 1 and len(out["longer"].extra["passes"]) == 2


def test_repair_only_continues_with_the_later_caps():
    """Over page records written without repairs, ``repair_only`` sends the first repair and, while it stops at its
    cap, the next."""
    with fake_chat_server(escalating, models=[{"id": MODEL, "max_model_len": 18000}]) as server:
        first = PageRecognizer(Chat(PRESET, server.url, max_window=4))
        records = list(first.run(iter([new_page_document("longer", image(LONGER)),
                                       new_page_document("stops", image(STOPS))])))
        again = PageRecognizer(Chat(PRESET, server.url, max_window=4, overrides={"repair_max_tokens": [8192, 12288]}),
                               repair_only=True)
        out = {d.id: page_of(d).transcriptions["ocr_new"] for d in again.run(iter(records))}
    longer = out["longer"]
    assert [p["max_tokens"] for p in longer.extra["passes"]] == [4096, 8192, 12288] and longer.extra["kept"] == 3
    assert "passes" not in out["stops"].extra                              # not needed: unchanged


def test_lightonocr_3_0_8b_edition_3_escalates_to_twice_and_three_times_its_cap():
    from linecaster.adapters import chat_model as model

    three = model("lightonocr-3-0.8b@3")
    assert three.sampling["max_tokens"] == 4096 and three.repair_caps == (8192, 12288)
    assert model("lightonocr-3-0.8b@2").repair_caps == ()
    assert three.repair_temperature == 0.1 and three.apply_overrides({"repair_max_tokens": 0}).repair_caps == ()
