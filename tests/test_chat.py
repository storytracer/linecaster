"""Chat-VLM page recognition: the LightOnOCR-2 spec's request and parse, and ChatPageStep end to end
against a fake OpenAI-compatible server (through saturate, as in production)."""
from __future__ import annotations

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from linecaster.backends import InProcess, Served
from linecaster.blocks.base import new_page_document, page_of
from linecaster.blocks.chat import ChatPageStep
from linecaster.blocks.serve import ServeChatModel
from linecaster.models import chat_model, text_transcription
from linecaster.transcription.model import Transcription


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
    cmd = ServeChatModel(chat_model("lightonocr-2-1b"), port=8123, gpu_memory_utilization=0.3).command()
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
    m = t.model[0]
    assert (m.step, m.name, m.revision, m.backend) == ("page", "lightonai/LightOnOCR-2-1B",
                                                       "c97bd377f04481830395218fa8951df9deaba756", "served x")
    assert m.measurements == {"prompt_tokens": 2322, "completion_tokens": 7, "finish_reason": "stop"}
    assert m.settings["sampling"]["temperature"] == 0.2 and m.settings["image"]["longest_side_px"] == 1540
    assert Transcription.model_validate_json(t.model_dump_json()) == t      # exact round trip


def test_parse_truncated_and_empty():
    t = chat_model("lightonocr-2-1b").parse(completion("a\na\na", finish="length"))
    assert t.extra["finish_reason"] == "length" and t.model[0].measurements["finish_reason"] == "length"
    empty = chat_model("lightonocr-2-1b").parse(completion(None, usage={}))
    assert empty.text == "" and empty.extra["raw"] == "" and len(empty.lines) == 1
    assert empty.model[0].measurements["prompt_tokens"] is None


def test_parse_without_choices_raises():
    with pytest.raises(ValueError, match="no choices"):
        chat_model("lightonocr-2-1b").parse({"object": "error"})


def test_text_transcription_round_trips_text():
    for raw in ["", "x", "a\n\nb\n", "\n"]:
        assert text_transcription(raw).text == raw


def test_chat_step_needs_a_served_backend():
    with pytest.raises(TypeError):
        ChatPageStep(chat_model("lightonocr-2-1b"), InProcess("x:y"))


# ---------------------------------------------------- end to end, fake server
class FakeChat(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):  # saturate's engine probe: no gauges here (blind mode)
        self.send_response(404); self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/v1/chat/completions":
            self.send_response(404); self.end_headers(); return
        im = sent_image(body)
        FakeChat.seen.append((body["model"], im.size))
        out = json.dumps(completion(f"\npage {im.size[0]}x{im.size[1]}\n", usage={"prompt_tokens": 10,
                                                                                "completion_tokens": 3})).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out)))
        self.end_headers(); self.wfile.write(out)


@pytest.fixture()
def fake_server():
    FakeChat.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeChat)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def test_chat_page_step_end_to_end(fake_server):
    docs = [new_page_document(str(i), image(1000 + 100 * i, 2000)) for i in range(5)]
    errored = new_page_document("bad", image(10, 10))
    errored.metadata["errors"] = [{"step": "earlier", "error": "x"}]
    step = ChatPageStep(chat_model("lightonocr-2-1b"), Served(fake_server, model="lightonai/LightOnOCR-2-1B", max_window=4))
    out = {d.id: d for d in step.run(iter([*docs, errored]))}
    assert set(out) == {"0", "1", "2", "3", "4", "bad"}
    assert len(FakeChat.seen) == 5 and {m for m, _ in FakeChat.seen} == {"lightonai/LightOnOCR-2-1B"}
    for i in range(5):
        d = out[str(i)]
        t = page_of(d).transcriptions["ocr"]
        w = round((1000 + 100 * i) * 1540 / 2000)
        assert t.extra["raw"] == f"\npage {w}x1540\n" and d.text == t.extra["raw"]
        assert t.model[0].measurements["completion_tokens"] == 3
        assert "errors" not in d.metadata
    assert "ocr" not in page_of(out["bad"]).transcriptions      # bypassed: an earlier step failed on it


def test_chat_page_step_records_server_errors(fake_server):
    # a route the server does not have: the page comes out with the error recorded, no transcription
    step = ChatPageStep(chat_model("lightonocr-2-1b"), Served(fake_server.replace("/v1", "/nope"), model="m", max_window=2))
    out = list(step.run(iter([new_page_document("p", image(100, 200))])))
    assert len(out) == 1 and out[0].metadata["errors"][0]["step"] == "page"
    assert "404" in out[0].metadata["errors"][0]["error"]
    assert "ocr" not in page_of(out[0]).transcriptions


def test_serve_block_outside_venv(monkeypatch):
    import os
    import sys

    own = os.path.join(sys.prefix, "bin")
    monkeypatch.setenv("PATH", os.pathsep.join([own, "/usr/local/bin", "/usr/bin"]))
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    block = ServeChatModel(chat_model("lightonocr-2-1b"), port=8123, outside_venv=True)
    cmd = block.launch_command()
    assert cmd[:4] == ["env", "-u", "VIRTUAL_ENV", "PATH=/usr/local/bin:/usr/bin"]
    assert cmd[4:] == block.command()
    assert ServeChatModel(chat_model("lightonocr-2-1b")).launch_command() == ServeChatModel(chat_model("lightonocr-2-1b")).command()


def test_minicpm_speculative_args_pin_the_draft():
    import json

    
    flag, config = chat_model("minicpm-ocr-1.0").speculative_args(chat_model("minicpm-ocr-1.0").draft_model, chat_model("minicpm-ocr-1.0").draft_revision)
    assert flag == "--speculative-config"
    assert json.loads(config) == {"method": "dspark", "model": "openbmb/MiniCPM-OCR-1.0-DSpark", "num_speculative_tokens": 15,
                                  "enable_adaptive_verification": False, "revision": chat_model("minicpm-ocr-1.0").draft_revision}


def test_job_dependencies_without_kraken():
    from linecaster.jobs import ROOT, dependencies

    deps = dependencies("abc123", ROOT / "recipes/vlm.py")
    assert any(d.startswith("linecaster-paddlex @ ") for d in deps)
    assert not any("kraken" in d or "lightning" in d or "git+" in d for d in deps)
    assert any(d.startswith("linecaster-kraken @ ") for d in dependencies("abc123", ROOT / "recipes/chain.py"))
