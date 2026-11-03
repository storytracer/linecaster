"""datalab-to/chandra-ocr-2: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the board's saturate driver ``chandra-ocr2-port.py`` (in the board's evaluation harness), a port
of the vendor's own vLLM client, ``chandra-ocr`` v0.2.0 (github.com/datalab-to/chandra, tag v0.2.0 =
497dfd38d7625259307c81c979d44093e9f75f44): ``chandra/model/vllm.py: generate_vllm`` with the
``ocr_layout`` prompt of the CLI. Where the driver and the vendor differ, this follows the driver:

* message = the page image, then the ``ocr_layout`` prompt as a text part (copied verbatim from
  ``chandra/prompts.py`` at v0.2.0 and hash-checked, as the driver does);
* the image RGB-converted, scaled by the vendor's ``scale_to_fit`` (``chandra/model/util.py``,
  verbatim: pixel count clamped to 3072 x 2048 = 6,291,456 and up to 1792 x 28, both sides snapped to
  multiples of 28, LANCZOS; an image already on the grid and within bounds is untouched), then PNG;
* sampling: temperature 0.0, top_p 0.1, max_tokens 12384 (the vendor's ``MAX_OUTPUT_TOKENS`` and
  ``generate_vllm`` defaults); thinking needs no switch (the chat template opens an empty
  ``<think></think>``);
* ONE attempt per page: the vendor client retries a page up to six times at a raised temperature when it
  detects a repetition loop; the board does not, so a loop shows as a loop (the driver's documented
  deviation from the vendor, kept here);
* serve flags: ``--max-model-len 20480`` (the board's correction of the vendor's 18000: 6144 visual tokens
  at the cap + 12384 + the prompt do not fit in 18000), ``--mm-processor-kwargs '{"min_pixels": 3136,
  "max_pixels": 6291456}'`` and ``--dtype bfloat16`` (vendor), ``--limit-mm-per-prompt '{"image": 1,
  "video": 0}' --mm-processor-cache-gb 0 --no-enable-prefix-caching`` (house); no
  ``--trust-remote-code``;
* model revision pinned to the board's checkpoint.

The model answers with HTML layout blocks (``<div data-bbox=.. data-label=..>``). The completion is
stored verbatim: the board converts it to Markdown with the vendor's ``chandra/output.py:
parse_markdown`` in the harness (``normalize_outputs``: strip, then ``chandra_html_to_markdown``, keyed on
the model id), not in the driver, so that stays in the harness. The board's vLLM is 0.26.0
(``vllm/vllm-openai:v0.26.0``; the vendor's launcher pins 0.17.0). ``--gpu-memory-utilization`` is the
deployment's choice (board 0.8 on an A10G, at most 12 pages in flight) and not part of the spec.
"""
from __future__ import annotations

import base64
import hashlib
import io
from typing import Any, ClassVar

from . import ChatModel

# ---- verbatim from chandra-ocr v0.2.0 chandra/prompts.py (via the board driver) ----
ALLOWED_TAGS = [
    "math", "br", "i", "b", "u", "del", "sup", "sub", "table", "tr", "td", "p", "th", "div", "pre", "h1",
    "h2", "h3", "h4", "h5", "ul", "ol", "li", "input", "a", "span", "img", "hr", "tbody", "small",
    "caption", "strong", "thead", "big", "code", "chem",
]
ALLOWED_ATTRIBUTES = [
    "class", "colspan", "rowspan", "display", "checked", "type", "border", "value", "style", "href", "alt",
    "align", "data-bbox", "data-label",
]

PROMPT_ENDING = f"""
Only use these tags {ALLOWED_TAGS}, and these attributes {ALLOWED_ATTRIBUTES}.

Guidelines:
* Inline math: Surround math with <math>...</math> tags. Math expressions should be rendered in KaTeX-compatible LaTeX. Use display for block math.
* Tables: Use colspan and rowspan attributes to match table structure.
* Formatting: Maintain consistent formatting with the image, including spacing, indentation, subscripts/superscripts, and special characters.
* Images: Include a description of any images in the alt attribute of an <img> tag. Do not fill out the src property. Describe in detail inside the div tag. Also convert charts to high fidelity data, and convert diagrams to mermaid.
* Forms: Mark checkboxes and radio buttons properly.
* Text: join lines together properly into paragraphs using <p>...</p> tags.  Use <br> tags for line breaks within paragraphs, but only when absolutely necessary to maintain meaning.
* Chemistry: Use <chem>...</chem> tags for chemical formulas with reactive SMILES.
* Lists: Preserve indents and proper list markers.
* Use the simplest possible HTML structure that accurately represents the content of the block.
* Make sure the text is accurate and easy for a human to read and interpret.  Reading order should be correct and natural.
""".strip()

OCR_LAYOUT_PROMPT = f"""
OCR this image to HTML, arranged as layout blocks.  Each layout block should be a div with the data-bbox attribute representing the bounding box of the block in x0 y0 x1 y1 format.  Bboxes are normalized 0-1000. The data-label attribute is the label for the block.

Use the following labels:
- Caption
- Footnote
- Equation-Block
- List-Group
- Page-Header
- Page-Footer
- Image
- Section-Header
- Table
- Text
- Complex-Block
- Code-Block
- Form
- Table-Of-Contents
- Figure
- Chemical-Block
- Diagram
- Bibliography
- Blank-Page

{PROMPT_ENDING}
""".strip()
# ---- end verbatim ----
#: the driver's check that the prompt is chandra-ocr v0.2.0's
PROMPT_SHA256_PREFIX = "025935f3e1de1acd"
assert hashlib.sha256(OCR_LAYOUT_PROMPT.encode()).hexdigest()[:16] == PROMPT_SHA256_PREFIX, (
    "OCR_LAYOUT_PROMPT differs from chandra-ocr v0.2.0")

MAX_SIZE, MIN_SIZE, GRID = (3072, 2048), (1792, 28), 28
MAX_MODEL_LEN, MAX_TOKENS = 20480, 12384


def scale_to_fit(img, max_size=MAX_SIZE, min_size=MIN_SIZE, grid_size: int = GRID):
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


def encode_png(image: bytes) -> tuple[str, tuple[int, int]]:
    """The driver's ``encode_png``: RGB, ``scale_to_fit``, base64 PNG; and the size sent."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = scale_to_fit(im.convert("RGB"))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode(), img.size


class ChandraOCR2(ChatModel):
    model: ClassVar[str] = "datalab-to/chandra-ocr-2"
    revision: ClassVar[str | None] = "af93b47dba1b47b6640c86ccf487ed2260ab9a09"
    page_longest: ClassVar[int | None] = None       # pixel-count bound (scale_to_fit), not a longest side
    prompt: ClassVar[str] = OCR_LAYOUT_PROMPT
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.0, "top_p": 0.1, "max_tokens": MAX_TOKENS}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", str(MAX_MODEL_LEN),
        "--mm-processor-kwargs", '{"min_pixels": 3136, "max_pixels": 6291456}',
        "--limit-mm-per-prompt", '{"image": 1, "video": 0}',
        "--mm-processor-cache-gb", "0",
        "--no-enable-prefix-caching",
        "--dtype", "bfloat16",
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        b64, _ = encode_png(image)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": f"chandra-ocr v0.2.0 ocr_layout (sha256 {PROMPT_SHA256_PREFIX}...)",
                "image": {"format": "png", "resize": "chandra scale_to_fit (max 3072x2048 px, min 1792x28 px, "
                                                      "grid 28), LANCZOS"},
                "attempts": 1}
