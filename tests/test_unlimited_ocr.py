"""The Unlimited-OCR (vLLM) and Unlimited-OCR-2 (SGLang) specs as the BHL board's drivers ran them, and
ServeChatModel's SGLang path (command, environment, server packages, pin check)."""
from __future__ import annotations

import base64
import io
import json
import types

import pytest
from PIL import Image

from linecaster.blocks import serve as serve_mod
from linecaster.blocks.serve import ServeChatModel, check_default_branch
from linecaster.models import chat_model
from linecaster.models.unlimited_ocr import NGRAM_PROCESSOR, UnlimitedOCR, UnlimitedOCR2


def image(w: int, h: int, fmt: str, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), 200 if mode == "L" else (200, 190, 180)).save(buf, format=fmt)
    return buf.getvalue()


def completion(content, finish="stop"):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 3000, "completion_tokens": 120}}


def sent(body: dict) -> tuple[str, bytes]:
    head, b64 = body["messages"][0]["content"][0]["image_url"]["url"].split(",", 1)
    return head, base64.b64decode(b64)


# ------------------------------------------------------------- Unlimited-OCR
def test_v1_request_matches_the_driver():
    data = image(2400, 3600, "JPEG")
    body = chat_model("baidu/Unlimited-OCR").request(data)
    assert body["model"] == "baidu/Unlimited-OCR"
    assert body["messages"][0]["content"][1] == {"type": "text", "text": "document parsing."}
    assert (body["temperature"], body["max_tokens"], body["skip_special_tokens"]) == (0.0, 8192, False)
    assert body["vllm_xargs"] == {"ngram_size": 35, "window_size": 128}
    assert sent(body) == ("data:image/jpeg;base64", data)            # RGB JPEG: byte-for-byte


def test_v1_grey_page_becomes_full_size_rgb_png():
    head, raw = sent(UnlimitedOCR().request(image(3000, 4500, "PNG", "L")))
    with Image.open(io.BytesIO(raw)) as im:
        assert (head, im.mode, im.size) == ("data:image/png;base64", "RGB", (3000, 4500))


def test_v1_serve_args_keep_the_logits_processor_last():
    cmd = ServeChatModel(UnlimitedOCR(), port=8000, gpu_memory_utilization=0.8).command()
    assert cmd[:3] == ["vllm", "serve", "baidu/Unlimited-OCR"]
    args = cmd[7:]
    assert args[:2] == ["--revision", "07dea832e22aefee32ad281d4b80551282e1c168"]
    assert args[-2:] == ["--logits_processors", "vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor"]
    for flag in (["--max-model-len", "32768"], ["--mm-processor-cache-gb", "0"],
                 ["--limit-mm-per-prompt", '{"image": 1}'], ["--gpu-memory-utilization", "0.8"]):
        i = args.index(flag[0])
        assert args[i:i + 2] == flag
    assert {"--trust-remote-code", "--no-enable-prefix-caching"} <= set(args)


def test_v1_parse_is_verbatim_and_null_content_is_an_error():
    raw = "<｜begin▁of▁sentence｜><|det|>text [12, 30, 980, 64]<|/det|>PROCEEDINGS\n<|det|>image [0, 70, 990, 900]<|/det|>"
    t = UnlimitedOCR().parse(completion(raw, "length"))
    assert t.text == raw and t.extra["raw"] == raw and t.extra["finish_reason"] == "length"
    assert t.model[0].revision == UnlimitedOCR.revision
    with pytest.raises(ValueError, match="no content"):
        UnlimitedOCR().parse(completion(None))
    assert UnlimitedOCR().parse(completion("")).text == ""


# ----------------------------------------------------------- Unlimited-OCR-2
def test_v2_request_matches_the_driver():
    spec = chat_model("baidu/Unlimited-OCR-2")
    data = image(1800, 2600, "PNG")
    body = spec.request(data)
    assert body["model"] == "Unlimited-OCR-2"                       # the served name
    assert body["messages"][0]["content"][1] == {"type": "text", "text": "<PAGE><image>Multi page parsing."}
    assert sent(body) == ("data:image/png;base64", data)
    assert (body["max_tokens"], body["temperature"], body["skip_special_tokens"]) == (8000, 0.0, False)
    assert body["images_config"] == {"crop_mode": True}
    assert body["custom_params"] == {"ngram_size": 35, "window_size": 128, "page_token_id": 128827,
                                     "eos_token_id": 1, "max_page_tokens": 20000}
    assert body["custom_logit_processor"] == NGRAM_PROCESSOR
    import pickletools

    ops = [arg for _, arg, _ in pickletools.genops(bytes.fromhex(json.loads(NGRAM_PROCESSOR)["callable"]))]
    assert "sglang.srt.sampling.custom_logit_processor" in ops and "DeepseekOCRNoRepeatNGramLogitProcessor" in ops
    assert "vllm_xargs" not in body


def test_v2_sglang_command_and_environment(monkeypatch):
    import os
    import sys

    own = os.path.join(sys.prefix, "bin")
    monkeypatch.setenv("PATH", os.pathsep.join([own, "/opt/sglang/bin", "/usr/bin"]))
    monkeypatch.setenv("VIRTUAL_ENV", "/opt/sglang")   # the SGLang image sets it to its own environment: keep that
    block = ServeChatModel(UnlimitedOCR2(), port=8000, outside_venv=True)
    cmd = block.command("/opt/sglang/bin/python3")
    assert cmd[:10] == ["/opt/sglang/bin/python3", "-m", "sglang.launch_server", "--model-path", "baidu/Unlimited-OCR-2",
                        "--host", "127.0.0.1", "--port", "8000", "--enable-metrics"]
    args = cmd[10:]
    assert "--revision" not in args                                  # the server loads the default branch
    assert args[:2] == ["--served-model-name", "Unlimited-OCR-2"]
    assert args[2:] == UnlimitedOCR2.serve_args                      # the card's flags, nothing added
    assert "--gpu-memory-utilization" not in cmd
    assert block.command()[0] == "python3"
    launch = block.launch_command("/opt/sglang/bin/python3")
    assert launch[:4] == ["env", "-u", "VIRTUAL_ENV", "PATH=/opt/sglang/bin:/usr/bin"]
    assert "SGLANG_UOCR_EANABLE_DOC_LIMIT=1" in launch and "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True" in launch
    assert launch[-len(cmd):] == cmd
    # a deployment's memory share becomes SGLang's flag (after the spec's: the later one wins)
    assert ServeChatModel(UnlimitedOCR2(), gpu_memory_utilization=0.6).command()[-2:] == ["--mem-fraction-static", "0.6"]
    with pytest.raises(TypeError):
        UnlimitedOCR2().vllm_args()


def test_v2_server_packages_come_from_the_pinned_revision():
    block = ServeChatModel(UnlimitedOCR2())
    wheel, fastokens = block.install_commands("/opt/sglang/bin/python3")
    assert wheel == ["uv", "pip", "install", "-q", "--python", "/opt/sglang/bin/python3", "--no-deps",
                     "https://huggingface.co/baidu/Unlimited-OCR-2/resolve/9cf077c4b206e0e2a31879df937b0b0bcba3661c"
                     "/wheel/sglang-0.5.20.dev10%2Bg8d62f5fb9c-py3-none-any.whl"]
    assert fastokens[-1] == "fastokens==0.3.2"
    assert ServeChatModel(UnlimitedOCR()).install_commands("python3") == []


def fake_hub(monkeypatch, files: dict[str, dict[str, str]]):
    import huggingface_hub

    class Api:
        def model_info(self, model, revision=None, files_metadata=False):
            return types.SimpleNamespace(siblings=[types.SimpleNamespace(rfilename=k, blob_id=v)
                                                   for k, v in files[revision].items()])

    monkeypatch.setattr(huggingface_hub, "HfApi", Api)


def test_check_default_branch(monkeypatch):
    pinned = {"model.safetensors": "a", "config.json": "b", "README.md": "r1", "wheel/sglang-dev10.whl": "w1"}
    fake_hub(monkeypatch, {"pin": pinned, "main": {**pinned, "README.md": "r2", "wheel/sglang-dev13.whl": "w2"}})
    check_default_branch("m", "pin", UnlimitedOCR2.pin_ignore)       # README and wheels moved: fine
    fake_hub(monkeypatch, {"pin": pinned, "main": {**pinned, "config.json": "c"}})
    with pytest.raises(RuntimeError, match="config.json"):
        check_default_branch("m", "pin", UnlimitedOCR2.pin_ignore)
    fake_hub(monkeypatch, {"pin": pinned, "main": {**pinned, "tokenizer.json": "t"}})
    with pytest.raises(RuntimeError, match="tokenizer.json"):
        check_default_branch("m", "pin", UnlimitedOCR2.pin_ignore)


def test_serve_block_runs_sglang_after_installing_and_checking(monkeypatch):
    import saturate

    calls = []
    monkeypatch.setattr(serve_mod, "check_default_branch", lambda *a: calls.append(("check", a)))
    monkeypatch.setattr(ServeChatModel, "server_python", lambda self: "/opt/sglang/bin/python3")
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: calls.append(("run", cmd[:6])))

    class Engine:
        def __init__(self, model, engine, port, boot_timeout, cmd):
            calls.append(("engine", engine, cmd))

        def __enter__(self):
            calls.append(("up",))

        def __exit__(self, *exc):
            calls.append(("down",))

    monkeypatch.setattr(saturate, "Engine", Engine)
    block = ServeChatModel(UnlimitedOCR2(), port=8000, outside_venv=True)
    assert list(block.run(iter([1, 2]))) == [1, 2]
    assert calls[0] == ("check", ("baidu/Unlimited-OCR-2", UnlimitedOCR2.revision, UnlimitedOCR2.pin_ignore))
    assert [c[0] for c in calls] == ["check", "run", "run", "engine", "up", "down"]
    assert calls[1][1] == ["uv", "pip", "install", "-q", "--python", "/opt/sglang/bin/python3"]
    engine, cmd = calls[3][1], calls[3][2]
    assert engine == "sglang" and cmd[0] == "env" and "/opt/sglang/bin/python3" in cmd


def test_serve_block_vllm_spec_needs_no_preparation(monkeypatch):
    monkeypatch.setattr(serve_mod, "check_default_branch", lambda *a: pytest.fail("vLLM specs pass --revision"))
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("nothing to install"))
    assert ServeChatModel(UnlimitedOCR()).prepare() is None


def test_v2_settings_record_the_server():
    s = UnlimitedOCR2().parse(completion("<BLOCK>text[10, 20, 990, 60]<FORK>Shell 6 mm.")).model[0].settings
    assert s["server"] == "sglang" and s["server_env"]["SGLANG_UOCR_MAX_PAGE_TOKENS"] == "20000"
    assert s["custom_params"]["window_size"] == 128 and s["sampling"]["max_tokens"] == 8000


def test_server_python_takes_the_first_python_that_imports_sglang(monkeypatch, tmp_path):
    import os
    import stat

    from linecaster.blocks.serve import ServeChatModel

    bad, good = tmp_path / "venv" / "bin", tmp_path / "opt" / "bin"
    for d, code in ((bad, 1), (good, 0)):
        d.mkdir(parents=True)
        py = d / "python3"
        py.write_text(f"#!/bin/sh\nexit {code}\n")
        py.chmod(py.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bad), str(good), "/usr/bin"]))
    monkeypatch.setattr(ServeChatModel, "SERVER_PYTHONS", ())
    block = ServeChatModel(UnlimitedOCR2(), outside_venv=True)
    assert block.server_python() == str(good / "python3")
    good.joinpath("python3").write_text("#!/bin/sh\necho 'No module named sglang' >&2\nexit 1\n")
    with pytest.raises(RuntimeError, match="No module named sglang"):
        block.server_python()
