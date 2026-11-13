"""Adapter ``lighton-ocr-3-grounding``: LightOnOCR-3's grounding call (presets ``lightonocr-3-0.8b-grounding`` and
``lightonocr-3-4b-grounding``; the card's "Prompt Modes", model card at 36d8636).

The request is the transcription call's (``lighton-ocr-3``: the page thumbnailed to 2048 px, PNG, the same sampling)
with the text part ``grounding`` after the image, as the card's vLLM example sends it. The model then puts a
placeholder line before every block, ``![label](x1,y1,x2,y2)`` with the block's box in page coordinates normalised
to 0-1000, followed by the block's content (Markdown; tables as HTML). ``ground`` turns the completion into a
transcription with one region per block, in the order emitted:

* **Labels** (``LABELS``): the model's label is ``raw_label`` (and ``extra["label"]``), ``label`` its Docling label:
  ``header`` and ``footer`` are ``page_header`` and ``page_footer`` (page furniture); ``page_number`` is one of them by
  position, ``page_header`` when the box's centre lies in the top ``HEADER_ZONE`` of the page, else ``page_footer``,
  as PP-DocLayout's ``number`` is placed; ``aside_text`` (marginalia) is body ``text``, as PP-DocLayout's is;
  ``title`` (document, section and paragraph headings) is ``section_header`` with ``heading_level`` the number of
  ``#`` it starts with (the ``#`` taken off the text). A label the card does not name is kept as ``raw_label``, made
  ``text`` and counted (``unknown``).
* **Continuations**: a ``+`` after the label marks a block that continues an earlier one (``extra["continuation"]``;
  ``extra["continues"]`` the id of the last block of the same label on the page, ``None`` where there is none: it
  continues the previous page or column). The blocks stay separate regions, linked.
* **Text**: a block's content lines are its lines (``region_id``, rows in order), so the page's text, the Docling
  composition and the text variants see them like any layout's: tables stay HTML, formulas LaTeX (also
  ``extra["formula"]``, without ``$$``). The model gives boxes for blocks, not lines: a line's box is the block's
  split into equal rows, one per content line, and says so (``extra["box"] = "estimated"``). ``verbatim_txt`` keeps the furniture, ``readable_txt`` and
  ``readable_md`` leave it out (``linecaster.text.variants``).
* **Generated, not printed**: ``image``, ``header_image``, ``footer_image`` (``picture``) and ``chart`` (``chart``)
  carry what the model wrote about the figure, a description or the data read off a chart (an HTML table). It is kept
  in ``extra["generated"]`` (``{"kind": "description" | "data", "content": ...}``, ``extra["printed"] = False``) and
  the region gets no lines: no text derived from the page contains it.
* **Faults, kept and counted** (``extra["grounding"]``, the block's stats ``grounding_*``): a placeholder line that
  does not parse (``malformed``: its content becomes lines without a region, the line itself is listed); text before
  the first placeholder (``unplaced`` lines, without a region); a completion without any placeholder (``missing``:
  its text as lines without regions, nothing guessed); the last block of a completion cut off at ``max_tokens``
  (``truncated``, ``extra["truncated"]``; the repair pass applies as in transcription mode).

The boxes come out in 0-1000 units (``extra["grounding"]["coordinates"]``); ``place`` scales them to the page image
the block read (its full size, not the thumbnail's), which ``PageRecognizer`` does with the page's size.

vLLM's repetition detection (on by default: a pattern of 8 to 100 tokens repeated 16 times in a row) sees the
placeholder lines as part of the output: consecutive blocks differ in their boxes, so only blocks repeated exactly,
box and content, form such a run. Not yet checked with the model's tokenizer on grounding completions (NOTES.md).
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from ..data.transcription import Line, Region, Source, Transcription
from . import data_url
from .lighton_ocr3 import LightOnOCR3Adapter

#: the card's grounding prompt, the text part after the image
PROMPT = "grounding"
#: the coordinate scale of the boxes the model writes
SCALE = 1000
#: a ``page_number`` whose box centre lies in this top share of the page is a ``page_header`` (PP-DocLayout's rule)
HEADER_ZONE = 0.15
#: LightOnOCR-3's labels (the card's table) -> Docling labels; ``page_number`` is placed by position
LABELS = {"text": "text", "title": "section_header", "list": "list_item", "header": "page_header",
          "footer": "page_footer", "page_number": None, "footnote": "footnote", "caption": "caption",
          "formula": "formula", "code": "code", "table": "table", "image": "picture", "chart": "chart",
          "header_image": "picture", "footer_image": "picture", "aside_text": "text"}
#: the labels whose content the model generates about a figure, never printed text: label -> what it is
GENERATED = {"image": "description", "header_image": "description", "footer_image": "description", "chart": "data"}
#: a placeholder line: ``![label](x1,y1,x2,y2)``, ``label+`` for a continuation
PLACEHOLDER = re.compile(r"^!\[(?P<label>[a-z_]+)(?P<plus>\+?)\]\((?P<box>[^()]*)\)\s*$")
#: a line that starts like a placeholder (one that does not match ``PLACEHOLDER`` is malformed)
LOOKS_LIKE = re.compile(r"^!\[[a-z_+]*\]?\(?")
_HEADING = re.compile(r"^(#{1,6})\s+")


def _box(text: str) -> list[float] | None:
    """``x1,y1,x2,y2`` in 0-1000, or None when it is not four numbers in range with x1 <= x2, y1 <= y2."""
    try:
        v = [float(x) for x in text.split(",")]
    except ValueError:
        return None
    if len(v) != 4 or not all(0 <= x <= SCALE for x in v) or v[0] > v[2] or v[1] > v[3]:
        return None
    return v


def ground(raw: str, finish_reason: str | None = None) -> Transcription:
    """The transcription of a grounding completion (module docstring), boxes in 0-1000 units."""
    blocks: list[dict] = []
    unplaced: list[str] = []
    malformed: list[str] = []
    current: dict | None = None
    for text in raw.split("\n"):
        m = PLACEHOLDER.match(text)
        if m and (box := _box(m.group("box"))) is not None:
            current = {"raw": m.group("label"), "continuation": bool(m.group("plus")), "box": box, "lines": []}
            blocks.append(current)
        elif LOOKS_LIKE.match(text):
            malformed.append(text)
            current = {"raw": None, "lines": []}                # its content: lines without a region
            blocks.append(current)
        elif current is None:
            unplaced.append(text)
        else:
            current["lines"].append(text)
    regions: list[Region] = []
    lines: list[Line] = []
    unknown: list[str] = []
    last_of: dict[str, str] = {}
    generated = 0

    def add_lines(texts: list[str], region_id: str | None, prefix: str, box: list[float] | None = None) -> None:
        for k, t in enumerate(texts):
            geometry: dict[str, Any] = {}
            if box is not None:                                # the block's box split into equal rows
                x1, y1, x2, y2 = box
                h = (y2 - y1) / len(texts)
                top = y1 + k * h
                geometry = {"bbox": [x1, top, x2 - x1, h], "polygon": [[x1, top], [x2, top], [x2, top + h], [x1, top + h]],
                            "extra": {"box": "estimated"}}
            lines.append(Line(id=f"{prefix}_l{k}", region_id=region_id, reading_order=len(lines), row=k, text=t,
                              **geometry))

    add_lines(_trim(unplaced), None, "unplaced")
    for i, b in enumerate(blocks):
        content = _trim(b["lines"])
        if b["raw"] is None:                                   # under a malformed placeholder
            add_lines(content, None, f"malformed_{i}")
            continue
        raw_label, (x1, y1, x2, y2) = b["raw"], b["box"]
        if raw_label not in LABELS:
            unknown.append(raw_label)
            label = "text"
        elif raw_label == "page_number":
            label = "page_header" if (y1 + y2) / 2 < HEADER_ZONE * SCALE else "page_footer"
        else:
            label = LABELS[raw_label]
        rid = f"{raw_label}_{i}"
        extra: dict[str, Any] = {"label": raw_label + ("+" if b["continuation"] else ""), "box_1000": [x1, y1, x2, y2]}
        if b["continuation"]:
            extra["continuation"], extra["continues"] = True, last_of.get(raw_label)
        last_of[raw_label] = rid
        level = None
        if raw_label in GENERATED:
            generated += 1
            extra.update(generated={"kind": GENERATED[raw_label], "content": "\n".join(content)}, printed=False)
            content = []
        elif label == "section_header" and content and (h := _HEADING.match(content[0])):
            level, content = len(h.group(1)), [content[0][h.end():], *content[1:]]
        if label == "formula" and content:
            extra["formula"] = "\n".join(content).strip().removeprefix("$$").removesuffix("$$").strip()
        if finish_reason == "length" and i == len(blocks) - 1:
            extra["truncated"] = True
        regions.append(Region(id=rid, label=label, raw_label=raw_label,
                              polygon=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]], bbox=[x1, y1, x2 - x1, y2 - y1],
                              reading_order=len(regions), heading_level=level, extra=extra))
        add_lines(content, rid, rid, [x1, y1, x2, y2])
    placed = sum(1 for b in blocks if b["raw"] is not None)
    counts = {"blocks": placed, "unknown": unknown, "malformed": malformed, "generated": generated,
              "unplaced": len(_trim(unplaced)), "missing": not blocks,
              "truncated": finish_reason == "length" and bool(regions) and blocks[-1]["raw"] is not None,
              "coordinates": f"0-{SCALE}"}
    return Transcription(regions=regions, lines=lines, source=Source(kind="produced", format="text"),
                         extra={"raw": raw, "finish_reason": finish_reason, "grounding": counts})


def _trim(texts: list[str]) -> list[str]:
    """A block's content lines without the empty lines around them (the separators between blocks)."""
    lo, hi = 0, len(texts)
    while lo < hi and not texts[lo].strip():
        lo += 1
    while hi > lo and not texts[hi - 1].strip():
        hi -= 1
    return texts[lo:hi]


def place(t: Transcription, width: int, height: int) -> Transcription:
    """Scales the regions' boxes from 0-1000 to a ``width`` x ``height`` page image, once (the coordinates are noted in
    ``extra["grounding"]["coordinates"]``); a transcription without grounding, or one placed already, stays."""
    g = t.extra.get("grounding")
    if not g or g.get("coordinates") != f"0-{SCALE}" or not width or not height:
        return t
    sx, sy = width / SCALE, height / SCALE
    for item in (*t.regions, *(ln for ln in t.lines if ln.bbox is not None)):
        item.polygon = [[x * sx, y * sy] for x, y in item.polygon]
        x, y, w, h = item.bbox
        item.bbox = [x * sx, y * sy, w * sx, h * sy]
    g["coordinates"] = "page"
    t.source.image_width, t.source.image_height = int(width), int(height)
    return t


class LightOnOCR3GroundingAdapter(LightOnOCR3Adapter):
    adapter: ClassVar[str] = "lighton-ocr-3-grounding"

    @property
    def prompt_text(self) -> str:
        return str(self.prompt or PROMPT)

    def _body(self, b64: str) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [data_url("image/png", b64),
                                                      {"type": "text", "text": self.prompt_text}]}],
            **self.sampling,
            "chat_template_kwargs": self.chat_template_kwargs,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt_text, "mode": "grounding"}

    def parse(self, body: dict, backend: str | None = None) -> Transcription:
        """The grounded transcription (``ground``), boxes in 0-1000 until ``place``."""
        raw, finish = self.content(body)
        usage = body.get("usage") or {}
        t = ground(raw, finish)
        t.steps = [self.step_info(backend, measurements={
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": finish})]
        return t

    def place(self, t: Transcription, width: int, height: int) -> Transcription:
        return place(t, width, height)
