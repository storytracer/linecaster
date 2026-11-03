"""lightonai/LightOnOCR-3-4B and -0.8B: request, parse and serve flags exactly as the BHL OCR board ran them.

Source: the board's saturate driver for both rows (one driver, ``--model`` picks the checkpoint; the
two rows differ only in the model id and its pinned revision), itself following the model card:

* message = the page image ONLY, no text part (the card's transcription call, ``PROMPT = ""``;
  grounding is a different output and not run);
* the image RGB-converted and ``thumbnail((2048, 2048))``-ed, then PNG: the card's "target longest
  dimension of 2048px". ``thumbnail`` only ever downscales and keeps the aspect ratio, so a page
  smaller than 2048 px is sent as it is (unlike LightOnOCR-2's forced 1540 px);
* sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096, and thinking off per request
  (``chat_template_kwargs``) as well as server-side;
* serve flags: ``--max-model-len 16384`` (the board's; a 2048-px page is at most 4096 image tokens),
  ``--default-chat-template-kwargs '{"enable_thinking": false}'`` (card), ``--limit-mm-per-prompt
  '{"image": 1, "video": 0}' --mm-processor-cache-gb 0 --no-enable-prefix-caching``; no
  ``--trust-remote-code`` (the architecture is registered in vLLM);
* model revision pinned to the board's checkpoint, per size.

The completion is stored verbatim; the board's post-processing (a strip) stays in the harness. The board
ran vLLM 0.30.0 (``vllm/vllm-openai:v0.30.0``), not the board-wide 0.26.0: LightOn's repo says 0.27.1
makes these models loop. ``--gpu-memory-utilization`` is the deployment's choice (board 0.8 on an
A10G) and not part of the spec.
"""
from __future__ import annotations

import base64
import io
from typing import Any, ClassVar

from . import ChatModel


def png_thumbnail(image: bytes, longest: int) -> tuple[str, tuple[int, int]]:
    """RGB, ``thumbnail((longest, longest))`` (downscale only, Pillow's default filter), base64 PNG; and the size."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    img.thumbnail((longest, longest))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode(), img.size


class LightOnOCR3(ChatModel):
    model: ClassVar[str] = "lightonai/LightOnOCR-3-4B"
    revision: ClassVar[str | None] = "b71010f095dc3735de7ee6b9969bff8f8f50b39a"
    target_longest: ClassVar[int] = 2048
    page_longest: ClassVar[int | None] = 2048
    sampling: ClassVar[dict[str, Any]] = {"max_tokens": 4096, "temperature": 0.2, "top_p": 0.9}
    chat_template_kwargs: ClassVar[dict[str, Any]] = {"enable_thinking": False}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", "16384",
        "--default-chat-template-kwargs", '{"enable_thinking": false}',
        "--limit-mm-per-prompt", '{"image": 1, "video": 0}',
        "--mm-processor-cache-gb", "0",
        "--no-enable-prefix-caching",
    ]
    vllm_version: ClassVar[str | None] = "0.30.0"

    def request(self, image: bytes) -> dict:
        b64, _ = png_thumbnail(image, self.target_longest)
        return self._body(b64)

    def request_region(self, crop: bytes, region=None) -> dict:
        """A region crop, already at the page's scale: PNG as it is, no further resize."""
        return self._body(base64.b64encode(crop).decode())

    def _body(self, b64: str) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
            **self.sampling,
            "chat_template_kwargs": dict(self.chat_template_kwargs),
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "image": {"format": "png", "longest_side_px": self.target_longest,
                                                "resize": "thumbnail (down only), Pillow default filter"},
                "chat_template_kwargs": dict(self.chat_template_kwargs), "prompt": None}


class LightOnOCR3Small(LightOnOCR3):
    """The 0.8B checkpoint: everything as the 4B but the model id and its revision."""

    model: ClassVar[str] = "lightonai/LightOnOCR-3-0.8B"
    revision: ClassVar[str | None] = "36d8636925327c671bd8e479c517a004f7566bd9"
