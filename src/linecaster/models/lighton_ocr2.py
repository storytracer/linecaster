"""lightonai/LightOnOCR-2-1B: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the saturate driver that produced the board row (in the board's evaluation harness), itself a
port of Daniel van Strien's ``uv-scripts/ocr/lighton-ocr2-saturate.py``:

* message = the page image ONLY, no text part (LightOnOCR-2's trained format, per the card);
* the image re-encoded as PNG with the longest side forced to exactly 1540 px, in both directions
  (the card's "target longest dimension of 1540px", ``processor_config`` longest_edge 1540);
* sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096;
* serve flags: the card's three (``--limit-mm-per-prompt '{"image": 1}' --mm-processor-cache-gb 0
  --no-enable-prefix-caching``) plus ``--max-model-len 16384`` (the board's; the model's native
  context); no ``--trust-remote-code`` (the architecture is registered in vLLM);
* model revision pinned to the board's checkpoint.

The completion is stored verbatim; the board's post-processing (a strip) stays in the harness. The board's vLLM is 0.26.0 (``vllm/vllm-openai:v0.26.0``);
``--gpu-memory-utilization`` is the deployment's choice (board 0.8 on an A10G) and not part of the spec.
"""
from __future__ import annotations

from typing import Any, ClassVar

from . import ChatModel, png_longest


class LightOnOCR2(ChatModel):
    model: ClassVar[str] = "lightonai/LightOnOCR-2-1B"
    revision: ClassVar[str | None] = "c97bd377f04481830395218fa8951df9deaba756"
    target_longest: ClassVar[int] = 1540
    page_longest: ClassVar[int | None] = 1540
    sampling: ClassVar[dict[str, Any]] = {"max_tokens": 4096, "temperature": 0.2, "top_p": 0.9}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", "16384",
        "--limit-mm-per-prompt", '{"image": 1}',
        "--mm-processor-cache-gb", "0",
        "--no-enable-prefix-caching",
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        b64, _ = png_longest(image, self.target_longest)
        return self._body(b64)

    def request_region(self, crop: bytes, region=None) -> dict:
        """A region crop, already at the page's 1540-px scale: PNG as it is, no further resize."""
        import base64

        return self._body(base64.b64encode(crop).decode())

    def _body(self, b64: str) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "image": {"format": "png", "longest_side_px": self.target_longest,
                                                "resize": "forced (up and down), LANCZOS"},
                "prompt": None}
