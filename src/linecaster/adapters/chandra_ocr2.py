"""Adapter ``chandra-ocr``: Datalab's chandra-ocr client, ported (preset
``chandra-ocr-2``): ``chandra/model/vllm.py: generate_vllm`` of ``chandra-ocr`` v0.2.0.

* message = the page image, then ``settings.prompt`` as a text part (the ``ocr_layout`` prompt of
  ``chandra/prompts.py`` at v0.2.0, verbatim in the preset; its sha256 is checked against
  ``settings.prompt_sha256`` when the adapter is built);
* the image RGB-converted, scaled by the vendor's ``scale_to_fit`` (``chandra/model/util.py``, verbatim:
  pixel count clamped to ``max_size`` and up to ``min_size``, both sides snapped to multiples of ``grid``,
  LANCZOS; an image already on the grid and within bounds is untouched), then PNG;
* ONE attempt per page: the vendor client retries a page up to six times at a raised temperature when it
  detects a repetition loop; linecaster does not, so a loop shows as a loop.

The model answers with HTML layout blocks (``<div data-bbox=.. data-label=..>``), stored verbatim as the raw output
and read into the transcription by linecaster's HTML importer (``parse``): each block's content by HTML's semantics
(paragraphs, headings, lists, tables, formulas, emphasis), the running head and foot and footnotes by their labels
(``Page-Header``, ``Page-Footer``, ``Footnote`` as DPUB-ARIA roles), a ``Blank-Page`` block as nothing. The text is
the model's, read literally; nothing is dropped (the vendor's ``parse_markdown`` drops running heads and feet). The
blocks' boxes are not placed.
"""
from __future__ import annotations

import hashlib
from typing import Any, ClassVar

from ..data import Transcription
from ..errors import CatalogError
from . import ChatAdapter, data_url, png_bytes, text_lines

#: chandra's block labels that HTML's semantics do not tell, as the DPUB-ARIA roles the HTML importer reads
ROLES = {"Page-Header": "doc-pageheader", "Page-Footer": "doc-pagefooter", "Footnote": "doc-footnote"}


def read_layout(raw: str, t: Transcription, annotator: int) -> bool:
    """``raw`` (chandra's layout HTML) read into ``t`` by ``annotator``: True, or False when it holds no layout
    block (``t`` untouched)."""
    from lxml import html as H

    from ..formats.html import HtmlConverter

    try:
        root = H.fromstring(f"<html><body>{raw}</body></html>")
    except Exception:  # noqa: BLE001 - lxml refuses an empty or broken document
        return False
    body = root.find("body")
    blocks = [d for d in body if d.tag == "div" and d.get("data-label")] if body is not None else []
    if not blocks:
        return False
    for d in blocks:
        label = d.get("data-label")
        if label == "Blank-Page":
            d.drop_tree()
        elif label in ROLES:
            d.set("role", ROLES[label])
    HtmlConverter().read(root, t, annotator, annotator)
    return True


def scale_to_fit(img, max_size=(3072, 2048), min_size=(1792, 28), grid_size: int = 28):
    """chandra-ocr v0.2.0 ``chandra/model/util.py: scale_to_fit``, verbatim in behavior."""
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


class ChandraOCRAdapter(ChatAdapter):
    adapter: ClassVar[str] = "chandra-ocr"

    def __init__(self, preset, served_name=None):
        super().__init__(preset, served_name)
        digest = hashlib.sha256(self.prompt.encode()).hexdigest()
        if f"sha256:{digest}" != self.config["prompt_sha256"]:
            raise CatalogError(f"{self.preset}: the prompt differs from chandra-ocr v0.2.0's ocr_layout prompt")

    def scale(self, img):
        i = self.config["image"]
        return scale_to_fit(img, tuple(i["max_size"]), tuple(i["min_size"]), int(i["grid"]))

    def encode_png(self, image: bytes) -> tuple[str, tuple[int, int]]:
        """RGB, ``scale_to_fit``, base64 PNG; and the size sent."""
        from ..images.pixels import rgb_image

        img = self.scale(rgb_image(image))
        return png_bytes(img), img.size

    def request(self, image: bytes) -> dict:
        b64, _ = self.encode_png(image)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [data_url("image/png", b64), {"type": "text", "text": self.prompt}]}],
            **self.sampling,
        }

    def parse(self, body: dict, backend: str | None = None) -> Transcription:
        """The completion's layout blocks read by linecaster's HTML importer (``read_layout``); a completion without
        any (cut off before its first block) one line per text line, as the other adapters read theirs."""
        t = self.begin(body, backend)
        if not read_layout(t.outputs[0].content, t, 0):
            text_lines(t, 0, 0)
        return t

    def settings(self) -> dict[str, Any]:
        i = self.config["image"]
        (mw, mh), (nw, nh) = i["max_size"], i["min_size"]
        prefix = self.config["prompt_sha256"].removeprefix("sha256:")[:16]
        return {**super().settings(), "prompt": f"chandra-ocr v0.2.0 ocr_layout (sha256 {prefix}...)",
                "image": {"format": "png", "resize": f"chandra scale_to_fit (max {mw}x{mh} px, min {nw}x{nh} px, "
                                                      f"grid {i['grid']}), LANCZOS"},
                "attempts": 1}
