"""Adapter ``deepseek-ocr``: DeepSeek-OCR and DeepSeek-OCR-2 in grounded document mode (presets
``deepseek-ocr``, ``deepseek-ocr-2``; the board's twin drivers differ only in the checkpoint).

* the ``dots`` request (image at full resolution, passthrough; then the prompt as a text part, the chat
  template inserting the image token), with the card's n-gram repetition guard: ``settings.vllm_xargs`` per
  request and ``settings.logits_processor`` registered at boot, last on the command line;
* no resolution mode is passed (no ``mm_processor_kwargs``), so vLLM's default applies: Gundam;
* ``skip_special_tokens`` false (in the preset's sampling), so the grounding tags survive in the completion.

The completion is stored verbatim, grounding markup included (``<|ref|>label<|/ref|><|det|>[[x0, y0, x1,
y1]]<|/det|>`` before each block). ``strip_grounding`` is the board harness's rule for removing it
(``normalize_outputs``, postproc 3), for consumers that want the text without it.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from .dots import DotsAdapter

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


class DeepSeekOCRAdapter(DotsAdapter):
    adapter: ClassVar[str] = "deepseek-ocr"

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "resolution": "vLLM default (Gundam)",
                "logits_processor": self.logits_processor, "vllm_xargs": dict(self.config["vllm_xargs"])}
