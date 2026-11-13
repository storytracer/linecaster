"""The Nemotron 3.5 Parse spec: request, serve flags, plugin setup and parse, after the model card."""
from __future__ import annotations

import base64
import io
import subprocess

from PIL import Image

from linecaster.adapters import chat_model
from linecaster.adapters.nemotron_parse35 import strip_underscore_emphasis
from linecaster.blocks.servers.serve import ChatModelServer

PROMPT = chat_model("nemotron-3.5-parse").prompt

MODEL = "nvidia/Nemotron-3.5-Parse"
REV = "62cb1e4ba153d113ff64aaf2be6e068c377cf53c"


def image(w: int, h: int, fmt: str = "WEBP") -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), 200).save(buf, format=fmt)
    return buf.getvalue()


def test_request_is_prompt_then_full_size_png_with_card_sampling():
    b = chat_model(MODEL).request(image(2400, 3600))
    text_part, image_part = b["messages"][0]["content"]
    assert text_part == {"type": "text", "text": PROMPT}
    assert PROMPT == "</s><s><predict_bbox><predict_classes><output_markdown><predict_text_in_pic>"
    url = image_part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    im = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert im.format == "PNG" and im.mode == "RGB" and im.size == (2400, 3600)
    assert (b["temperature"], b["top_k"], b["repetition_penalty"], b["max_tokens"]) == (0.0, 1, 1.1, 8744)
    assert b["skip_special_tokens"] is False
    assert set(b) == {"model", "messages", "temperature", "top_k", "repetition_penalty", "max_tokens",
                      "skip_special_tokens"}


def test_serve_args_match_the_card():
    args = chat_model("nemotron-3.5-parse").vllm_args(0.8)
    assert args[:2] == ["--revision", REV]
    expect = ["--max-model-len", "16384", "--trust-remote-code", "--dtype", "bfloat16",
              "--distributed-executor-backend", "uni", "--max-num-seqs", "192", "--max-num-batched-tokens",
              "16384", "--no-enable-prefix-caching", "--limit-mm-per-prompt", '{"image": 1}',
              "--attention-config", '{"flash_attn_version": 3}']
    assert args[2:2 + len(expect)] == expect and args[-2:] == ["--gpu-memory-utilization", "0.8"]
    # context: worst-case image tokens + output + prompt fit
    assert (2048 // 16) * ((1664 // 16) // 4) + 1 + 8744 + 64 <= 16384


def test_serve_command_installs_the_plugin_before_vllm(tmp_path):
    cmd = ChatModelServer(chat_model("nemotron-3.5-parse"), port=8123, gpu_memory_utilization=0.8).command()
    assert cmd[:2] == ["bash", "-c"]
    script = cmd[2]
    assert f"revision='{REV}'" in script and "inference.constraints.txt" in script
    assert "grep -v '^nemotron-parse=='" in script
    assert 'uv pip install --system --python "$PY" --constraint /tmp/np-constraints.txt /tmp/np' in script
    assert "assert vllm.__version__ == '0.26.0'" in script
    assert script.splitlines()[-1].startswith(f"exec vllm serve {MODEL} --host 127.0.0.1 --port 8123 --revision {REV}")
    assert subprocess.run(["bash", "-n", "-c", script]).returncode == 0
    # the interpreter is read from the server command's shebang
    fake = tmp_path / "vllm"
    fake.write_text("#!/usr/bin/python3\n")
    fake.chmod(0o755)
    probe = "\n".join(script.splitlines()[:4]) + '\necho "$PY"'
    out = subprocess.run(["bash", "-c", probe.replace("VLLM=vllm", f"VLLM={fake}")], capture_output=True, text=True)
    assert out.stdout.strip() == "/usr/bin/python3"


def test_parse_keeps_the_block_stream_verbatim():
    raw = "<x_0.1><y_0.1>_Corvus corax_ L.<x_0.9><y_0.2><class_Text>"
    body = {"choices": [{"message": {"content": raw}, "finish_reason": "stop"}], "usage": {}}
    t = chat_model("nemotron-3.5-parse").parse(body)
    assert t.outputs[0].content == raw and t.text == raw
    assert t.annotators[0].settings["sampling"]["repetition_penalty"] == 1.1


def test_strip_underscore_emphasis():
    assert strip_underscore_emphasis("_Corvus corax_ and column_1 and ___") == "Corvus corax and column_1 and ___"
