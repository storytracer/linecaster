"""allenai/olmOCR-2-7B-1025-FP8: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the saturate driver that produced the board row (in the board's evaluation harness), a port
of Daniel van Strien's ``uv-scripts/ocr/olmocr2-vllm.py``; where the two differ, the driver wins:

* message = the olmOCR no-anchoring (v4, YAML) prompt as a text part, THEN the page image (text
  before image, as the driver sends it);
* the image re-encoded as PNG with the longest side forced to exactly 1288 px, in both directions
  (the olmOCR pipeline's ``target_longest_image_dim``), LANCZOS;
* sampling: temperature 0.1, max_tokens 8192, repetition_penalty 1.05, stop
  ``["<|im_end|>", "<|endoftext|>"]`` (the recipe's values, recorded in the driver);
* serve flags: ``--max-model-len 16384 --no-enable-prefix-caching --mm-processor-cache-gb 0
  --limit-mm-per-prompt '{"image": 1}'``; no ``--trust-remote-code``;
* model revision pinned to the board's checkpoint.

The model answers with YAML front matter (primary_language, is_rotation_valid, rotation_correction,
is_table, is_diagram) above the page text. The completion is stored verbatim (``extra["raw"]``, the
lines); the front matter is also parsed into ``extra["front_matter"]`` as page metadata, as the driver
parses it into its ``markdown_metadata`` column. Splitting it off the scored text is the board's
post-processing and stays in the harness; ``body`` gives the same split for other consumers. The
board's vLLM is 0.26.0 (``vllm/vllm-openai:v0.26.0``); ``--gpu-memory-utilization`` is the
deployment's choice (board 0.8 on an A10G) and not part of the spec.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from . import ChatModel, png_longest
from ..transcription.model import Transcription

PROMPT = (
    "Attached is one page of a document that you must process. Just return the plain "
    "text representation of this document as if you were reading it naturally. Convert "
    "equations to LateX and tables to HTML.\n"
    "If there are any figures or charts, label them with the following markdown syntax "
    "![Alt text describing the contents of the figure](page_startx_starty_width_height.png)\n"
    "Return your output as markdown, with a front matter section on top specifying values "
    "for the primary_language, is_rotation_valid, rotation_correction, is_table, and "
    "is_diagram parameters."
)
#: the board harness's pattern (the body is optional: a blank page is answered with front matter alone)
FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n(.*))?$", re.DOTALL)


def _scalar(v: str) -> Any:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~", ""):
        return None
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def split_front_matter(raw: str) -> tuple[dict[str, Any] | None, str]:
    """``(metadata, body)`` of an olmOCR-2 completion: the flat ``key: value`` YAML front matter
    (``None`` if there is none) and the text below it exactly as the board harness splits it
    (outer whitespace stripped first, body not re-stripped; the whole stripped text if no front matter)."""
    text = raw.strip()
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, text
    meta: dict[str, Any] = {}
    for line in m.group(1).split("\n"):
        key, sep, value = line.partition(":")
        if sep and key.strip():
            meta[key.strip()] = _scalar(value)
    return meta, m.group(2) or ""


def body(raw: str) -> str:
    """The page text below the front matter (the board's ``strip`` + ``drop_front_matter``)."""
    return split_front_matter(raw)[1]


class OlmOCR2(ChatModel):
    model: ClassVar[str] = "allenai/olmOCR-2-7B-1025-FP8"
    revision: ClassVar[str | None] = "40bd7202494b8264ee17ada08b401b5aab7a9ce1"
    target_longest: ClassVar[int] = 1288
    page_longest: ClassVar[int | None] = 1288
    prompt: ClassVar[str] = PROMPT
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.1, "repetition_penalty": 1.05,
                                          "stop": ["<|im_end|>", "<|endoftext|>"], "max_tokens": 8192}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", "16384",
        "--no-enable-prefix-caching",
        "--mm-processor-cache-gb", "0",
        "--limit-mm-per-prompt", '{"image": 1}',
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        b64, _ = png_longest(image, self.target_longest)
        return self._body(b64)

    def request_region(self, crop: bytes, region=None) -> dict:
        """A region crop, already at the page's 1288-px scale: PNG as it is, no further resize."""
        import base64

        return self._body(base64.b64encode(crop).decode())

    def _body(self, b64: str) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": self.prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
            "temperature": self.sampling["temperature"],
            "repetition_penalty": self.sampling["repetition_penalty"],
            "stop": list(self.sampling["stop"]),
            "max_tokens": self.sampling["max_tokens"],
        }

    def parse(self, body: dict, backend: str | None = None) -> Transcription:
        t = super().parse(body, backend=backend)
        t.extra["front_matter"] = split_front_matter(t.extra["raw"])[0]
        return t

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "image": {"format": "png", "longest_side_px": self.target_longest,
                                                "resize": "forced (up and down), LANCZOS"},
                "prompt": "olmOCR no-anchoring v4 (YAML front matter), text before image"}
