"""Adapter ``lighton-ocr-3-grounding``: LightOnOCR-3's grounding call (presets ``lightonocr-3-0.8b-grounding`` and
``lightonocr-3-4b-grounding``; the card's "Prompt Modes", model card at 36d8636).

The request is the transcription call's (``lighton-ocr-3``: the page thumbnailed to 2048 px, PNG, the same sampling)
with the text part ``grounding`` after the image, as the card's vLLM example sends it. The model then puts a
placeholder before every block, ``![label](x1,y1,x2,y2)`` with the block's box in page coordinates normalised to
0-1000, followed by the block's content (Markdown; tables as HTML): on the same line after a space for nearly every
block (the card's example puts it on the next line, which a list block also does), then on the lines after it.
``ground`` turns the completion (the transcription's raw output) into one region per block, in the order emitted,
all by the step's annotator and naming the output they were parsed from:

* **Labels** (``LABELS``): the model's label is the region's ``label``, verbatim; its content role
  (``linecaster.data.policy.ROLES``) a ``role`` classification: ``header`` and ``footer`` are ``header`` and
  ``footer`` (page furniture); ``page_number`` is ``page_number``, whose Docling label is ``page_header`` in the top
  half of the page and ``page_footer`` below (``linecaster.data.policy.docling_label``; 0.7.4 put the line at the top
  15 %); ``aside_text`` is ``marginalia`` (body text, as PP-DocLayout's ``aside_text``); ``title`` (document,
  section and paragraph headings) is ``heading`` with a ``heading_level`` classification, the number of ``#`` it
  starts with (the ``#`` taken off the text). A label the card does not name is kept as the region's label,
  classified ``other`` and counted (``unknown``).
* **Continuations**: a ``+`` after the label marks a block that continues an earlier one (``lighton__continuation``
  on the region, and a ``Link`` of kind ``continues`` to the last block of the same label on the page, where there is
  one; without one it continues the previous page or column). The blocks stay separate regions, linked.
* **Text**: a block's content lines are its lines (``region``, rows in order), each read as it is, so the page's
  text, the Docling composition and the text variants see them like any layout's: tables stay HTML, formulas LaTeX
  (also a ``Formula``, without ``$$``). The model gives boxes for blocks, not lines: a line's box is the block's split
  into equal rows, one per content line, and says so (``lighton__estimated``). ``verbatim_txt`` keeps the furniture,
  ``readable_txt`` and ``readable_md`` leave it out (``linecaster.text.variants``). Each region keeps the box as the
  model wrote it (``lighton__box_1000``).
* **Generated, not printed**: ``image``, ``header_image``, ``footer_image`` (``picture``) and ``chart`` (``chart``)
  carry what the model wrote about the figure, a description or the data read off a chart (an HTML table). It is a
  ``Description`` of the region (kind ``description`` or ``data``), and the region gets no lines: no text derived
  from the page contains it.
* **Faults, kept and counted** (the transcription's ``lighton__grounding``, the block's stats ``grounding_*``): a
  placeholder line that does not parse (``malformed``: the line itself is listed; what follows its closing
  parenthesis and the lines after it become lines without a region); text before the first placeholder (``unplaced``
  lines, without a region); a completion without any placeholder (``missing``: its text as lines without regions,
  nothing guessed); the last block of a completion cut off at ``max_tokens`` (``truncated``, ``lighton__truncated``
  on the region; the repair pass applies as in transcription mode).

The boxes come out in 0-1000 units, on a page of 1000 x 1000 (``lighton__grounding["coordinates"]``); ``place``
scales them to the page image the block read (its full size, not the thumbnail's), which ``PageRecognizer`` does with
the page's size.

vLLM's repetition detection (on by default: a pattern of 8 to 100 tokens repeated 16 times in a row) sees the
placeholder lines as part of the output: consecutive blocks differ in their boxes, so only blocks repeated exactly,
box and content, form such a run. Not yet checked with the model's tokenizer on grounding completions (NOTES.md).
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from ..data.transcription import Annotator, Description, Formula, Link, RawOutput, Source, Transcription
from . import data_url
from .lighton_ocr3 import LightOnOCR3Adapter

#: the card's grounding prompt, the text part after the image
PROMPT = "grounding"
#: the coordinate scale of the boxes the model writes
SCALE = 1000
#: LightOnOCR-3's labels (the card's table) -> content roles (``linecaster.data.policy.ROLES``); other labels: ``other``
LABELS = {"text": "paragraph", "title": "heading", "list": "list_item", "header": "header", "footer": "footer",
          "page_number": "page_number", "footnote": "footnote", "caption": "caption", "formula": "formula",
          "code": "code", "table": "table", "image": "picture", "chart": "chart", "header_image": "picture",
          "footer_image": "picture", "aside_text": "marginalia"}
#: the labels whose content the model generates about a figure, never printed text: label -> the description's kind
GENERATED = {"image": "description", "header_image": "description", "footer_image": "description", "chart": "data"}
#: a placeholder at the start of a line: ``![label](x1,y1,x2,y2)``, ``label+`` for a continuation, then the block's
#: first content line on the same line (as the model writes nearly every block) or nothing (its content on the next)
PLACEHOLDER = re.compile(r"^!\[(?P<label>[a-z_]+)(?P<plus>\+?)\]\((?P<box>[^()]*)\)[ \t]?(?P<rest>.*)$")
#: a line that starts like a placeholder (one that does not match ``PLACEHOLDER`` with a valid box is malformed);
#: ``rest`` is what follows its closing parenthesis, kept as text
LOOKS_LIKE = re.compile(r"^!\[[a-z_+]*\]?(?:\([^()]*\)[ \t]?(?P<rest>.*))?")
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


def ground(raw: str, finish_reason: str | None = None, annotator: Annotator | None = None) -> Transcription:
    """The transcription of a grounding completion (module docstring), boxes in 0-1000 units: ``raw`` its raw output,
    by ``annotator`` (default: an unnamed recognition step)."""
    t = Transcription(source=Source(kind="produced", format="text"))
    a = t.add_annotator(annotator or Annotator(kind="model", step="recognition", name="lighton-ocr-3-grounding"))
    t.add_output(RawOutput(annotator=a, content=raw, finish_reason=finish_reason))
    return ground_output(t, a, 0)


def ground_output(t: Transcription, annotator: int, output: int) -> Transcription:
    """``t`` with what its raw output ``output`` (a grounding completion) holds (module docstring), by ``annotator``,
    boxes in 0-1000 units on a page of 1000 x 1000."""
    raw = t.outputs[output].content
    finish_reason = t.outputs[output].finish_reason
    a, o = annotator, output
    blocks: list[dict] = []
    unplaced: list[str] = []
    malformed: list[str] = []
    current: dict | None = None
    for text in raw.split("\n"):
        m = PLACEHOLDER.match(text)
        if m and (box := _box(m.group("box"))) is not None:
            rest = m.group("rest")
            current = {"raw": m.group("label"), "continuation": bool(m.group("plus")), "box": box,
                       "lines": [rest] if rest.strip() else []}
            blocks.append(current)
        elif lm := LOOKS_LIKE.match(text):
            malformed.append(text)
            rest = lm.group("rest") or ""
            current = {"raw": None, "lines": [rest] if rest.strip() else []}   # lines without a region
            blocks.append(current)
        elif current is None:
            unplaced.append(text)
        else:
            current["lines"].append(text)
    regions: list[str] = []
    lines: list[str] = []
    rows: list[int] = []
    unknown: list[str] = []
    last_of: dict[str, str] = {}
    generated = 0

    def add_lines(texts: list[str], region_id: str | None, prefix: str, box: list[float] | None = None) -> None:
        for k, text in enumerate(texts):
            geometry: dict[str, Any] = {}
            if box is not None:                                # the block's box split into equal rows
                x1, y1, x2, y2 = box
                h = (y2 - y1) / len(texts)
                top = y1 + k * h
                geometry = {"box": [x1, top, x2 - x1, h],
                            "polygon": [[x1, top], [x2, top], [x2, top + h], [x1, top + h]],
                            "lighton__estimated": True}
            line = t.add_line(a, f"{prefix}_l{k}", region=region_id, output=o, **geometry)
            t.read(a, line, text, output=o)
            lines.append(line.id)
            rows.append(k)

    add_lines(_trim(unplaced), None, "unplaced")
    for i, b in enumerate(blocks):
        content = _trim(b["lines"])
        if b["raw"] is None:                                   # under a malformed placeholder
            add_lines(content, None, f"malformed_{i}")
            continue
        label, (x1, y1, x2, y2) = b["raw"], b["box"]
        if label not in LABELS:
            unknown.append(label)
        role = LABELS.get(label, "other")
        rid = f"{label}_{i}"
        fields: dict[str, Any] = {"lighton__box_1000": [x1, y1, x2, y2]}
        if b["continuation"]:
            fields["lighton__continuation"] = True
        if finish_reason == "length" and i == len(blocks) - 1:
            fields["lighton__truncated"] = True
        level = None
        description = None
        if label in GENERATED:
            generated += 1
            description, content = "\n".join(content), []
        elif role == "heading" and content and (h := _HEADING.match(content[0])):
            level, content = len(h.group(1)), [content[0][h.end():], *content[1:]]
        t.add_region(a, rid, [x1, y1, x2 - x1, y2 - y1], [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], label=label,
                     role=role, heading_level=level, output=o, **fields)
        regions.append(rid)
        if b["continuation"] and label in last_of:
            t.links.append(Link(annotator=a, output=o, kind="continues", source=rid, target=last_of[label]))
        last_of[label] = rid
        if description is not None:
            t.descriptions.append(Description(annotator=a, output=o, target=rid, kind=GENERATED[label],
                                              text=description,
                                              format="html" if description.lstrip().startswith("<") else "markdown"))
        if role == "formula" and content:
            t.formulas.append(Formula(annotator=a, output=o, target=rid, latex="\n".join(content).strip()
                                      .removeprefix("$$").removesuffix("$$").strip()))
        add_lines(content, rid, rid, [x1, y1, x2, y2])
    t.add_order(a, regions, lines, rows)
    t.source.image_width = t.source.image_height = SCALE
    placed = sum(1 for b in blocks if b["raw"] is not None)
    t.lighton__grounding = {"blocks": placed, "unknown": unknown, "malformed": malformed, "generated": generated,
                            "unplaced": len(_trim(unplaced)), "missing": not blocks,
                            "truncated": finish_reason == "length" and bool(regions) and blocks[-1]["raw"] is not None,
                            "coordinates": f"0-{SCALE}"}
    return t


def _trim(texts: list[str]) -> list[str]:
    """A block's content lines without the empty lines around them (the separators between blocks)."""
    lo, hi = 0, len(texts)
    while lo < hi and not texts[lo].strip():
        lo += 1
    while hi > lo and not texts[hi - 1].strip():
        hi -= 1
    return texts[lo:hi]


def reground(t: Transcription, width: int, height: int) -> Transcription:
    """A grounding transcription parsed again from its kept raw output and placed on a ``width`` x ``height`` page
    image, keeping its annotators, its raw outputs (the repair passes) and its other extension fields: for records
    written by linecaster 0.7.3 (upgraded to ``linecaster.page/3``), whose parser took a placeholder only alone on its
    line and so left most pages without text. What the earlier parse made is left out; ``t`` without a text output
    stays as it is."""
    kept = [i for i, o in enumerate(t.outputs) if o.kept and isinstance(o.content, str)]
    if not kept:
        return t
    o = kept[-1]
    extensions = {k: v for k, v in t.extensions.items() if k not in ("lighton__grounding", "page2__grounding")}
    new = Transcription(source=Source(kind="produced", format="text"),
                        annotators=[a.model_copy(deep=True) for a in t.annotators],
                        outputs=[x.model_copy(deep=True) for x in t.outputs], **extensions)
    return place(ground_output(new, t.outputs[o].annotator, o), width, height)


def place(t: Transcription, width: int, height: int) -> Transcription:
    """Scales the regions' and lines' boxes from 0-1000 to a ``width`` x ``height`` page image, once (the coordinates
    are noted in ``lighton__grounding["coordinates"]``); a transcription without grounding, or one placed already,
    stays."""
    g = getattr(t, "lighton__grounding", None)
    if not g or g.get("coordinates") != f"0-{SCALE}" or not width or not height:
        return t
    sx, sy = width / SCALE, height / SCALE
    for zone in (*t.regions, *(ln for ln in t.lines if ln.box is not None)):
        zone.polygon = [[x * sx, y * sy] for x, y in zone.polygon]
        x, y, w, h = zone.box
        zone.box = [x * sx, y * sy, w * sx, h * sy]
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
        """The grounded transcription (``ground_output``), boxes in 0-1000 until ``place``."""
        return ground_output(self.begin(body, backend), 0, 0)

    def grounding(self, t: Transcription) -> dict | None:
        return getattr(t, "lighton__grounding", None)

    def place(self, t: Transcription, width: int, height: int) -> Transcription:
        return place(t, width, height)
