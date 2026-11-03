"""openbmb/MiniCPM-OCR-1.0: a region reader, run the way OpenBMB's SDK (``minicpm-ocr`` 1.0.1) runs it.

The SDK finds PP-DocLayoutV3 regions, crops each one from the full-resolution page and sends the crop
with the prompt for its region type; it assembles the page as Markdown (tables HTML, formulas LaTeX).
Here the layout comes from linecaster's layout step and ``ChatRegionStep`` sends the crops; this spec
holds everything model-specific, taken from the SDK's bundled config (``configs/minicpmvocr.yaml``,
``prompts.DEFAULT_PROMPT_MAP``, ``backends/dialects.build_vllm_payload``,
``layouts/ppdoclayout3_paddlex``):

* **Prompt and token cap per region type**, looked up by the layout model's own label
  (``Region.raw_label`` = PP-DocLayoutV3's class name, the SDK's vocabulary): ``Text Recognition:``
  for text-like regions, ``Table Recognition:`` (8192 tokens), ``Formula Recognition:`` for display
  formulas, ``Chart to Table:``, ``Seal Recognition:``; unknown types get the SDK default
  (``Text Recognition:``, 8192). Caps are clamped to max-model-len - 512 as the SDK does (no effect at
  40960).
* **Request**: the image, then the prompt as a text part; ``mm_processor_kwargs``
  ``{"downsample_mode": "4x", "max_slice_nums": 9}``; thinking off; temperature 0.01, top_p 0.001,
  top_k 1, repetition_penalty 1.0, no_repeat_ngram_size 100. PNG.
* **Which regions are read**: all but the image types (``image``, ``header_image``,
  ``footer_image``); charts and seals are read (the SDK's chart and seal recognition are on).
* **Crop**: from the full-resolution page (no page scaling, no padding), the box truncated to whole
  pixels as PaddleX's ``CropByBoxes`` does, pixels outside the region's polygon painted white
  (``layout_shape_mode="auto"``).
* **Assembly** (``assemble_markdown``): the SDK's own post-processing and Markdown assembly
  (``postprocess_content``, ``_normalize_and_dedupe_blocks``, ``assemble_markdown``), imported from
  the ``minicpm-ocr`` package (extra ``linecaster[minicpm-ocr]``; pure Python, no Paddle). The SDK
  leaves page numbers, headers, footers, footnotes and side notes out of the Markdown;
  ``keep_labels`` puts types back (the BHL board row kept ``footnote`` and ``aside_text``). Everything
  stays in the transcription either way: one line per read region with the raw completion.

Not reproduced (recorded in NOTES): the SDK's PaddleX box filtering (``filter_overlap_boxes``) and its
merging of aligned text blocks into one composite crop (``merge_blocks``); linecaster's layout step
runs PP-DocLayoutV3's ONNX export with its own containment suppression, the SDK runs it on
PaddlePaddle.
"""
from __future__ import annotations

import base64
import io
from typing import Any, ClassVar

from . import ChatModel

DEFAULT = {"prompt": "Text Recognition:", "max_new_tokens": 8192, "output_format": "text", "slice_nums": 9}
T, TAB, F = "Text Recognition:", "Table Recognition:", "Formula Recognition:"
#: minicpm-ocr 1.0.1 ``DEFAULT_PROMPT_MAP["element_prompts"]``: label -> (prompt, max_new_tokens, output_format)
ELEMENTS: dict[str, tuple[str, int, str]] = {
    "text": (T, 4096, "text"), "content": (T, 4096, "text"), "abstract": (T, 4096, "text"),
    "reference": (T, 2048, "text"), "reference_content": (T, 2048, "text"), "vertical_text": (T, 2048, "text"),
    "vision_footnote": (T, 1024, "text"), "algorithm": (T, 4096, "text"), "doc_title": (T, 512, "text"),
    "paragraph_title": (T, 512, "text"), "figure_title": (T, 512, "text"), "table": (TAB, 8192, "html"),
    "display_formula": (F, 2048, "latex"), "inline_formula": (T, 1024, "latex"), "formula_number": (T, 256, "text"),
    "header": (T, 512, "text"), "footer": (T, 512, "text"), "footnote": (T, 1024, "text"),
    "aside_text": (T, 1024, "text"), "number": (T, 256, "text"), "chart": ("Chart to Table:", 4096, "html"),
    "seal": ("Seal Recognition:", 256, "text"),
}
IMAGE_LABELS = ("image", "header_image", "footer_image")
#: Docling labels -> the SDK's region type, for regions whose producer gave no PP-DocLayoutV3 label
FROM_DOCLING = {"title": "doc_title", "section_header": "paragraph_title", "caption": "figure_title",
                "page_header": "header", "page_footer": "footer", "formula": "display_formula",
                "picture": "image", "list_item": "text", "code": "algorithm", "document_index": "content"}
#: minicpm-ocr 1.0.1 ``markdown_assembly.ignore_labels``
SDK_IGNORED_LABELS = ("number", "footnote", "header", "footer", "aside_text")
MAX_MODEL_LEN, PROMPT_RESERVE = 40960, 512


def sdk_label(region) -> str:
    raw = region.raw_label or ""
    if raw in ELEMENTS or raw in IMAGE_LABELS:
        return raw
    return FROM_DOCLING.get(region.label, region.label)


def element(label: str) -> dict:
    if label in ELEMENTS:
        prompt, cap, fmt = ELEMENTS[label]
        return {"prompt": prompt, "max_new_tokens": cap, "output_format": fmt, "slice_nums": 9}
    return dict(DEFAULT)


class MiniCPMOCR(ChatModel):
    model: ClassVar[str] = "openbmb/MiniCPM-OCR-1.0"
    revision: ClassVar[str | None] = "a59a4acf215e34c6d73149e9eafdb88ed2086e39"
    draft_model: ClassVar[str] = "openbmb/MiniCPM-OCR-1.0-DSpark"
    draft_revision: ClassVar[str] = "31e3feaf80e0061cd6aa73db23480d2d691d6452"
    step: ClassVar[str] = "regions"
    page_longest: ClassVar[int | None] = None       # crops from the full-resolution page
    region_pad: ClassVar[int] = 0
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.01, "top_p": 0.001, "top_k": 1, "repetition_penalty": 1.0,
                                          "no_repeat_ngram_size": 100}
    mm_processor_kwargs: ClassVar[dict[str, Any]] = {"downsample_mode": "4x", "max_slice_nums": 9}
    # OpenBMB's SDK tutorial (docs/minicpmvocr_tutorial_en.md), as in the board job; speculative decoding
    # (DSpark) is added by ``speculative_args``
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", str(MAX_MODEL_LEN), "--max-num-batched-tokens", str(MAX_MODEL_LEN), "--max-num-seqs", "32",
        "--limit-mm-per-prompt", '{"image":36,"video":0}', "--mm-processor-kwargs", '{"downsample_mode":"4x"}',
        "--trust-request-mm-kwargs", "--default-chat-template-kwargs", '{"enable_thinking":false}',
    ]
    vllm_version: ClassVar[str | None] = "0.32.1rc1.dev602+g5d35ce393 (nightly 5d35ce3)"

    def __init__(self, served_name: str | None = None):
        super().__init__(served_name or "minicpm-ocr")

    @staticmethod
    def speculative_args(draft: str, revision: str | None = None) -> list[str]:
        """DSpark speculative decoding with ``draft`` (a local directory, or a Hub id pinned by ``revision``)."""
        import json

        config = {"method": "dspark", "model": draft, "num_speculative_tokens": 15, "enable_adaptive_verification": False}
        if revision:
            config["revision"] = revision
        return ["--speculative-config", json.dumps(config)]

    # ---------------------------------------------------------------- regions
    def reads_region(self, region, labels=None) -> bool:
        return sdk_label(region) not in IMAGE_LABELS

    def crop_region(self, image, region, scale: float = 1.0, pad: int = 0):
        """PaddleX ``CropByBoxes`` with ``layout_shape_mode="auto"``: the box truncated to ints, outside
        the polygon white."""
        from PIL import Image, ImageDraw

        from ..geometry import bbox_of

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
        label = sdk_label(region) if region is not None else "text"
        elem = element(label)
        max_tokens = min(int(elem["max_new_tokens"]), max(256, MAX_MODEL_LEN - PROMPT_RESERVE))
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(crop).decode()}},
                {"type": "text", "text": elem["prompt"]},
            ]}],
            "max_tokens": max_tokens,
            "mm_processor_kwargs": {**self.mm_processor_kwargs, "max_slice_nums": int(elem["slice_nums"])},
            "chat_template_kwargs": {"enable_thinking": False},
            **self.sampling,
        }

    def request(self, image: bytes) -> dict:
        """A whole page as one ``text`` region (not how the SDK uses the model; for ``ChatPageStep``)."""
        buf = io.BytesIO()
        from PIL import Image

        with Image.open(io.BytesIO(image)) as im:
            im.convert("RGB").save(buf, format="PNG")
        return self.request_region(buf.getvalue())

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "mm_processor_kwargs": dict(self.mm_processor_kwargs),
                "prompts": "minicpm-ocr 1.0.1 DEFAULT_PROMPT_MAP", "crop": "full resolution, int box, polygon mask",
                "skipped": list(IMAGE_LABELS)}


# ---------------------------------------------------------------- assembly
def region_blocks(t) -> list[dict]:
    """The SDK's result blocks from a transcription made by ``ChatRegionStep`` with this spec: one per
    region (read or image), in reading order, ``content`` = the raw completion."""
    text_of = {ln.region_id: ln.text or "" for ln in t.lines}
    regions = sorted(t.regions, key=lambda r: (r.reading_order is None, r.reading_order or 0))
    blocks = []
    for order, r in enumerate(regions):
        label = sdk_label(r)
        if label not in IMAGE_LABELS and r.id not in text_of:
            continue                                   # not read (a failed request, or another step's region)
        blocks.append({"label": label, "order": order, "raw": text_of.get(r.id, "")})
    return blocks


def assemble_markdown(t, keep_labels=()) -> str:
    """The page's Markdown exactly as minicpm-ocr 1.0.1 assembles it (needs the ``minicpm-ocr`` package):
    each block post-processed (``postprocess_content``), normalised and de-duplicated
    (``_normalize_and_dedupe_blocks``), then ``assemble_markdown`` with the SDK's ignore list minus
    ``keep_labels``."""
    from minicpmvocr.pipeline._text import _normalize_and_dedupe_blocks
    from minicpmvocr.postprocess.markdown import assemble_markdown as sdk_assemble
    from minicpmvocr.postprocess.markdown import has_mixed_inline_formula_content, postprocess_content
    from minicpmvocr.prompts import DEFAULT_PROMPT_MAP

    blocks = []
    for b in region_blocks(t):
        fmt = element(b["label"])["output_format"]
        blocks.append({"label": b["label"], "order": b["order"], "status": "ok",
                       "content": postprocess_content(b["raw"], fmt, label=b["label"]),
                       "raw_content": b["raw"],
                       "inline_formula_mixed": b["label"] == "inline_formula" and has_mixed_inline_formula_content(b["raw"])})
    prompt_map = {**DEFAULT_PROMPT_MAP, "markdown_assembly": {
        **DEFAULT_PROMPT_MAP["markdown_assembly"],
        "ignore_labels": [x for x in DEFAULT_PROMPT_MAP["markdown_assembly"]["ignore_labels"] if x not in keep_labels]}}
    return sdk_assemble(_normalize_and_dedupe_blocks(blocks), prompt_map)
