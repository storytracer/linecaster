"""Tagging step engines: classifications of zones in **property schemes** (``linecaster.data.PROPERTIES``: yes/no
schemes such as ``rotated``, ``tiny``, ``multi_column``, ``degraded``, ``form``) and other closed schemes, each
defined by its vocabulary in the catalog (``vocabularies/<scheme>.yaml``: a definition, what counts and what does
not). A **tagger** is an engine of the ``tagging`` step; it records what it decided as ``Classification`` s by its
own annotator, and records nothing where its evidence does not decide: nothing is guessed into a record.

Two taggers, the evidence ordered from most to least certain:

* ``tagging.geometry.v1`` (``GeometryTaggingEngine``): what geometry decides, by rules (annotator kind ``rule``);
* ``tagging.chat.v1`` (``ChatTaggingEngine``): a panel of vision-language models behind OpenAI-compatible chat
  servers (annotator kind ``model``), for what geometry cannot see (``degraded``, ``form``, an upside-down page) and
  for what the rules left undecided.

Both are called like the model steps' engines, ``engine(image, transcription, page=None, **options)`` (the page image
as an RGB array; the geometry tagger needs none), and both run in the pipeline's process (the chat tagger is a client
of its servers). ``Tagger`` (``linecaster.blocks.tagging``) runs either by preset.

**The geometry tagger.** Each classification is on the narrowest target its scheme is true of, with its evidence in
the call's raw output (format ``json``, the engine's native result; each classification names it) and the page's
numbers in the annotator's measurements (``tagged``, ``undecided``, ``body_line_height``):

* ``rotated``, on lines: ``yes`` where the line's recorded writing direction is vertical, or where its baseline (else
  its polygon's minimum-area rectangle, when that is at least ``elongation`` times longer than it is high) is tilted
  by ``max_tilt`` degrees or more; ``no`` where it is tilted less. A line with only a box is undecided: a box says no
  angle. A page turned upside down has level baselines: geometry cannot see a half turn, which is why ``decide_no``
  can leave ``no`` to the model tagger;
* ``tiny``, on lines: the line's height across its direction against the median of the page's body text lines
  (lines of regions whose role is one of ``body_roles``; all lines where none is in a region); ``yes`` below
  ``tiny`` times that median, else ``no``. With fewer than ``min_body_lines`` body lines nothing is decided;
* ``multi_column``, on text regions (roles ``column_roles``), seen in the page's writing direction's frame: ``yes``
  where another text region sits beside it (their extents across the lines overlap by ``min_overlap`` of the
  shorter, along the lines by at most ``max_overlap`` of the narrower); ``no`` where it spans ``full_width`` of the
  page's text width with nothing beside it; else undecided (a narrow region alone).

**The model tagger** (the design; Omni Parse Bench's labeling recipe, ``docs/tagging.md`` there, adopted):

* *One question per target and scheme*, generated from the scheme's vocabulary, never paraphrased: the definition
  of ``yes`` (a property scheme) or of each value (another closed scheme), what counts and what does not; open
  schemes (``language``, ``script``) are never asked. The question says exactly what is marked and how (a red box,
  one per target), asks for the reason first and the answer last, as one JSON object
  (``{"reason": ..., "answer": ...}``), and takes the answers named after the property (``degraded``,
  ``not_degraded``: a model's "yes" cannot be read as "yes, the box is right"), a closed scheme's values, and
  ``cannot_tell`` and ``not_here`` (the box marks no content). Anything else, or a reply that is no JSON, is no
  answer.
* *What the models see* (``views``): the page with the target's box drawn (``page``, its longest side at most
  ``page_longest``) and the target enlarged with ``context`` around it and the same box (``crop``, at most
  ``crop_longest``); a page target is the page alone. Every member sees the same images and the same question and
  nothing else (not the text read, not other tags).
* *The panel*: two members (``panel``, the first the one a review found right more often) and optionally a third
  (``referee``). The two agree: that is the classification. They split, or one gives no answer: the referee is asked
  and the scheme's rule (``settle``) decides: ``first_with_referee`` (the default: the referee must give the first
  member's answer; where the first gave none, the second's), ``majority`` (two of the three), ``first`` (the first
  member's answer alone, no referee). What no rule settles is **undecided**: nothing is recorded, and the item is
  written for review. A member names a chat preset of the catalog (``preset``: its model, revision and hash are
  recorded) or a served model (``model``, with its ``revision`` where known).
* *The cache* (``cache``): every answer is kept under the hash of everything the member was shown (the request
  body, images included, and the model's revision), as ``<LINECASTER_CACHE or ~/.cache/linecaster>/tagging/
  <hash[:2]>/<hash>.json``; a changed definition, image or setting asks again only the questions it touches, and a
  rerun asks nothing.
* *The record*: one annotator for the call (kind ``model``, step ``tagging``, the members' models as its name, its
  settings the members with their presets, revisions and sampling, the views, the rules per scheme and each
  vocabulary's hash), every member's completion verbatim as a raw output (its settings name the member, the target
  and the scheme; ``kept`` on the one the classification follows), each classification naming the raw output it
  follows; measurements ``tagged``, ``undecided``, ``agreed``, ``settled``, ``asked``, ``cached`` and the tokens
  of the requests sent.
* *Review* (``review``, a folder): each undecided item as one JSON line (``linecaster.tagging-review/1``: the page,
  the target and its box, the scheme, the rule, every member's answer, reason and completion, and, with
  ``review_images``, the images the members saw) in ``review-<token>.jsonl``, one file per engine instance, so
  that workers never write one file together. A person's answers are corrections applied after the taggers.

Import-light, like the data model: the catalog (vocabularies, presets) is read when the engine loads.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from linecaster.data.geometry import BBox, bbox_of
from linecaster.data.geometry.frames import to_frame
from linecaster.data.policy import role_of_label
from linecaster.data.transcription import Annotator, RawOutput, Transcription, producer
from linecaster.errors import PipelineConfigError, ServerError
from linecaster.engines.base import RuleEngine

#: statuses whose zones a tagger leaves alone: they are no text of the page
SKIPPED_STATUSES = ("duplicate", "removed", "suppressed")
#: the text roles whose regions make columns (``multi_column``)
COLUMN_ROLES = ("paragraph", "heading", "title", "caption", "list_item", "list_label", "toc_entry", "footnote",
                "footnote_continued", "endnote", "credit", "floating", "reference", "code", "other")
#: the format of a review file's lines
REVIEW_SCHEMA = "linecaster.tagging-review/1"
#: the answers every question takes besides the scheme's (``linecaster.catalog.vocabulary.NO_ANSWERS``)
NO_ANSWERS = ("cannot_tell", "not_here")
SETTLE_RULES = ("first_with_referee", "majority", "first")


# ------------------------------------------------------------------------------------------------ geometry

def fold(angle: float) -> float:
    """An angle in degrees as the tilt of an undirected line: in [-90, 90)."""
    return (angle + 90.0) % 180.0 - 90.0


def _hull(p: np.ndarray) -> np.ndarray:
    """The convex hull of points (Andrew's monotone chain), counterclockwise."""
    pts = sorted(map(tuple, p))
    if len(pts) <= 2:
        return np.asarray(pts, dtype=float)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for q in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper: list = []
    for q in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.asarray(lower[:-1] + upper[:-1], dtype=float)


def min_area_rect(points) -> tuple[float, float, float] | None:
    """The minimum-area rectangle around ``points``: the tilt of its longer side (degrees, ``fold``), its longer and its
    shorter side; ``None`` for fewer than three points not on one line."""
    p = np.unique(np.asarray(points, dtype=float).reshape(-1, 2), axis=0)
    if len(p) < 3:
        return None
    h = _hull(p)
    if len(h) < 3:
        return None
    best = None
    for i in range(len(h)):
        e = h[(i + 1) % len(h)] - h[i]
        n = math.hypot(*e)
        if n == 0:
            continue
        u = e / n
        v = np.array([-u[1], u[0]])
        a, b = h @ u, h @ v
        w, t = float(a.max() - a.min()), float(b.max() - b.min())
        if best is None or w * t < best[0] - 1e-9:
            best = (w * t, u, w, t)
    _, u, w, t = best
    if t > w:
        u, w, t = np.array([-u[1], u[0]]), t, w
    return fold(math.degrees(math.atan2(u[1], u[0]))), w, t


def _box_points(box) -> list[list[float]]:
    x, y, w, h = box
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def zone_bbox(z) -> BBox | None:
    """A zone's box from its polygon, else its ``box``; ``None`` without geometry."""
    if z.polygon:
        return bbox_of(z.polygon)
    if z.box:
        x, y, w, h = z.box
        return BBox(x, y, x + w, y + h)
    return None


def line_measure(ln, vertical: bool, elongation: float) -> dict:
    """A line's tilt and height as geometry gives them: ``tilt`` (degrees, ``fold``; from the baseline's ends, else
    from the polygon's minimum-area rectangle when it is ``elongation`` times longer than high, else ``None``),
    ``source`` (``baseline``, ``polygon``) and ``height`` (across the line: the polygon's or box's extent across the
    tilt; without a tilt the box's height, its width for a vertical line; ``None`` without geometry)."""
    tilt = source = None
    if ln.baseline and len(ln.baseline) >= 2:
        (x0, y0), (x1, y1) = ln.baseline[0][:2], ln.baseline[-1][:2]
        if (x0, y0) != (x1, y1):
            tilt, source = fold(math.degrees(math.atan2(y1 - y0, x1 - x0))), "baseline"
    pts = ln.polygon if ln.polygon and len(ln.polygon) >= 3 else (_box_points(ln.box) if ln.box else None)
    if tilt is None and ln.polygon and len(ln.polygon) >= 3:
        rect = min_area_rect(ln.polygon)
        if rect is not None and rect[2] > 0 and rect[1] >= elongation * rect[2]:
            tilt, source = rect[0], "polygon"
    height = None
    if pts is not None:
        p = np.asarray(pts, dtype=float).reshape(-1, 2)
        if tilt is not None:
            r = math.radians(tilt)
            across = p @ np.array([-math.sin(r), math.cos(r)])
            height = float(across.max() - across.min())
        else:
            ext = p.max(axis=0) - p.min(axis=0)
            height = float(ext[0] if vertical else ext[1])
    return {"tilt": None if tilt is None else round(tilt, 2), "source": source,
            "height": None if height is None else round(height, 2)}


def _role(t: Transcription, zone) -> str:
    return t.role(zone.id) or role_of_label(getattr(zone, "label", "") or "")[0]


def _vertical(direction: str | None) -> bool:
    return bool(direction) and direction.startswith("vertical")


class _Tally:
    """A call's counts: classifications by scheme and value, undecided targets by scheme."""

    def __init__(self):
        self.tagged: dict[str, dict[str, int]] = {}
        self.undecided: dict[str, int] = {}

    def tag(self, scheme: str, value: str) -> None:
        by = self.tagged.setdefault(scheme, {})
        by[value] = by.get(value, 0) + 1

    def skip(self, scheme: str) -> None:
        self.undecided[scheme] = self.undecided.get(scheme, 0) + 1

    def measurements(self) -> dict:
        out: dict[str, Any] = {}
        if self.tagged:
            out["tagged"] = {s: dict(sorted(v.items())) for s, v in sorted(self.tagged.items())}
        if self.undecided:
            out["undecided"] = dict(sorted(self.undecided.items()))
        return out


class GeometryTaggingEngine(RuleEngine):
    """Classifies lines as ``rotated`` and ``tiny`` and text regions as ``multi_column`` from their geometry, by rules.

    ``rotated``: a line whose recorded writing direction is vertical, or whose baseline (else its polygon, when it
    is clearly longer than high) is tilted by ``max_tilt`` degrees or more, is rotated; one tilted less is not. ``tiny``:
    a line lower than ``tiny`` times the median height of the page's body text lines is tiny; one at least that high is
    not. ``multi_column``: a text region with another text region beside it is in columns; one that spans
    ``full_width`` of the page's text width with nothing beside it is not. Each decision is a classification of the
    narrowest target (a line, a region) by the call's annotator (kind ``rule``), with its evidence (the line's tilt,
    height and ratio, the regions beside it) in the call's raw output (format ``json``); the annotator records the
    counts (``tagged``, ``undecided``) and the body lines' median height (``body_line_height``). Where the evidence
    does not decide (a line with only a box, too few body lines, a narrow region alone), nothing is recorded; with
    ``decide_no`` off only ``yes`` is, so that a model tagger asks about the rest. Lines and regions whose status is
    ``duplicate``, ``removed`` or ``suppressed`` are left alone. The vocabularies' definitions (``rotated``, ``tiny``,
    ``multi_column``) are what the rules implement; the thresholds are options.

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "tagging.geometry.v1"
    step = "tagging"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["tags"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)
    #: the page image is not needed: the rules read geometry only
    reads_image: ClassVar[bool] = False

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        schemes: list[Literal["rotated", "tiny", "multi_column"]] = Field(
            ["rotated", "tiny", "multi_column"], description="the property schemes it decides")
        decide_no: bool = Field(True, description="record no where the rules find the property absent; false: only "
                                                  "yes, the rest left to a model tagger")
        max_tilt: float = Field(5.0, gt=0, le=90, description="rotated: a line tilted by this many degrees or more "
                                                              "is rotated (the vocabulary's about 5 degrees)")
        elongation: float = Field(3.0, ge=1, description="rotated: a line without a baseline is measured from its "
                                                         "polygon only when that is at least this many times longer "
                                                         "than high (a single glyph says no angle)")
        tiny: float = Field(0.6, gt=0, lt=1, description="tiny: a line lower than this share of the median body "
                                                         "line height is tiny (6 pt fine print against 10-12 pt body "
                                                         "type; a running header at 8-9 pt stays above it)")
        min_body_lines: int = Field(5, ge=1, description="tiny: fewer body lines than this on a page decide nothing")
        body_roles: list[str] = Field(["paragraph", "list_item"], description="tiny: the roles of the regions whose "
                                                                              "lines are the page's body text")
        column_roles: list[str] = Field(list(COLUMN_ROLES), description="multi_column: the roles of the text "
                                                                        "regions that make columns")
        min_overlap: float = Field(0.25, gt=0, le=1, description="multi_column: two regions are beside each other "
                                                                 "when their extents across the lines overlap by at "
                                                                 "least this share of the shorter one")
        max_overlap: float = Field(0.1, ge=0, lt=1, description="multi_column: and their extents along the lines "
                                                                "overlap by at most this share of the narrower one")
        full_width: float = Field(0.8, gt=0, le=1, description="multi_column: a region alone that spans at least "
                                                               "this share of the page's text width is not in "
                                                               "columns")

    @classmethod
    def reads(cls, options: dict | None = None) -> tuple[str, ...]:
        """The parts it reads: the regions and the lines."""
        return ("regions", "lines")

    def __call__(self, image, t: Transcription, page: str | None = None, **options) -> Transcription:
        """Adds the page's classifications (``image`` and ``page`` are not used)."""
        o = self.configured(options)
        a = self.annotate(t, o)
        tally, evidence = _Tally(), {}
        decided: list[tuple[str, str, str]] = []
        if "rotated" in o.schemes or "tiny" in o.schemes:
            self._lines(t, o, tally, evidence, decided)
        if "multi_column" in o.schemes:
            self._columns(t, o, tally, evidence, decided)
        if decided:
            out = t.add_output(RawOutput(annotator=a, content=evidence, format="json"))
            for target, scheme, value in decided:
                t.classify(a, target, scheme, value, output=out)
        t.annotators[a].measurements.update(tally.measurements())
        if "body_line_height" in evidence:
            t.annotators[a].measurements["body_line_height"] = evidence["body_line_height"]
        return t

    def _decide(self, o, tally, decided, target, scheme, value) -> None:
        if value is None or (value == "no" and not o.decide_no):
            tally.skip(scheme)
            return
        tally.tag(scheme, value)
        decided.append((target, scheme, value))

    def _lines(self, t, o, tally, evidence, decided) -> None:
        lines = [ln for ln in t.lines if t.status(ln.id) not in SKIPPED_STATUSES]
        measured = {}
        for ln in lines:
            direction = t.direction(ln.id)
            m = line_measure(ln, _vertical(direction), o.elongation)
            if _vertical(direction):
                m["direction"] = direction
            measured[ln.id] = m
        if "rotated" in o.schemes:
            for ln in lines:
                m = measured[ln.id]
                value = None
                if "direction" in m:
                    value = "yes"
                elif m["tilt"] is not None:
                    value = "yes" if abs(m["tilt"]) >= o.max_tilt else "no"
                self._decide(o, tally, decided, ln.id, "rotated", value)
        if "tiny" in o.schemes:
            placed = any(t.region_of(ln) for ln in lines)

            def body_line(ln) -> bool:
                if not placed:
                    return True
                rid = t.region_of(ln)
                region = t.region(rid) if rid else None
                return region is not None and _role(t, region) in o.body_roles

            body = [measured[ln.id]["height"] for ln in lines if measured[ln.id]["height"] and body_line(ln)]
            median = float(np.median(body)) if len(body) >= o.min_body_lines else None
            if median is not None:
                evidence["body_line_height"] = round(median, 2)
            for ln in lines:
                m = measured[ln.id]
                value = None
                if median and m["height"]:
                    m["ratio"] = round(m["height"] / median, 3)
                    value = "yes" if m["ratio"] < o.tiny else "no"
                self._decide(o, tally, decided, ln.id, "tiny", value)
        shown = {lid: {k: v for k, v in m.items() if v is not None} for lid, m in measured.items()}
        if shown:
            evidence["lines"] = shown

    def _columns(self, t, o, tally, evidence, decided) -> None:
        direction = t.direction("")
        regions = [(r, to_frame(b, direction)) for r in t.regions
                   if t.status(r.id) not in SKIPPED_STATUSES and _role(t, r) in o.column_roles
                   and (b := zone_bbox(r)) is not None]
        if not regions:
            return
        x0 = min(b.x0 for _, b in regions)
        x1 = max(b.x1 for _, b in regions)
        text_width = x1 - x0
        found = {}
        for r, b in regions:
            beside = []
            for s, c in regions:
                if s is r:
                    continue
                across = min(b.y1, c.y1) - max(b.y0, c.y0)
                along = min(b.x1, c.x1) - max(b.x0, c.x0)
                if across >= o.min_overlap * min(b.height, c.height) > 0 \
                        and along <= o.max_overlap * min(b.width, c.width):
                    beside.append(s.id)
            share = b.width / text_width if text_width > 0 else 1.0
            value = "yes" if beside else ("no" if share >= o.full_width else None)
            found[r.id] = {"beside": beside, "width": round(share, 3)} if beside else {"width": round(share, 3)}
            self._decide(o, tally, decided, r.id, "multi_column", value)
        evidence["regions"] = found


# ------------------------------------------------------------------------------------------------ the panel

class Member(BaseModel):
    """One model of the panel: a chat preset of the catalog or a served model, where it is served, how it samples."""

    model_config = ConfigDict(extra="forbid")

    preset: str | None = Field(None, description="a chat preset of the catalog (chat.v1): its model, revision and "
                                                 "hash are recorded; the served name defaults to its Hugging Face id")
    model: str | None = Field(None, description="the name the server hosts the model under (default: the preset's "
                                                "Hugging Face id)")
    revision: str | None = Field(None, description="the model's revision, where no preset gives it (recorded, and "
                                                   "part of the cache key)")
    url: str = Field("http://127.0.0.1:8000/v1", description="the OpenAI-compatible server's base URL (operational: "
                                                             "not recorded)")
    api_key_env: str | None = Field(None, description="the environment variable that holds the server's API key, "
                                                      "if it needs one (the key is never recorded)")
    max_tokens: int = Field(512, ge=16, description="the cap of the answer (a reason and an answer)")
    temperature: float = Field(0.0, ge=0, description="the sampling temperature")

    @model_validator(mode="after")
    def _named(self):
        if not (self.preset or self.model):
            raise ValueError("a panel member names a preset or a model")
        return self


class _Asked:
    """One member's answer to one question."""

    __slots__ = ("member", "content", "finish", "usage", "answer", "value", "reason", "sent", "error")

    def __init__(self, member: str, content: str, finish: str | None, usage: dict, sent: bool):
        self.member, self.content, self.finish, self.usage, self.sent = member, content, finish, usage, sent
        self.answer = self.value = self.reason = self.error = None


def parse_answer(content: str, answers: dict[str, str]) -> tuple[str | None, str | None, str | None]:
    """A completion's ``answer`` (as written, lowercased), the value it means (``answers``: answer -> value; ``None``
    for ``cannot_tell``, ``not_here`` or anything else) and its ``reason``: from the JSON object in it (code fences
    and text around it allowed), else from an ``"answer": "..."`` pair in the text."""
    text = (content or "").strip()
    data = None
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            data = None
    if isinstance(data, dict):
        answer, reason = data.get("answer"), data.get("reason")
    else:
        m = re.search(r'"answer"\s*:\s*"([^"]*)"', text)
        r = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        answer, reason = (m.group(1) if m else None), (r.group(1) if r else None)
    answer = answer.strip().lower() if isinstance(answer, str) else None
    return answer, answers.get(answer) if answer else None, reason if isinstance(reason, str) else None


def settle(rule: str, values: dict[str, str | None]) -> tuple[str | None, str | None, str]:
    """The panel's decision: ``values`` are the members' (``a``, ``b`` and, where asked, ``c``; ``None``: no answer).
    Returns the value, the member it follows and how it was decided (``agreed``, ``first``, ``referee``,
    ``majority``, ``undecided``)."""
    a, b = values.get("a"), values.get("b")
    if a is not None and a == b:
        return a, "a", "agreed"
    if rule == "first":
        return (a, "a", "first") if a is not None else (None, None, "undecided")
    if "c" not in values:
        return None, None, "undecided"
    c = values["c"]
    if rule == "majority":
        votes = [(m, v) for m, v in (("a", a), ("b", b), ("c", c)) if v is not None]
        for m, v in votes:
            if sum(1 for _, w in votes if w == v) >= 2:
                return v, m, "majority"
        return None, None, "undecided"
    if a is not None and c == a:
        return a, "a", "referee"
    if a is None and b is not None and c == b:
        return b, "b", "referee"
    return None, None, "undecided"


def _needs_referee(rule: str, a: str | None, b: str | None) -> bool:
    """Whether the referee's answer can decide: the two split or one gave none, the rule takes a referee, and one of
    the two answered (two without an answer leave it nothing to agree with)."""
    if (a is not None and a == b) or rule == "first":
        return False
    return a is not None or b is not None


#: the target as a question names it
NOUNS = {"line": "line of text", "region": "region", "page": "page"}


def question(vocabulary, target: str, views: list[str]) -> str:
    """The question for one target of kind ``target`` (``line``, ``region``, ``page``) in ``vocabulary``'s scheme, the
    images ``views`` (``page``, ``crop``) shown first: generated from the vocabulary's definitions, the reason asked
    for first and the answer last."""
    noun = NOUNS[target]
    if target == "page":
        seen = ["The image shows a page."]
        place = "the page"
    else:
        seen = []
        for k, v in enumerate(views):
            which = ("The first image" if k == 0 else "The second image") if len(views) > 1 else "The image"
            seen.append(f"{which} shows the page with a red box drawn around one {noun}." if v == "page" else
                        f"{which} shows that {noun} enlarged, with the same red box around it.")
        place = f"the {noun} inside the red box"
    allowed = list(vocabulary.answer_values())
    lines = [" ".join(seen), ""]

    def term(name, t):
        out = [f"{name}: {t.definition}"]
        if t.counts:
            out += ["  Counts:", *[f"  - {x}" for x in t.counts]]
        if t.does_not_count:
            out += ["  Does not count:", *[f"  - {x}" for x in t.does_not_count]]
        return out

    if vocabulary.answers:
        yes, no = vocabulary.answers["yes"], vocabulary.answers["no"]
        lines += [f"Decide whether {place} is {yes} or {no}, by this definition.", "",
                  *term(yes, vocabulary.values["yes"]), *term(no, vocabulary.values["no"])]
    else:
        lines += [f"Decide which one of these {place} is, by their definitions.", ""]
        for name, t in vocabulary.values.items():
            lines += term(name, t)
    lines += ["", f"The content is {place}; judge nothing else." + ("" if target == "page" else
              " Answer not_here if the red box marks no content."),
              "Answer cannot_tell if the image does not let you decide.",
              "Reply with one JSON object and nothing else, the reason first and the answer last:",
              '{"reason": "<what you see that decides it, in one or two sentences>", "answer": "<one of: '
              + ", ".join([*allowed, "cannot_tell", *([] if target == "page" else ["not_here"])]) + '>"}']
    return "\n".join(lines)


def cache_root() -> Path:
    """The tagging cache's folder: ``$LINECASTER_CACHE/tagging``, else ``~/.cache/linecaster/tagging``."""
    base = os.environ.get("LINECASTER_CACHE")
    return (Path(base) if base else Path.home() / ".cache" / "linecaster") / "tagging"


def cache_key(body: dict, revision: str | None) -> str:
    """The hash of everything a member was shown: the request body (model, messages with their images, sampling)
    and the model's revision."""
    blob = json.dumps({"body": body, "revision": revision}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class ChatTaggingEngine(RuleEngine):
    """Classifies zones in property schemes (and other closed schemes) by a panel of vision-language models behind
    OpenAI-compatible chat servers: one question per target and scheme, generated from the scheme's vocabulary, two
    members asked and a third on their splits, a rule per scheme for what the third decides, the answers cached under
    a hash of everything shown, the undecided written for review.

    Each member sees the page with the target's box drawn and the target enlarged (``views``), and the question: the
    vocabulary's definition with what counts and what does not, the answers named after the property (or the
    scheme's values), ``cannot_tell`` and ``not_here``, and the reply asked for as JSON, the reason first. The two
    members (``panel``) agree: that is the classification. They split, or one gives no answer: the ``referee`` is
    asked, and the scheme's rule (``settle``, else ``default_settle``) decides: ``first_with_referee`` (the referee
    must give the first member's answer; where the first gave none, the second's), ``majority`` (two of three) or
    ``first`` (the first member alone, no referee). An item no rule settles is undecided: nothing is recorded, and it
    is written to ``review`` as a JSON line. The call's annotator (kind ``model``) records the members (their presets,
    revisions and sampling; never their URLs or keys), the views, the rules and each vocabulary's hash; every
    member's completion is a raw output (its settings name the member, target and scheme), and each classification
    names the one it follows. Answers are cached (``cache``) under the hash of the request and the model's revision
    (``$LINECASTER_CACHE/tagging``, else ``~/.cache/linecaster/tagging``). A request that fails after ``retries`` is a
    ``ServerError``. The design is in the module's docstring (``linecaster.engines.tagging``).

    Args:
        **options: the engine's options, the fields of its ``Options`` model (described there); a preset's
            ``options`` construct it."""

    engine_id: ClassVar[str] = "tagging.chat.v1"
    step = "tagging"
    capabilities: ClassVar[dict] = {"unit": "page", "produces": ["tags"]}
    scripts: ClassVar[tuple[str, ...]] = ("*",)
    #: the page image is cut into the views the members see
    reads_image: ClassVar[bool] = True

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        schemes: list[str] = Field(min_length=1, description="the schemes it asks about: closed vocabularies of the "
                                                             "catalog, property schemes above all")
        target: Literal["line", "region", "page"] = Field("region", description="what it asks about: each line, "
                                                                                "each region, or the page; one of "
                                                                                "the targets of every scheme's "
                                                                                "vocabulary")
        skip_roles: list[str] = Field(["separator", "noise"], description="regions of these roles (and their "
                                                                          "lines) are not asked about")
        panel: list[Member] = Field(min_length=2, max_length=2, description="the two members asked about every "
                                                                            "target, the one a review found right "
                                                                            "more often first")
        referee: Member | None = Field(None, description="the third member, asked where the two split or one gave "
                                                         "no answer; none: splits are undecided, except by the rule "
                                                         "first")
        settle: dict[str, Literal["first_with_referee", "majority", "first"]] = Field(
            default_factory=dict, description="scheme -> the rule that settles a split (first_with_referee, "
                                              "majority, first); schemes not named: default_settle")
        default_settle: Literal["first_with_referee", "majority", "first"] = Field(
            "first_with_referee", description="the rule of the schemes settle does not name")
        views: list[Literal["page", "crop"]] = Field(["page", "crop"], min_length=1,
                                                     description="the images each member sees: the page with the "
                                                                 "target's box drawn, the target enlarged with the "
                                                                 "same box (a page target: the page alone)")
        page_longest: int = Field(1280, ge=64, description="the page view's longest side at most, in pixels")
        crop_longest: int = Field(1024, ge=64, description="the crop view's longest side at most, in pixels")
        context: float = Field(0.5, ge=0, description="the margin around the target in the crop, as a share of "
                                                      "its longer side (at least 16 pixels)")
        box_width: int = Field(3, ge=1, description="the red box's line width in the images sent, in pixels")
        cache: bool = Field(True, description="answers cached under the hash of everything shown and the model's "
                                              "revision, and read from there")
        cache_dir: str | None = Field(None, description="the cache's folder (operational; default "
                                                        "$LINECASTER_CACHE/tagging, else ~/.cache/linecaster/tagging)")
        review: str | None = Field(None, description="a folder for the undecided items, as JSON lines "
                                                     "(operational; none: not written)")
        review_images: bool = Field(True, description="a review item holds the images the members saw (PNG data "
                                                      "URLs)")
        concurrency: int = Field(4, ge=1, description="questions in flight at once, within the page (operational)")
        timeout: float = Field(300.0, gt=0, description="a request's timeout in seconds (operational)")
        retries: int = Field(2, ge=0, description="a failed request is sent again this many times before it is a "
                                                  "ServerError (operational)")

        @model_validator(mode="after")
        def _settled(self):
            unknown = sorted(set(self.settle) - set(self.schemes))
            if unknown:
                raise ValueError(f"settle names schemes it does not ask about: {unknown}")
            return self

    #: options that say where and how it runs, not what it answers: left out of the annotator's settings
    OPERATIONAL: ClassVar[tuple[str, ...]] = ("cache", "cache_dir", "review", "review_images", "concurrency",
                                              "timeout", "retries")

    def __init__(self, **options):
        super().__init__(**options)
        self._vocabularies: dict[str, tuple[Any, str]] = {}
        self._resolved: dict[str, dict] = {}
        self._token = uuid.uuid4().hex[:12]
        self._lock = threading.Lock()

    @classmethod
    def reads(cls, options: dict | None = None) -> tuple[str, ...]:
        """The parts it reads: the page image and its targets (regions or lines; the page: nothing more)."""
        target = (options or {}).get("target", "region")
        return ("image",) + ({"region": ("regions",), "line": ("lines",)}.get(target, ()))

    def load(self) -> None:
        """Resolves the schemes' vocabularies and the members' presets from the catalog (checked: closed schemes
        whose vocabulary lists the target, presets of ``chat.v1``)."""
        self._check(self.options)

    def _check(self, o) -> None:
        for scheme in o.schemes:
            v, _ = self._vocabulary(scheme)
            if v.open:
                raise PipelineConfigError(f"{self.engine_id}: {scheme} is an open scheme; only closed vocabularies are "
                                          "asked")
            if o.target not in v.targets:
                raise PipelineConfigError(f"{self.engine_id}: {scheme} classifies {', '.join(v.targets)}, not a "
                                          f"{o.target}")
        for m in [*o.panel, *([o.referee] if o.referee else [])]:
            self._member(m)

    def _vocabulary(self, scheme: str):
        if scheme not in self._vocabularies:
            from linecaster.catalog.registry import catalog
            from linecaster.errors import CatalogError

            try:
                c = catalog()
                self._vocabularies[scheme] = (c.vocabulary(scheme), c.vocabulary_sha256(scheme))
            except CatalogError as e:
                raise PipelineConfigError(f"{self.engine_id}: {e}") from None
        return self._vocabularies[scheme]

    def _member(self, m: Member) -> dict:
        """A member as it is asked and recorded: served name, revision, preset and its hash, sampling."""
        key = m.model_dump_json()
        if key not in self._resolved:
            out = {"model": m.model, "revision": m.revision, "preset": None, "preset_sha256": None}
            if m.preset:
                from linecaster.catalog.registry import catalog
                from linecaster.errors import CatalogError

                try:
                    c = catalog()
                    r = c.resolve(m.preset)
                    if r.engine != "chat.v1" or not r.content.get("model"):
                        raise PipelineConfigError(f"{self.engine_id}: {m.preset} is not a chat preset (chat.v1)")
                    pin = r.content["model"]
                    out.update(preset=r.ref, preset_sha256=r.sha256, revision=pin["revision"],
                               model=m.model or c.model(pin["id"]).source.ref)
                except CatalogError as e:
                    raise PipelineConfigError(f"{self.engine_id}: {e}") from None
            out.update(max_tokens=m.max_tokens, temperature=m.temperature)
            self._resolved[key] = out
        return self._resolved[key]

    def _rules(self, o) -> dict[str, str]:
        return {s: o.settle.get(s, o.default_settle) for s in o.schemes}

    def _annotator_of(self, o, members: dict[str, dict]) -> Annotator:
        settings = o.model_dump(mode="json", exclude={*self.OPERATIONAL, "panel", "referee", "settle",
                                                      "default_settle"})
        record = {k: {f: v for f, v in m.items() if v is not None} for k, m in members.items()}
        settings.update(panel=[record["a"], record["b"]], referee=record.get("c"), settle=self._rules(o),
                        vocabularies={s: self._vocabulary(s)[1] for s in o.schemes})
        name = " + ".join(m["model"] for m in members.values())
        return Annotator(kind="model", step=self.step, name=name, engine=self.engine_id, settings=settings)

    # ------------------------------------------------------------------ the call
    def __call__(self, image, t: Transcription, page: str | None = None, **options) -> Transcription:
        """Adds the page's classifications; ``image`` is the page image (an RGB array), ``page`` its id (named in
        the review items)."""
        o = self.configured(options)
        if options:
            self._check(o)
        if image is None:
            raise PipelineConfigError(f"{self.engine_id}: the model tagger needs the page image")
        members = {"a": self._member(o.panel[0]), "b": self._member(o.panel[1])}
        if o.referee is not None:
            members["c"] = self._member(o.referee)
        specs = {"a": o.panel[0], "b": o.panel[1], **({"c": o.referee} if o.referee is not None else {})}
        a = t.add_annotator(self._annotator_of(o, members))
        targets = self._targets(t, o)
        rules = self._rules(o)
        page_image = self._page_image(image, o)
        views = {ref: self._views(page_image, box, o) for ref, box in targets}
        questions = [(ref, box, s) for ref, box in targets for s in o.schemes]

        def ask(q):
            ref, box, scheme = q
            vocab = self._vocabulary(scheme)[0]
            kinds, images = views[ref]
            text = question(vocab, o.target, kinds)
            allowed = vocab.answer_values()
            got: dict[str, _Asked] = {}
            for k in ("a", "b"):
                got[k] = self._ask(k, members[k], specs[k], images, text, allowed, o)
            if "c" in members and _needs_referee(rules[scheme], got["a"].value, got["b"].value):
                got["c"] = self._ask("c", members["c"], specs["c"], images, text, allowed, o)
            value, follows, how = settle(rules[scheme], {k: g.value for k, g in got.items()})
            return got, value, follows, how, text, images

        if o.concurrency > 1 and len(questions) > 1:
            with ThreadPoolExecutor(max_workers=o.concurrency) as pool:
                results = list(pool.map(ask, questions))
        else:
            results = [ask(q) for q in questions]
        tally = _Tally()
        counts: dict[str, Any] = {"agreed": 0, "settled": 0, "asked": {}, "cached": {}}
        tokens = {"prompt_tokens": 0, "completion_tokens": 0}
        for (ref, box, scheme), (got, value, follows, how, text, images) in zip(questions, results):
            index = {}
            for k, g in got.items():
                index[k] = t.add_output(RawOutput(
                    annotator=a, content=g.content, format="text", kept=(k == follows), finish_reason=g.finish,
                    prompt_tokens=g.usage.get("prompt_tokens"), completion_tokens=g.usage.get("completion_tokens"),
                    settings={"member": k, "target": ref, "scheme": scheme}))
                where = "asked" if g.sent else "cached"
                counts[where][k] = counts[where].get(k, 0) + 1
                if g.sent:
                    for key in tokens:
                        if isinstance(g.usage.get(key), int):
                            tokens[key] += g.usage[key]
            if value is None:
                tally.skip(scheme)
                self._review(o, page, ref, box, scheme, rules[scheme], got, members, images)
                continue
            counts["agreed" if how == "agreed" else "settled"] += 1
            tally.tag(scheme, value)
            t.classify(a, ref, scheme, value, output=index[follows])
        m = t.annotators[a].measurements
        m.update(tally.measurements())
        m.update({k: v for k, v in counts.items() if v})
        m.update({k: v for k, v in tokens.items() if v})
        return t

    def _targets(self, t: Transcription, o) -> list[tuple[str, list[float] | None]]:
        """The targets in the transcription's order, each with its box (``[x, y, w, h]``; the page: none)."""
        if o.target == "page":
            return [("", None)]
        skipped = {r.id for r in t.regions if _role(t, r) in o.skip_roles or t.status(r.id) in SKIPPED_STATUSES}
        zones = t.regions if o.target == "region" else [
            ln for ln in t.lines if t.region_of(ln) not in skipped and t.status(ln.id) not in SKIPPED_STATUSES]
        out = []
        for z in zones:
            if o.target == "region" and z.id in skipped:
                continue
            b = zone_bbox(z)
            if b is not None and b.width > 0 and b.height > 0:
                out.append((z.id, [b.x0, b.y0, b.width, b.height]))
        return out

    @staticmethod
    def _page_image(image, o):
        """The page as a Pillow image, and as the page view shows it (at most ``page_longest``) with its scale."""
        from PIL import Image

        img = Image.fromarray(np.asarray(image)).convert("RGB")
        s = min(1.0, o.page_longest / max(img.size))
        shown = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS) \
            if s < 1 else img
        return img, shown, s

    def _views(self, page_image, box, o) -> tuple[list[str], list[str]]:
        """The images a member sees, as base64 PNGs (``linecaster.adapters.png_bytes``), with what each is."""
        from PIL import Image, ImageDraw

        from linecaster.adapters import png_bytes

        img, shown, scale = page_image
        kinds, out = [], []

        def drawn(view, rect, scale):
            if rect is not None:
                x, y, w, h = (v * scale for v in rect)
                ImageDraw.Draw(view).rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=o.box_width)
            return view

        for kind in o.views:
            if kind == "page":
                out.append(png_bytes(drawn(shown.copy(), box, scale)))
                kinds.append("page")
            elif box is not None:
                x, y, w, h = box
                margin = max(16.0, o.context * max(w, h))
                x0, y0 = max(0, int(x - margin)), max(0, int(y - margin))
                x1, y1 = min(img.width, int(math.ceil(x + w + margin))), min(img.height, int(math.ceil(y + h + margin)))
                v = img.crop((x0, y0, x1, y1))
                s = min(1.0, o.crop_longest / max(v.size))
                if s < 1:
                    v = v.resize((max(1, round(v.width * s)), max(1, round(v.height * s))), Image.LANCZOS)
                out.append(png_bytes(drawn(v, [x - x0, y - y0, w, h], s)))
                kinds.append("crop")
        if not out:            # a page target with only a crop asked for: the page
            out.append(png_bytes(shown))
            kinds.append("page")
        return kinds, out

    def _body(self, member: dict, images: list[str], text: str) -> dict:
        from linecaster.adapters import data_url

        return {"model": member["model"], "max_tokens": member["max_tokens"], "temperature": member["temperature"],
                "messages": [{"role": "user", "content": [*(data_url("image/png", b) for b in images),
                                                          {"type": "text", "text": text}]}]}

    def _ask(self, k: str, member: dict, spec: Member, images: list[str], text: str, allowed: dict, o) -> _Asked:
        body = self._body(member, images, text)
        key = cache_key(body, member.get("revision"))
        path = (Path(o.cache_dir) if o.cache_dir else cache_root()) / key[:2] / f"{key}.json"
        hit = None
        if o.cache and path.exists():
            try:
                hit = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                hit = None
        if hit is not None:
            got = _Asked(k, hit.get("content") or "", hit.get("finish_reason"), hit.get("usage") or {}, sent=False)
        else:
            response = self._post(spec, body, o)
            choices = response.get("choices") or []
            if not choices:
                raise ServerError(f"{self.engine_id}: no choices in the answer of {member['model']}: "
                                  f"{json.dumps(response)[:300]}")
            content = choices[0].get("message", {}).get("content") or ""
            got = _Asked(k, content, choices[0].get("finish_reason"), response.get("usage") or {}, sent=True)
            if o.cache:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
                tmp.write_text(json.dumps({"content": content, "finish_reason": got.finish, "usage": got.usage,
                                           "model": member["model"], "revision": member.get("revision"),
                                           "linecaster": producer()}, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, path)
        got.answer, got.value, got.reason = parse_answer(got.content, allowed)
        return got

    def _post(self, spec: Member, body: dict, o) -> dict:
        """``body`` to the member's server's ``/chat/completions``; a failure sent again ``retries`` times (after 1,
        2, 4 ... seconds), then a ``ServerError``."""
        headers = {"Content-Type": "application/json"}
        if spec.api_key_env:
            key = os.environ.get(spec.api_key_env)
            if not key:
                raise PipelineConfigError(f"{self.engine_id}: the environment variable {spec.api_key_env} is not set")
            headers["Authorization"] = f"Bearer {key}"
        data = json.dumps(body).encode()
        url = spec.url.rstrip("/") + "/chat/completions"
        for attempt in range(o.retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=o.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code not in (408, 429, 500, 502, 503, 504) or attempt == o.retries:
                    raise ServerError(f"{self.engine_id}: {url} answered {e.code}: {e.read()[:300]!r}") from None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                if attempt == o.retries:
                    raise ServerError(f"{self.engine_id}: {url} did not answer: {e}") from None
            time.sleep(2 ** attempt)
        raise ServerError(f"{self.engine_id}: {url} did not answer")   # pragma: no cover - the loop returns or raises

    def _review(self, o, page, ref, box, scheme, rule, got, members, images) -> None:
        """An undecided item, as one JSON line of the instance's review file."""
        if not o.review:
            return
        item = {"schema": REVIEW_SCHEMA, "linecaster": producer(), "page": page, "target": ref, "box": box,
                "scheme": scheme, "target_kind": o.target, "settle": rule,
                "vocabulary_sha256": self._vocabulary(scheme)[1],
                "answers": [{"member": k, "model": members[k]["model"], "revision": members[k].get("revision"),
                             "answer": g.answer, "value": g.value, "reason": g.reason, "content": g.content}
                            for k, g in got.items()]}
        if o.review_images:
            item["images"] = [f"data:image/png;base64,{b}" for b in images]
        folder = Path(o.review)
        with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / f"review-{self._token}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
