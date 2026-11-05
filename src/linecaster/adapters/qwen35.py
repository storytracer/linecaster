"""Adapter ``qwen3.5``: Qwen3.5 as a page reader (preset ``qwen3.5-9b``, the board's "greedy + card penalties"
row). The request is Ovis-OCR's (``ovis_ocr.OvisOCRAdapter``: image as JPEG, area-capped, then the prompt;
``chat_template_kwargs`` with thinking off: the shipped template opens a ``<think>`` block unless
``enable_thinking`` is false); the record names the prompt variant (``settings.prompt_variant``) and its
hash, by which the board names the row.

The completion is stored verbatim; ``unwrap_fence`` is the board harness's rule for a reply wrapped whole in
one code fence, for other consumers.
"""
from __future__ import annotations

import hashlib
from typing import Any, ClassVar

from .ovis_ocr import OvisOCRAdapter


def unwrap_fence(text: str) -> str:
    """The board's ``unwrap_fence`` (applied after a strip): a reply wrapped whole in one ``` fence -> its body."""
    if not text.startswith("```") or not text.endswith("```") or text.count("```") != 2:
        return text
    body = text[3:-3]
    head, _, rest = body.partition("\n")
    return (rest if head.strip().isalpha() or not head.strip() else body).strip()


class Qwen35Adapter(OvisOCRAdapter):
    adapter: ClassVar[str] = "qwen3.5"

    def settings(self) -> dict[str, Any]:
        s = super().settings()
        s["image"]["resize"] = "area downscale only, LANCZOS"
        return {"sampling": s["sampling"], "serve_args": s["serve_args"], "prompt": self.prompt,
                "prompt_variant": self.config.get("prompt_variant"),
                "prompt_sha8": hashlib.sha256(self.prompt.encode()).hexdigest()[:8],
                "chat_template_kwargs": self.chat_template_kwargs, "image": s["image"]}
