"""Adapter ``chandra-ocr``: Datalab's chandra-ocr client as the BHL board's driver ports it (preset
``chandra-ocr-2``): ``chandra/model/vllm.py: generate_vllm`` of ``chandra-ocr`` v0.2.0.

* message = the page image, then ``settings.prompt`` as a text part (the ``ocr_layout`` prompt of
  ``chandra/prompts.py`` at v0.2.0, verbatim in the preset; its sha256 is checked against
  ``settings.prompt_sha256`` when the adapter is built, as the driver checks it);
* the image RGB-converted, scaled by the vendor's ``scale_to_fit`` (``chandra/model/util.py``, verbatim:
  pixel count clamped to ``max_size`` and up to ``min_size``, both sides snapped to multiples of ``grid``,
  LANCZOS; an image already on the grid and within bounds is untouched), then PNG;
* ONE attempt per page: the vendor client retries a page up to six times at a raised temperature when it
  detects a repetition loop; the board does not, so a loop shows as a loop.

The model answers with HTML layout blocks (``<div data-bbox=.. data-label=..>``), stored verbatim; the board
converts them to Markdown with the vendor's ``parse_markdown`` in its harness.
"""
from __future__ import annotations

import hashlib
import io
from typing import Any, ClassVar

from . import ChatModel, data_url, png_bytes


def scale_to_fit(img, max_size=(3072, 2048), min_size=(1792, 28), grid_size: int = 28):
    """chandra-ocr v0.2.0 ``chandra/model/util.py: scale_to_fit``, verbatim in behaviour."""
    from PIL import Image

    width, height = img.size
    if width <= 0 or height <= 0:
        return img
    original_ar = width / height
    current_pixels = width * height
    max_pixels = max_size[0] * max_size[1]
    min_pixels = min_size[0] * min_size[1]

    scale = 1.0
    if current_pixels > max_pixels:
        scale = (max_pixels / current_pixels) ** 0.5
    elif current_pixels < min_pixels:
        scale = (min_pixels / current_pixels) ** 0.5

    w_blocks = max(1, round((width * scale) / grid_size))
    h_blocks = max(1, round((height * scale) / grid_size))

    while (w_blocks * h_blocks * grid_size * grid_size) > max_pixels:
        if w_blocks == 1 and h_blocks == 1:
            break
        if w_blocks == 1:
            h_blocks -= 1
            continue
        if h_blocks == 1:
            w_blocks -= 1
            continue
        ar_w_loss = abs(((w_blocks - 1) / h_blocks) - original_ar)
        ar_h_loss = abs((w_blocks / (h_blocks - 1)) - original_ar)
        if ar_w_loss < ar_h_loss:
            w_blocks -= 1
        else:
            h_blocks -= 1

    new_width, new_height = w_blocks * grid_size, h_blocks * grid_size
    if (new_width, new_height) == (width, height):
        return img
    return img.resize((new_width, new_height), resample=Image.Resampling.LANCZOS)


class ChandraOCR(ChatModel):
    adapter: ClassVar[str] = "chandra-ocr"

    def __init__(self, preset, served_name=None):
        super().__init__(preset, served_name)
        digest = hashlib.sha256(self.prompt.encode()).hexdigest()
        if f"sha256:{digest}" != self.config["prompt_sha256"]:
            raise ValueError(f"{self.preset}: the prompt differs from chandra-ocr v0.2.0's ocr_layout prompt")

    def scale(self, img):
        i = self.config["image"]
        return scale_to_fit(img, tuple(i["max_size"]), tuple(i["min_size"]), int(i["grid"]))

    def encode_png(self, image: bytes) -> tuple[str, tuple[int, int]]:
        """The driver's ``encode_png``: RGB, ``scale_to_fit``, base64 PNG; and the size sent."""
        from PIL import Image

        with Image.open(io.BytesIO(image)) as im:
            img = self.scale(im.convert("RGB"))
        return png_bytes(img), img.size

    def request(self, image: bytes) -> dict:
        b64, _ = self.encode_png(image)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [data_url("image/png", b64), {"type": "text", "text": self.prompt}]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        i = self.config["image"]
        (mw, mh), (nw, nh) = i["max_size"], i["min_size"]
        prefix = self.config["prompt_sha256"].removeprefix("sha256:")[:16]
        return {**super().settings(), "prompt": f"chandra-ocr v0.2.0 ocr_layout (sha256 {prefix}...)",
                "image": {"format": "png", "resize": f"chandra scale_to_fit (max {mw}x{mh} px, min {nw}x{nh} px, "
                                                      f"grid {i['grid']}), LANCZOS"},
                "attempts": 1}
