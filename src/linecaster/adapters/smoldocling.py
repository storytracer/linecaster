"""Adapter ``smoldocling``: SmolDocling's DocTags answer (preset ``smoldocling-256m-preview``).

* message = the page image FIRST, then ``settings.prompt``. The order matters: the repo's chat template
  branches on ``content[0]['type'] == 'image'``;
* the image RGB-converted, downscaled (never upscaled) so its longest side is at most
  ``settings.image.longest_side_max`` (LANCZOS), sent as JPEG at ``settings.image.jpeg_quality``;
* ``skip_special_tokens`` false (in the preset's sampling): DocTags' ``<doctag>`` and ``<loc_*>`` are added
  special tokens, which vLLM's default strips.

The completion is stored verbatim (``extra["raw"]``, the lines). ``parse`` also converts it
into ``extra["markdown"]`` (docling-core's ``DocTagsDocument`` -> ``DoclingDocument.load_from_doctags`` ->
``export_to_markdown`` with the furniture layer and no image placeholder); a conversion that raises leaves
``extra["markdown"]`` ``None`` with ``extra["markdown_error"]``, so the raw completion is never lost.
"""
from __future__ import annotations

import base64
import io
from typing import Any, ClassVar

from ..data.transcription import Transcription
from . import ChatAdapter, data_url


def jpeg_longest_at_most(image: bytes, longest: int, quality: int = 95) -> tuple[str, tuple[int, int]]:
    """RGB, downscaled (LANCZOS) only if the longest side exceeds ``longest``, base64 JPEG; and the size."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    w, h = img.size
    if max(w, h) > longest:
        scale = longest / max(w, h)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode(), img.size


def to_markdown(doctags: str) -> str:
    """The page text of a SmolDocling completion: outer whitespace stripped, DocTags converted
    with docling-core (body and furniture layers, empty image placeholder), stripped again. Empty DocTags give
    ``""``; docling-core does not raise on garbage."""
    from docling_core.types.doc import DoclingDocument
    from docling_core.types.doc.common.content_layer import ContentLayer
    from docling_core.types.doc.document import DocTagsDocument

    dt_doc = DocTagsDocument.from_doctags_and_image_pairs([doctags.strip()], None)
    doc = DoclingDocument.load_from_doctags(dt_doc, document_name="Document")
    return doc.export_to_markdown(included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE},
                                  image_placeholder="").strip()


class SmolDoclingAdapter(ChatAdapter):
    adapter: ClassVar[str] = "smoldocling"

    @property
    def longest_edge(self) -> int:
        return int(self.config["image"]["longest_side_max"])

    @property
    def jpeg_quality(self) -> int:
        return int(self.config["image"]["jpeg_quality"])

    def request(self, image: bytes) -> dict:
        b64, _ = jpeg_longest_at_most(image, self.longest_edge, self.jpeg_quality)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [data_url("image/jpeg", b64), {"type": "text", "text": self.prompt}]}],
            **self.sampling,
        }

    def parse(self, body: dict, backend: str | None = None) -> Transcription:
        t = super().parse(body, backend=backend)
        try:
            t.extra["markdown"] = to_markdown(t.extra["raw"])
        except Exception as e:  # noqa: BLE001 - keep the page and its raw DocTags; record why
            t.extra["markdown"], t.extra["markdown_error"] = None, f"{type(e).__name__}: {e}"
        return t

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt, "order": "image, then text",
                "image": {"format": "jpeg", "quality": self.jpeg_quality, "longest_side_px_max": self.longest_edge,
                          "resize": "down only, LANCZOS"},
                "markdown": "docling-core DocTags -> export_to_markdown, body + furniture, no image placeholder"}
