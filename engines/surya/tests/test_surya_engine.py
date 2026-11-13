"""linecaster-surya: the server flags the package implies, and the page's transcription from its blocks. The engine's
call needs a vLLM server with the checkpoint (a GPU): it is run by the pipeline (NOTES.md). Run in an environment
with the package (README: the test command)."""
import json
from pathlib import Path

import yaml

from linecaster_surya import SuryaRecognitionEngine, package_flags

PRESET = Path(__file__).resolve().parents[3] / "src/linecaster/catalog/data/presets/recognition/surya-ocr-2.5.yaml"


def test_the_preset_serves_with_the_package_s_flags():
    """The preset's vLLM flags are the ones the installed package's own launcher passes for its gpu_type."""
    preset = yaml.safe_load(PRESET.read_text())
    assert preset["serve"]["flags"] == package_flags(preset["options"]["gpu_type"])
    assert preset["serve"]["version"] == "0.25.1" and preset["serve"]["image"].startswith("vllm/vllm-openai:v0.25.1@")


def _block(html, error=False, label="Text"):
    return {"label": label, "raw_label": label, "reading_order": 0, "html": html, "skipped": False, "error": error,
            "confidence": None, "bbox": [0.0, 0.0, 1.0, 1.0]}


def test_the_transcription_keeps_the_blocks_verbatim():
    engine = SuryaRecognitionEngine()
    blocks = [_block("<h1>Title</h1>", label="SectionHeader"), _block("", label="Figure"), _block("<p>a</p>")]
    full = [{"prompt_type": "full", "raw": "<raw>", "finish_reason": "stop", "tokens": 30, "error": False}]
    t = engine.transcription(blocks, full, [])
    blocks_output, fullpage = t.outputs
    assert blocks_output.content == blocks and blocks_output.format == "json" and blocks_output.kept
    assert json.loads(json.dumps(blocks_output.content)) == blocks and t.text == "<h1>Title</h1>\n<p>a</p>"
    assert all(ln.reading.output == 0 for ln in t.lines)
    assert t.annotators[0].measurements == {"completion_tokens": 30, "finish_reason": "stop"}
    assert t.surya__fallback is False and (fullpage.content, fullpage.kept, fullpage.completion_tokens) == (
        "<raw>", False, 30)
    capped = engine.transcription([_block("<p>cut", error=True)], full,
                                  [{"prompt_type": "block", "raw": "", "finish_reason": "length", "tokens": 5,
                                    "error": False}])
    assert capped.outputs[0].finish_reason == "length" and capped.surya__fallback is True
    assert capped.surya__capped_blocks == 1 and capped.surya__requests == 2


def test_the_settings_go_to_the_package_by_environment():
    env = SuryaRecognitionEngine(endpoint="http://127.0.0.1:8001/v1").environment()
    assert env["SURYA_INFERENCE_URL"] == "http://127.0.0.1:8001/v1" and env["VLLM_GPU_TYPE"] == "a100-80"
    assert env["SURYA_FULLPAGE_REGEN"] == "false"
