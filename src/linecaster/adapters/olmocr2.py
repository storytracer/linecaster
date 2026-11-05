"""Adapter ``olmocr``: olmOCR-2 with the no-anchoring prompt (preset ``olmocr-2-7b-1025-fp8``).

* message = ``settings.prompt`` (olmOCR's no-anchoring v4, YAML front matter) as a text part, THEN the page
  image (text before image, as the board driver sends it);
* the image re-encoded as PNG with the longest side forced to exactly ``settings.image.longest_side_px``
  (1288, the olmOCR pipeline's ``target_longest_image_dim``), in both directions, LANCZOS; a region crop is
  already at that page scale and sent as it is.

The model answers with YAML front matter (primary_language, is_rotation_valid, rotation_correction,
is_table, is_diagram) above the page text. The completion is stored verbatim (``extra["raw"]``, the lines);
the front matter is also parsed into ``extra["front_matter"]`` as page metadata, as the driver parses it.
Splitting it off the scored text is the board's post-processing; ``body`` gives the same split.
"""
from __future__ import annotations

import base64
import re
from typing import Any, ClassVar

from ..data.transcription import Transcription
from . import ChatModel, data_url, png_longest

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


class OlmOCR(ChatModel):
    adapter: ClassVar[str] = "olmocr"

    @property
    def target_longest(self) -> int:
        return int(self.config["image"]["longest_side_px"])

    def request(self, image: bytes) -> dict:
        b64, _ = png_longest(image, self.target_longest)
        return self._body(b64)

    def request_region(self, crop: bytes, region=None) -> dict:
        """A region crop, already at the page's scale: PNG as it is, no further resize."""
        return self._body(base64.b64encode(crop).decode())

    def _body(self, b64: str) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [{"type": "text", "text": self.prompt},
                                                      data_url("image/png", b64)]}],
            **{k: (list(v) if isinstance(v, list) else v) for k, v in self.sampling.items()},
        }

    def parse(self, body: dict, backend: str | None = None) -> Transcription:
        t = super().parse(body, backend=backend)
        t.extra["front_matter"] = split_front_matter(t.extra["raw"])[0]
        return t

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "image": {"format": "png", "longest_side_px": self.target_longest,
                                                "resize": "forced (up and down), LANCZOS"},
                "prompt": f"{self.config.get('prompt_name', 'olmOCR')}, text before image"}
