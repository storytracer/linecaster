"""Adapter ``minicpm-ocr``: openbmb/MiniCPM-OCR-1.0 as a region reader, run the way OpenBMB's SDK
(``minicpm-ocr`` 1.0.1) runs it (preset ``minicpm-ocr-1.0``).

The SDK finds PP-DocLayoutV3 regions, crops each one from the full-resolution page and sends the crop with the
prompt for its region type; it assembles the page as Markdown (tables HTML, formulas LaTeX). Here the layout
comes from linecaster's layout step and ``RegionRecognizer`` sends the crops. The preset holds the SDK's data
(``configs/minicpmvocr.yaml``, ``prompts.DEFAULT_PROMPT_MAP``, ``backends/dialects.build_vllm_payload``): the
prompt and token cap per region type (``settings.elements``, looked up by the layout model's own label,
``Region.raw_label`` = PP-DocLayoutV3's class name, the SDK's vocabulary; ``settings.default_element`` for
unknown types), the region types not read (``settings.skip_labels``), sampling, ``mm_processor_kwargs``,
the DSpark draft. This adapter holds the code:

* **Labels**: a region without a PP-DocLayoutV3 label is mapped from its Docling label (``FROM_DOCLING``).
* **Request**: the crop, then the prompt as a text part; the token cap clamped to max-model-len -
  ``settings.prompt_reserve`` as the SDK does; ``mm_processor_kwargs`` with the element's slice count;
  thinking off; PNG.
* **Crop**: from the full-resolution page (no page scaling, no padding), the box truncated to whole pixels as
  PaddleX's ``CropByBoxes`` does, pixels outside the region's polygon painted white
  (``layout_shape_mode="auto"``).
* **Assembly** (``assemble_markdown``): the SDK's own post-processing and Markdown assembly
  (``postprocess_content``, ``_normalize_and_dedupe_blocks``, ``assemble_markdown``), imported from the
  ``minicpm-ocr`` package (extra ``linecaster[minicpm-ocr]``; pure Python, no Paddle). The SDK leaves page
  numbers, headers, footers, footnotes and side notes out of the Markdown; ``keep_labels`` puts types back.
  Everything stays in the transcription either way: one line per read region with the raw completion.

Not reproduced (recorded in NOTES): the SDK's PaddleX box filtering (``filter_overlap_boxes``) and its merging
of aligned text blocks into one composite crop (``merge_blocks``).
"""
from __future__ import annotations

import base64
import io
import json
from typing import Any, ClassVar

from . import ChatAdapter, data_url

#: Docling labels -> the SDK's region type, for regions whose producer gave no PP-DocLayoutV3 label
FROM_DOCLING = {"title": "doc_title", "section_header": "paragraph_title", "caption": "figure_title",
                "page_header": "header", "page_footer": "footer", "formula": "display_formula",
                "picture": "image", "list_item": "text", "code": "algorithm", "document_index": "content"}
PRESET = "minicpm-ocr-1.0"


class MiniCPMOCRAdapter(ChatAdapter):
    adapter: ClassVar[str] = "minicpm-ocr"

    @property
    def skip_labels(self) -> tuple[str, ...]:
        return tuple(self.config.get("skip_labels") or ())

    @property
    def mm_processor_kwargs(self) -> dict[str, Any]:
        return dict(self.config.get("mm_processor_kwargs") or {})

    @property
    def max_model_len(self) -> int:
        return int(self.flag("--max-model-len"))

    def sdk_label(self, region) -> str:
        raw = region.raw_label or ""
        if raw in self.config["elements"] or raw in self.skip_labels:
            return raw
        return FROM_DOCLING.get(region.label, region.label)

    def element(self, label: str) -> dict:
        e = self.config["elements"].get(label) or self.config["default_element"]
        return {**e, "slice_nums": int(self.config["slice_nums"])}

    def speculative_args(self, draft: str, revision: str | None = None) -> list[str]:
        """Speculative decoding (DSpark, ``serve.draft.speculative``) with ``draft`` (a local
        directory, or a Hub id pinned by ``revision``)."""
        sp = dict(self.draft_config)
        config = {"method": sp.pop("method"), "model": draft, **sp}
        if revision:
            config["revision"] = revision
        return ["--speculative-config", json.dumps(config)]

    # ---------------------------------------------------------------- regions
    def reads_region(self, region, labels=None) -> bool:
        return self.sdk_label(region) not in self.skip_labels

    def crop_region(self, image, region, scale: float = 1.0, pad: int = 0):
        """PaddleX ``CropByBoxes`` with ``layout_shape_mode="auto"``: the box truncated to ints, outside
        the polygon white."""
        from PIL import Image, ImageDraw

        from ..data.geometry import bbox_of

        b = bbox_of(region.polygon)
        x0, y0, x1, y1 = int(b.x0), int(b.y0), int(b.x1), int(b.y1)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(image.width, max(x1, x0 + 1)), min(image.height, max(y1, y0 + 1))
        crop = image.crop((x0, y0, x1, y1))
        if region.polygon and len(region.polygon) >= 3:
            mask = Image.new("1", crop.size, 0)
            pts = [(int(p[0]) - x0, int(p[1]) - y0) for p in region.polygon]
            ImageDraw.Draw(mask).polygon(pts, fill=1, outline=1)
            white = Image.new("RGB", crop.size, (255, 255, 255))
            crop = Image.composite(crop, white, mask)
        return crop

    def request_region(self, crop: bytes, region=None) -> dict:
        label = self.sdk_label(region) if region is not None else "text"
        elem = self.element(label)
        max_tokens = min(int(elem["max_new_tokens"]), max(256, self.max_model_len - int(self.config["prompt_reserve"])))
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                data_url("image/png", base64.b64encode(crop).decode()),
                {"type": "text", "text": elem["prompt"]},
            ]}],
            "max_tokens": max_tokens,
            "mm_processor_kwargs": {**self.mm_processor_kwargs, "max_slice_nums": int(elem["slice_nums"])},
            "chat_template_kwargs": dict(self.config["chat_template_kwargs"]),
            **self.sampling,
        }

    def request(self, image: bytes) -> dict:
        """A whole page as one ``text`` region (not how the SDK uses the model; for ``PageRecognizer``)."""
        buf = io.BytesIO()
        from PIL import Image

        with Image.open(io.BytesIO(image)) as im:
            im.convert("RGB").save(buf, format="PNG")
        return self.request_region(buf.getvalue())

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "mm_processor_kwargs": self.mm_processor_kwargs,
                "prompts": self.config.get("prompts_source"), "crop": "full resolution, int box, polygon mask",
                "skipped": list(self.skip_labels)}

    # ---------------------------------------------------------------- assembly
    def region_blocks(self, t) -> list[dict]:
        """The SDK's result blocks from a transcription made by ``RegionRecognizer`` with this adapter: one per
        region (read or image), in reading order, ``content`` = the raw completion."""
        text_of = {ln.region_id: ln.text or "" for ln in t.lines}
        regions = sorted(t.regions, key=lambda r: (r.reading_order is None, r.reading_order or 0))
        blocks = []
        for order, r in enumerate(regions):
            label = self.sdk_label(r)
            if label not in self.skip_labels and r.id not in text_of:
                continue                                   # not read (a failed request, or another step's region)
            blocks.append({"label": label, "order": order, "raw": text_of.get(r.id, "")})
        return blocks

    def assemble_markdown(self, t, keep_labels=()) -> str:
        """The page's Markdown exactly as minicpm-ocr 1.0.1 assembles it (needs the ``minicpm-ocr`` package):
        each block post-processed (``postprocess_content``), normalised and de-duplicated
        (``_normalize_and_dedupe_blocks``), then ``assemble_markdown`` with the SDK's ignore list minus
        ``keep_labels``."""
        from minicpmvocr.pipeline._text import _normalize_and_dedupe_blocks
        from minicpmvocr.postprocess.markdown import assemble_markdown as sdk_assemble
        from minicpmvocr.postprocess.markdown import has_mixed_inline_formula_content, postprocess_content
        from minicpmvocr.prompts import DEFAULT_PROMPT_MAP

        blocks = []
        for b in self.region_blocks(t):
            fmt = self.element(b["label"])["output_format"]
            blocks.append({"label": b["label"], "order": b["order"], "status": "ok",
                           "content": postprocess_content(b["raw"], fmt, label=b["label"]),
                           "raw_content": b["raw"],
                           "inline_formula_mixed": b["label"] == "inline_formula"
                           and has_mixed_inline_formula_content(b["raw"])})
        prompt_map = {**DEFAULT_PROMPT_MAP, "markdown_assembly": {
            **DEFAULT_PROMPT_MAP["markdown_assembly"],
            "ignore_labels": [x for x in DEFAULT_PROMPT_MAP["markdown_assembly"]["ignore_labels"]
                              if x not in keep_labels]}}
        return sdk_assemble(_normalize_and_dedupe_blocks(blocks), prompt_map)


def _spec(spec):
    if spec is None:
        from . import chat_model

        return chat_model(PRESET)
    return spec


def sdk_label(region, spec: MiniCPMOCRAdapter | None = None) -> str:
    """The SDK's region type of ``region`` (``spec`` default: the ``minicpm-ocr-1.0`` preset)."""
    return _spec(spec).sdk_label(region)


def region_blocks(t, spec: MiniCPMOCRAdapter | None = None) -> list[dict]:
    return _spec(spec).region_blocks(t)


def assemble_markdown(t, keep_labels=(), spec: MiniCPMOCRAdapter | None = None) -> str:
    return _spec(spec).assemble_markdown(t, keep_labels)
