"""ATH-MaaS/OvisOCR2 and OvisOCR3: request, parse and serve flags exactly as the BHL OCR board ran them.

Source: the board's saturate drivers ``ovis-ocr2-port.py`` (a port of Daniel van Strien's
``uv-scripts/ocr/ovis-ocr2-server.py``) and ``ovis-ocr3-port.py`` (the OvisOCR2 driver with the model, its
pinned revision and the prompt file of the OvisOCR3 card; every other value identical); where driver and
recipe differ, the driver wins:

* message = the page image, then the card's Markdown OCR prompt as a text part. OvisOCR2's prompt starts
  with a newline (the server recipe's); OvisOCR3's is ``prompts/document_markdown.txt`` from the model
  repo at the pinned revision, the same text without the leading newline;
* the image RGB-converted, downscaled with LANCZOS to at most 8,294,400 px (2880 x 2880, the processor's
  ``max_pixels``; sides ``int(w * s)``, ``int(h * s)`` with ``s = sqrt(max / (w * h))``) and never
  upscaled, then re-encoded as JPEG quality 95 (every image, also when it fits);
* sampling: temperature 0.0, max_tokens 16384, thinking off per request (``chat_template_kwargs``);
* serve flags: ``--max-model-len 32768 --no-enable-prefix-caching --mm-processor-cache-gb 0
  --limit-mm-per-prompt '{"image": 1}' --mm-processor-kwargs '{"images_kwargs": {"min_pixels": 200704,
  "max_pixels": 8294400}}'``; no ``--trust-remote-code``;
* model revision pinned to the board's checkpoint, per model.

The completion is stored verbatim, ``<img src="images/bbox_...">`` placeholders and all: the board drops
those blocks after a strip in the harness (``normalize_outputs``: ``drop_bbox_blocks``, keyed on the model
id), not in the driver. The card's ``clean_truncated_repeats`` trimmer is not applied (the board's
documented deviation). The board's vLLM is 0.26.0 (``vllm/vllm-openai:v0.26.0``) for both; the OvisOCR3
card runs vLLM 0.22.1 with ``gdn_prefill_backend="triton"``, the board the default backend.
``--gpu-memory-utilization`` is the deployment's choice (board 0.8; OvisOCR2 on an A10G, OvisOCR3 on an
A100) and not part of the spec.
"""
from __future__ import annotations

import base64
import io
import math
from typing import Any, ClassVar

from . import ChatModel

PROMPT = (
    "Extract all readable content from the image in natural human reading order "
    "and output the result as a single Markdown document. For charts or images, "
    'represent them using an HTML image tag: <img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, '
    "where left, top, right, bottom are bounding box coordinates scaled to [0, 1000). "
    "Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all other text as standard Markdown. Preserve the original text "
    "without translation or paraphrasing."
)
MIN_PIXELS, MAX_PIXELS = 200704, 8294400
MAX_MODEL_LEN, MAX_TOKENS = 32768, 16384
JPEG_QUALITY = 95


def encode_jpeg(image: bytes, max_pixels: int = MAX_PIXELS) -> tuple[str, tuple[int, int]]:
    """The driver's ``encode_jpeg``: RGB, downscaled to ``max_pixels`` (LANCZOS), JPEG q95; and the size."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    w, h = img.size
    if w * h > max_pixels:
        scale = math.sqrt(max_pixels / (w * h))
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode(), img.size


class OvisOCR2(ChatModel):
    model: ClassVar[str] = "ATH-MaaS/OvisOCR2"
    revision: ClassVar[str | None] = "65c619d374b55d4152e85150fc1b003700bc1f0c"
    prompt: ClassVar[str] = "\n" + PROMPT
    page_longest: ClassVar[int | None] = None       # pixel-count bound, not a longest side
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.0, "max_tokens": MAX_TOKENS}
    chat_template_kwargs: ClassVar[dict[str, Any]] = {"enable_thinking": False}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", str(MAX_MODEL_LEN),
        "--no-enable-prefix-caching",
        "--mm-processor-cache-gb", "0",
        "--limit-mm-per-prompt", '{"image": 1}',
        "--mm-processor-kwargs",
        f'{{"images_kwargs": {{"min_pixels": {MIN_PIXELS}, "max_pixels": {MAX_PIXELS}}}}}',
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        b64, _ = encode_jpeg(image)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
            "chat_template_kwargs": dict(self.chat_template_kwargs),
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt, "chat_template_kwargs": dict(self.chat_template_kwargs),
                "image": {"format": "jpeg", "quality": JPEG_QUALITY, "max_pixels": MAX_PIXELS,
                          "resize": "down only, LANCZOS"}}


class OvisOCR3(OvisOCR2):
    """OvisOCR3 (Qwen3.5-0.8B base): everything as OvisOCR2 but the model id, its revision and the prompt
    file's text (no leading newline)."""

    model: ClassVar[str] = "ATH-MaaS/OvisOCR3"
    revision: ClassVar[str | None] = "5f6ce6932efee9ec10c30746db55bd780214b7fd"
    prompt: ClassVar[str] = PROMPT
