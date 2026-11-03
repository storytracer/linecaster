"""Qwen/Qwen3.5-9B: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the board's saturate driver ``qwen35-9b-port.py`` (in the board's evaluation harness), written
from the model card and the checkpoint's config (there is no uv-scripts recipe for this model). The
board row is "greedy + card penalties": the driver run with ``--prompt neutral`` (its default) and
``--card-penalties``:

* message = the page image, then the prompt as a text part (the card's order). The prompt is the
  driver's ``neutral`` variant, ``Transcribe all of the text in this image.``, a house choice: the card
  documents no OCR prompt. The board row is named by this variant (``prompt_sha8`` ``settings()``);
* the image RGB-converted and, only when it has more than 2048 x 1024 px (2048 visual tokens at 1024 px
  per token, the driver's ``VISUAL_TOKEN_BUDGET``), downscaled to that area keeping the aspect ratio
  (``int`` truncation, LANCZOS); then JPEG quality 95. Smaller pages are not upscaled;
* sampling: greedy (temperature 0.0, the board's deliberate deviation from the card) with the card's
  penalties restored (presence_penalty 1.5, repetition_penalty 1.0); no top_p/top_k/min_p, no seed;
  max_tokens 8192; thinking off per request (``chat_template_kwargs``: the shipped template opens a
  ``<think>`` block unless ``enable_thinking`` is false);
* serve flags: ``--max-model-len 16384 --max-num-batched-tokens 16384 --no-enable-prefix-caching
  --mm-processor-cache-gb 0 --limit-mm-per-prompt '{"image": 1, "video": 0}'``; no ``--reasoning-parser``
  (the card's serve line has one; the driver drops it so the completion stays in ``content``), no
  ``--trust-remote-code``;
* model revision pinned to the board's checkpoint.

The completion is stored verbatim; the board's post-processing (strip, ``unwrap_fence``, and the
non-empty check, which is a no-op since postproc 2) stays in the harness (``normalize_outputs``, keyed
on the model id); ``unwrap_fence`` here is the same rule for other consumers. The board's vLLM is 0.26.0
(``vllm/vllm-openai:v0.26.0``) on an L40S; ``--gpu-memory-utilization`` is the deployment's choice
(board 0.9) and not part of the spec.
"""
from __future__ import annotations

import base64
import hashlib
import io
import math
from typing import Any, ClassVar

from . import ChatModel

PROMPT = "Transcribe all of the text in this image."
PROMPT_VARIANT = "neutral"
VISUAL_TOKEN_BUDGET, PIXELS_PER_VISUAL_TOKEN = 2048, 1024
MAX_PIXELS = VISUAL_TOKEN_BUDGET * PIXELS_PER_VISUAL_TOKEN
JPEG_QUALITY = 95


def encode_jpeg(image: bytes) -> tuple[str, tuple[int, int]]:
    """The driver's ``encode_jpeg``: RGB, downscaled to ``MAX_PIXELS`` area if larger, JPEG q95; base64 and size."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    w, h = img.size
    if w * h > MAX_PIXELS:
        scale = math.sqrt(MAX_PIXELS / (w * h))
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode(), img.size


def unwrap_fence(text: str) -> str:
    """The board's ``unwrap_fence`` (applied after a strip): a reply wrapped whole in one ``` fence -> its body."""
    if not text.startswith("```") or not text.endswith("```") or text.count("```") != 2:
        return text
    body = text[3:-3]
    head, _, rest = body.partition("\n")
    return (rest if head.strip().isalpha() or not head.strip() else body).strip()


class Qwen35(ChatModel):
    model: ClassVar[str] = "Qwen/Qwen3.5-9B"
    revision: ClassVar[str | None] = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
    page_longest: ClassVar[int | None] = None       # an area budget, not a longest side
    prompt: ClassVar[str] = PROMPT
    sampling: ClassVar[dict[str, Any]] = {"max_tokens": 8192, "temperature": 0.0,
                                          "presence_penalty": 1.5, "repetition_penalty": 1.0}
    chat_template_kwargs: ClassVar[dict[str, Any]] = {"enable_thinking": False}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", "16384",
        "--max-num-batched-tokens", "16384",
        "--no-enable-prefix-caching",
        "--mm-processor-cache-gb", "0",
        "--limit-mm-per-prompt", '{"image": 1, "video": 0}',
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
        return {**super().settings(), "prompt": self.prompt, "prompt_variant": PROMPT_VARIANT,
                "prompt_sha8": hashlib.sha256(self.prompt.encode()).hexdigest()[:8],
                "chat_template_kwargs": dict(self.chat_template_kwargs),
                "image": {"format": "jpeg", "quality": JPEG_QUALITY, "max_pixels": MAX_PIXELS,
                          "resize": "area downscale only, LANCZOS"}}
