"""deepseek-ai/DeepSeek-OCR and DeepSeek-OCR-2: request, parse and serve flags exactly as the BHL OCR board ran them.

Source: the board's saturate drivers ``deepseek-ocr-port.py`` and ``deepseek-ocr2-port.py`` (in the board's
evaluation harness), ports of Daniel van Strien's ``uv-scripts/ocr/deepseek-ocr-vllm.py`` and
``deepseek-ocr2-vllm.py``; where they differ, this follows the drivers. The two drivers are twins (same
request, flags and sampling); the rows differ only in the model id and its pinned revision:

* grounded document mode: prompt ``<|grounding|>Convert the document to markdown.`` as a text part after
  the image (the recipe's raw ``<image>\\n<|grounding|>...`` prompt becomes image + text; the chat
  template inserts the image token);
* resolution mode: none is passed (no ``mm_processor_kwargs``), so vLLM's default applies: Gundam
  (base 1024, tiles of 640, crop mode, up to 6 crops), the mode the card recommends for documents;
* the image at full resolution, no resize: RGB PNG/JPEG bytes as they are, anything else converted to
  RGB and sent as PNG (the drivers' ``encode_image``, the same rule as dots.mocr's);
* sampling: temperature 0.0, max_tokens 4096 (8192 context minus the image), ``skip_special_tokens``
  false so the grounding tags survive in the completion;
* the card's n-gram repetition guard: ``--logits_processors
  vllm.model_executor.models.deepseek_ocr:NGramPerReqLogitsProcessor`` at boot (last on the command line:
  the flag takes a list) and ``vllm_xargs`` ``{"ngram_size": 30, "window_size": 90,
  "whitelist_token_ids": [128821, 128822]}`` per request (the whitelist is ``<td>``/``</td>`` in v1's
  tokenizer; v2 uses v1's processor and whitelist, as the v2 vLLM recipe does);
* serve flags: ``--max-model-len 8192`` (the native context), ``--trust-remote-code``,
  ``--no-enable-prefix-caching --mm-processor-cache-gb 0 --limit-mm-per-prompt '{"image": 1}'``;
* model revision pinned to the board's checkpoint, per version.

The completion is stored verbatim, grounding markup included (``<|ref|>label<|/ref|><|det|>[[x0, y0, x1,
y1]]<|/det|>`` before each block). The board's post-processing (strip, then ``deepseek_strip_grounding``,
added in postproc 3) stays in the harness (``normalize_outputs``, keyed on the model id);
``strip_grounding`` here is the same rule for other consumers. The board's vLLM is 0.26.0
(``vllm/vllm-openai:v0.26.0``) on an A10G; ``--gpu-memory-utilization`` is the deployment's choice (board
0.8) and not part of the spec.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from . import ChatModel
from .dots_mocr import encode_image

PROMPT = "<|grounding|>Convert the document to markdown."
LOGITS_PROCESSOR = "vllm.model_executor.models.deepseek_ocr:NGramPerReqLogitsProcessor"
NGRAM = {"ngram_size": 30, "window_size": 90, "whitelist_token_ids": [128821, 128822]}

# the board harness's patterns (normalize_outputs, postproc 3)
REF_SPAN_RE = re.compile(r"<\|ref\|>.*?<\|/ref\|>", re.DOTALL)
DET_SPAN_RE = re.compile(r"<\|det\|>.*?<\|/det\|>", re.DOTALL)
REF_RE = re.compile(r"<\|/?ref\|>")
RESIDUAL_MARKUP_RE = re.compile(r"<\s*[|｜][^|｜]{0,40}[|｜]\s*>")


def strip_grounding(raw: str) -> str:
    """The board's strip + ``deepseek_strip_grounding``: ref spans (with their labels), det spans and stray
    delimiters removed, runs of blank lines collapsed, stripped; surviving ``<|...|>`` markup raises."""
    text = REF_SPAN_RE.sub("", raw.strip())
    text = DET_SPAN_RE.sub("", text)
    text = REF_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if residue := RESIDUAL_MARKUP_RE.findall(text):
        raise ValueError(f"unhandled grounding markup survived strip: {residue[:5]}")
    return text


class DeepSeekOCR(ChatModel):
    model: ClassVar[str] = "deepseek-ai/DeepSeek-OCR"
    revision: ClassVar[str | None] = "9f30c71f441d010e5429c532364a86705536c53a"
    page_longest: ClassVar[int | None] = None       # full resolution; Gundam tiles it server-side
    prompt: ClassVar[str] = PROMPT
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.0, "max_tokens": 4096, "skip_special_tokens": False}
    vllm_xargs: ClassVar[dict[str, Any]] = NGRAM
    logits_processor: ClassVar[str] = LOGITS_PROCESSOR
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", "8192",
        "--trust-remote-code",
        "--no-enable-prefix-caching",
        "--mm-processor-cache-gb", "0",
        "--limit-mm-per-prompt", '{"image": 1}',
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        mime, b64 = encode_image(image)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
            "vllm_xargs": {k: (list(v) if isinstance(v, list) else v) for k, v in self.vllm_xargs.items()},
        }

    def vllm_args(self, gpu_memory_utilization: float | None = None, extra: list[str] | None = None) -> list[str]:
        """The spec's flags and overrides, then ``--logits_processors`` last (it takes a list, so nothing may follow it)."""
        return super().vllm_args(gpu_memory_utilization, extra) + ["--logits_processors", self.logits_processor]

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt, "resolution": "vLLM default (Gundam)",
                "logits_processor": self.logits_processor, "vllm_xargs": dict(self.vllm_xargs),
                "image": {"resize": None, "passthrough": "RGB PNG/JPEG", "else": "RGB PNG"}}


class DeepSeekOCR2(DeepSeekOCR):
    """DeepSeek-OCR-2: everything as v1 (the board's twin driver) but the model id and its revision."""

    model: ClassVar[str] = "deepseek-ai/DeepSeek-OCR-2"
    revision: ClassVar[str | None] = "aaa02f3811945a91062062994c5c4a3f4c0af2b0"
