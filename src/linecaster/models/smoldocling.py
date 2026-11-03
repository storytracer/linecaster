"""ds4sd/SmolDocling-256M-preview: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the board's saturate driver ``smoldocling-port.py`` (in the board's evaluation harness), a port
of Daniel van Strien's ``uv-scripts/ocr/smoldocling-ocr.py``; where the two differ, this follows the
driver:

* message = the page image FIRST, then the prompt ``Convert this page to docling.`` (the card's
  transformers/chat example). The order matters: the repo's chat template branches on
  ``content[0]['type'] == 'image'``;
* the image RGB-converted, downscaled (never upscaled) so its longest side is at most 2048 px
  (LANCZOS; the processor's own ``size.longest_edge``, so only the payload shrinks), sent as JPEG q95;
* sampling: temperature 0.0, max_tokens 6144 (the driver's choice, not the card's 8192: the native
  context is 8192 and an image takes up to ~1600 tokens), ``skip_special_tokens: false`` (DocTags'
  ``<doctag>`` and ``<loc_*>`` are added special tokens; vLLM's default strips them);
* serve flags: ``--max-model-len 8192`` (``max_position_embeddings``, not raisable),
  ``--no-enable-prefix-caching --mm-processor-cache-gb 0 --limit-mm-per-prompt '{"image": 1}'``; no
  ``--trust-remote-code`` (Idefics3 is registered in vLLM);
* model revision pinned to the board's checkpoint.

The model answers in DocTags, not Markdown. The completion is stored verbatim (``extra["raw"]``, the
lines), as the driver stores it. The board converts it before scoring, in the harness
(``runners/normalize_outputs.py``: ``strip_outer_whitespace`` then ``smoldocling_doctags_to_markdown``,
i.e. docling-core's ``DocTagsDocument`` -> ``DoclingDocument.load_from_doctags`` -> ``export_to_markdown``
with the furniture layer (running heads, page numbers) included and no image placeholder). ``parse``
does the same conversion into ``extra["markdown"]`` (docling-core is a core dependency); a conversion
that raises leaves ``extra["markdown"]`` ``None`` with ``extra["markdown_error"]``, so the raw completion
is never lost. The board converted without the page image (the harness's default; the Markdown does
not depend on it) and with docling-core 2.89; linecaster's lock has a newer docling-core.

The board's vLLM is 0.26.0 (``vllm/vllm-openai:v0.26.0``). ``--gpu-memory-utilization`` is the
deployment's choice (board 0.8 on an A10G) and not part of the spec.
"""
from __future__ import annotations

import base64
import io
from typing import Any, ClassVar

from . import ChatModel
from ..transcription.model import Transcription

PROMPT = "Convert this page to docling."
MAX_MODEL_LEN, MAX_TOKENS, LONGEST_EDGE = 8192, 6144, 2048


def jpeg_longest_at_most(image: bytes, longest: int, quality: int = 95) -> tuple[str, tuple[int, int]]:
    """RGB, downscaled (LANCZOS) only if the longest side exceeds ``longest``, base64 JPEG; and the size
    (the driver's ``encode_jpeg``)."""
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
    """The board's scored text for a SmolDocling completion: outer whitespace stripped, DocTags converted
    with docling-core as the harness does (``doctags_to_markdown``: body and furniture layers, empty image
    placeholder), stripped again. Empty DocTags give ``""``; docling-core does not raise on garbage."""
    from docling_core.types.doc import DoclingDocument
    from docling_core.types.doc.common.content_layer import ContentLayer
    from docling_core.types.doc.document import DocTagsDocument

    dt_doc = DocTagsDocument.from_doctags_and_image_pairs([doctags.strip()], None)
    doc = DoclingDocument.load_from_doctags(dt_doc, document_name="Document")
    return doc.export_to_markdown(included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE},
                                  image_placeholder="").strip()


class SmolDocling(ChatModel):
    model: ClassVar[str] = "ds4sd/SmolDocling-256M-preview"
    revision: ClassVar[str | None] = "ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8"
    longest_edge: ClassVar[int] = LONGEST_EDGE
    prompt: ClassVar[str] = PROMPT
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.0, "max_tokens": MAX_TOKENS, "skip_special_tokens": False}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", str(MAX_MODEL_LEN),
        "--no-enable-prefix-caching",
        "--mm-processor-cache-gb", "0",
        "--limit-mm-per-prompt", '{"image": 1}',
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        b64, _ = jpeg_longest_at_most(image, self.longest_edge)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": self.prompt},
            ]}],
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
                "image": {"format": "jpeg", "quality": 95, "longest_side_px_max": self.longest_edge,
                          "resize": "down only, LANCZOS"},
                "markdown": "docling-core DocTags -> export_to_markdown, body + furniture, no image placeholder"}
