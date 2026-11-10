"""Chat-VLM page recognition: the LightOnOCR-2 spec's request and parse, and PageRecognizer end to end
against a fake OpenAI-compatible server (through saturate, as in production)."""
from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image

from linecaster.adapters import chat_model, text_transcription
from linecaster.backends import Chat, InProcess
from linecaster.blocks.base.page import new_page_document, page_of
from linecaster.blocks.recognition.chat import PageRecognizer, RegionRecognizer
from linecaster.blocks.servers.serve import ChatModelServer
from linecaster.data.transcription import Transcription
from linecaster.errors import PipelineConfigError, ServerError
from linecaster.testing import fake_chat_server


def image(w: int, h: int, fmt: str = "WEBP") -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), 200).save(buf, format=fmt)
    return buf.getvalue()


def sent_image(body: dict) -> Image.Image:
    url = body["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


# ------------------------------------------------------------------ request
@pytest.mark.parametrize("size, expected", [
    ((2000, 3000), (1027, 1540)),    # portrait, downscaled
    ((3000, 2000), (1540, 1027)),    # landscape
    ((700, 1000), (1078, 1540)),     # smaller than 1540: forced UP, as the board driver does
    ((1000, 1540), (1000, 1540)),    # already at the target: untouched
])
def test_lighton_request_forces_longest_side_to_1540(size, expected):
    body = chat_model("lightonocr-2-1b").request(image(*size))
    im = sent_image(body)
    assert im.format == "PNG" and im.mode == "RGB" and im.size == expected


def test_lighton_request_is_image_only_with_card_sampling():
    body = chat_model("lightonai/LightOnOCR-2-1B").request(image(800, 1200, "JPEG"))
    assert body["model"] == "lightonai/LightOnOCR-2-1B"
    assert len(body["messages"]) == 1 and body["messages"][0]["role"] == "user"
    content = body["messages"][0]["content"]
    assert len(content) == 1 and content[0]["type"] == "image_url"      # no text part
    assert (body["max_tokens"], body["temperature"], body["top_p"]) == (4096, 0.2, 0.9)
    assert set(body) == {"model", "messages", "max_tokens", "temperature", "top_p"}


def test_lighton_serve_args_match_the_board_driver():
    spec = chat_model("lightonocr-2-1b")
    args = spec.vllm_args(0.22)
    assert args[:2] == ["--revision", "c97bd377f04481830395218fa8951df9deaba756"]
    for flag in (["--max-model-len", "16384"], ["--limit-mm-per-prompt", '{"image": 1}'],
                 ["--mm-processor-cache-gb", "0"], ["--gpu-memory-utilization", "0.22"]):
        i = args.index(flag[0])
        assert args[i:i + 2] == flag
    assert "--no-enable-prefix-caching" in args and "--trust-remote-code" not in args
    assert "--served-model-name" not in args
    assert "--served-model-name" in chat_model("lightonocr-2-1b", served_name="ocr").vllm_args()


def test_serve_block_command():
    cmd = ChatModelServer(chat_model("lightonocr-2-1b"), port=8123, gpu_memory_utilization=0.3).command()
    assert cmd[:7] == ["vllm", "serve", "lightonai/LightOnOCR-2-1B", "--host", "127.0.0.1", "--port", "8123"]
    assert cmd[-2:] == ["--gpu-memory-utilization", "0.3"]


# -------------------------------------------------------------------- parse
def completion(content, finish="stop", usage=None):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": usage if usage is not None else {"prompt_tokens": 2322, "completion_tokens": 7}}


def test_parse_keeps_the_completion_verbatim():
    raw = "\n48\n\n# THE HAWFINCH\n\nnest itself  \n"
    t = chat_model("lightonocr-2-1b").parse(completion(raw), backend="served x")
    assert t.extra["raw"] == raw and t.text == raw            # not even a strip
    assert [ln.text for ln in t.lines] == raw.split("\n")
    assert all(ln.bbox is None and ln.polygon is None for ln in t.lines)
    assert [ln.reading_order for ln in t.lines] == list(range(len(t.lines)))
    assert t.source.kind == "produced" and t.source.format == "text"
    m = t.steps[0]
    assert (m.step, m.name, m.revision, m.backend) == ("recognition", "lightonai/LightOnOCR-2-1B",
                                                       "c97bd377f04481830395218fa8951df9deaba756", "served x")
    assert m.measurements == {"prompt_tokens": 2322, "completion_tokens": 7, "finish_reason": "stop"}
    assert m.settings["sampling"]["temperature"] == 0.2 and m.settings["image"]["longest_side_px"] == 1540
    assert Transcription.model_validate_json(t.model_dump_json()) == t      # exact round trip


def test_parse_truncated_and_empty():
    t = chat_model("lightonocr-2-1b").parse(completion("a\na\na", finish="length"))
    assert t.extra["finish_reason"] == "length" and t.steps[0].measurements["finish_reason"] == "length"
    empty = chat_model("lightonocr-2-1b").parse(completion(None, usage={}))
    assert empty.text == "" and empty.extra["raw"] == "" and len(empty.lines) == 1
    assert empty.steps[0].measurements["prompt_tokens"] is None


def test_parse_without_choices_raises():
    with pytest.raises(ServerError, match="no choices"):
        chat_model("lightonocr-2-1b").parse({"object": "error"})


def test_text_transcription_round_trips_text():
    for raw in ["", "x", "a\n\nb\n", "\n"]:
        assert text_transcription(raw).text == raw


def test_region_recognition_needs_a_chat_backend():
    with pytest.raises(PipelineConfigError, match="needs a Chat backend"):
        RegionRecognizer(InProcess("x:y"))


def test_page_recognition_takes_a_page_engine_but_no_other_unit():
    assert PageRecognizer(InProcess("x:y")).shape == "unit"
    with pytest.raises(PipelineConfigError, match="needs a Chat, InProcess or Served backend"):
        PageRecognizer(object())
    with pytest.raises(PipelineConfigError, match="reads line units, not whole pages"):
        PageRecognizer("kraken-ppocrv6-medium@1")


# ---------------------------------------------------- end to end, fake server
def _answer(body: dict) -> dict:
    im = sent_image(body)
    return completion(f"\npage {im.size[0]}x{im.size[1]}\n", usage={"prompt_tokens": 10, "completion_tokens": 3})


@pytest.fixture()
def chat():
    with fake_chat_server(_answer) as server:
        yield server


def seen(server) -> list[tuple[str, tuple[int, int]]]:
    """The model and image size of every request the server got."""
    return [(body["model"], sent_image(body).size) for body in server.requests]


def test_chat_page_step_end_to_end(chat):
    docs = [new_page_document(str(i), image(1000 + 100 * i, 2000)) for i in range(5)]
    errored = new_page_document("bad", image(10, 10))
    errored.metadata["errors"] = [{"step": "earlier", "error": "x"}]
    step = PageRecognizer(Chat("lightonocr-2-1b", chat.url, max_window=4))
    out = {d.id: d for d in step.run(iter([*docs, errored]))}
    assert set(out) == {"0", "1", "2", "3", "4", "bad"}
    assert len(seen(chat)) == 5 and {m for m, _ in seen(chat)} == {"lightonai/LightOnOCR-2-1B"}
    for i in range(5):
        d = out[str(i)]
        t = page_of(d).transcriptions["ocr_new"]
        w = round((1000 + 100 * i) * 1540 / 2000)
        assert t.extra["raw"] == f"\npage {w}x1540\n" and d.text == t.extra["raw"]
        assert t.steps[0].measurements["completion_tokens"] == 3
        assert "errors" not in d.metadata
    assert "ocr_new" not in page_of(out["bad"]).transcriptions      # bypassed: an earlier step failed on it


def test_chat_region_step_end_to_end(chat):
    from linecaster.blocks.base.page import set_page
    from linecaster.blocks.recognition.chat import RegionRecognizer
    from linecaster.data.transcription import Region

    def with_regions(page_id, regions):
        d = new_page_document(page_id, image(2000, 3000))
        page = page_of(d)
        page.transcriptions["ocr_new"] = Transcription(regions=[
            Region(id=rid, label=label, polygon=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]], bbox=[x, y, w, h],
                   reading_order=k) for k, (rid, label, (x, y, w, h)) in enumerate(regions)])
        set_page(d, page)
        return d

    docs = [with_regions("a", [("r1", "text", (100, 100, 800, 400)), ("pic", "picture", (0, 0, 10, 10)),
                               ("r2", "title", (100, 600, 1000, 200))]),
            with_regions("none", [("pic", "picture", (0, 0, 10, 10))])]
    step = RegionRecognizer(Chat("lightonocr-2-1b-regions", chat.url, max_window=4))
    out = {d.id: d for d in step.run(iter(docs))}
    assert set(out) == {"a", "none"} and len(seen(chat)) == 2          # the picture is not read
    t = page_of(out["a"]).transcriptions["ocr_new"]
    assert [ln.region_id for ln in t.lines] == ["r1", "r2"] and all(ln.text.startswith("\npage ") for ln in t.lines)
    m = t.steps[-1]
    assert (m.preset, m.measurements["regions"], m.measurements["prompt_tokens"]) == (
        "lightonocr-2-1b-regions@1", 2, 20)
    assert page_of(out["none"]).transcriptions["ocr_new"].lines == []     # passed through unchanged


def test_chat_page_step_records_server_errors(chat):
    # a route the server does not have: the page comes out with the error recorded, no transcription
    step = PageRecognizer(Chat("lightonocr-2-1b", chat.url.replace("/v1", "/nope"), served_name="m", max_window=2))
    out = list(step.run(iter([new_page_document("p", image(100, 200))])))
    assert len(out) == 1 and out[0].metadata["errors"][0]["step"] == "recognition"
    assert "404" in out[0].metadata["errors"][0]["error"]
    assert "ocr_new" not in page_of(out[0]).transcriptions


def test_serve_block_outside_venv(monkeypatch):
    import os
    import sys

    own = os.path.join(sys.prefix, "bin")
    monkeypatch.setenv("PATH", os.pathsep.join([own, "/usr/local/bin", "/usr/bin"]))
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    block = ChatModelServer(chat_model("lightonocr-2-1b"), port=8123, outside_venv=True)
    cmd = block.launch_command()
    assert cmd[:4] == ["env", "-u", "VIRTUAL_ENV", "PATH=/usr/local/bin:/usr/bin"]
    assert cmd[4:] == block.command()
    assert ChatModelServer(chat_model("lightonocr-2-1b")).launch_command() == ChatModelServer(chat_model("lightonocr-2-1b")).command()


def test_minicpm_speculative_args_pin_the_draft():
    import json

    
    flag, config = chat_model("minicpm-ocr-1.0").speculative_args(chat_model("minicpm-ocr-1.0").draft_model, chat_model("minicpm-ocr-1.0").draft_revision)
    assert flag == "--speculative-config"
    assert json.loads(config) == {"method": "dspark", "model": "openbmb/MiniCPM-OCR-1.0-DSpark", "num_speculative_tokens": 15,
                                  "enable_adaptive_verification": False, "revision": chat_model("minicpm-ocr-1.0").draft_revision}


def test_job_dependencies_without_kraken():
    from linecaster.runtime.jobs import ROOT, dependencies

    deps = dependencies("abc123", ROOT / "pipelines/transcribe_vlm.py")
    assert any(d.startswith("linecaster-paddlex @ ") for d in deps)
    assert not any("kraken" in d or "lightning" in d or "git+" in d for d in deps)
    modular = dependencies("abc123", ROOT / "pipelines/transcribe_modular.py")
    assert any(d.startswith("linecaster-paddlex @ ") for d in modular)
    assert not any("kraken" in d for d in modular)                # kraken runs in an environment that adds it


def test_region_recognizer_pad_explicit_wins_over_the_adapter():
    from linecaster.blocks.recognition.chat import DEFAULT_PAD, RegionRecognizer

    assert chat_model("minicpm-ocr-1.0").region_pad == 0
    assert RegionRecognizer("minicpm-ocr-1.0@1").pad == 0                 # the adapter's region_pad is the default
    assert RegionRecognizer("minicpm-ocr-1.0@1", pad=4).pad == 4          # an explicit pad wins
    assert RegionRecognizer("minicpm-ocr-1.0@1", pad=0).pad == 0
    backend = Chat("minicpm-ocr-1.0@1")
    backend.adapter.region_pad = None
    assert RegionRecognizer(backend).pad == DEFAULT_PAD == 8              # neither says


def test_region_recognizer_declares_the_lines_it_replaces():
    from linecaster.blocks.layout import LayoutDetector
    from linecaster.blocks.lines import LineDetector
    from linecaster.blocks.readers import ImageFolderReader
    from linecaster.blocks.recognition.chat import RegionRecognizer
    from linecaster.runtime.builder import build

    c = RegionRecognizer("minicpm-ocr-1.0@1").contract()
    assert {str(p) for p in c.replaces} == {"ocr_new:lines", "ocr_new:text"}
    assert {"ocr_new:lines", "ocr_new:text"} <= {str(p) for p in c.adds}
    # after a line step, the earlier lines are replaced: not a part added twice
    plan = build([ImageFolderReader("x"), LayoutDetector("single-region@1"), LineDetector(InProcess("x:Y")),
                  RegionRecognizer("minicpm-ocr-1.0@1")])
    assert plan.problems == []
