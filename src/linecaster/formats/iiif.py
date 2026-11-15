"""An annotation set as an IIIF Presentation 3 annotation page (W3C Web Annotations on the page's canvas).

``to_annotation_page(t, canvas, id)`` writes one annotation per region (motivation ``classifying``, its content
role as the body), per line with a reading (``supplementing``, IIIF's motivation for a transcription, with the
text granularity extension's ``textGranularity`` ``line``), per word (``word``), per description (``describing``)
and per edit (``editing``, targeting the line's annotation). Targets are the canvas with a media fragment
(``#xywh=``) where the annotation has a box, the canvas itself where it has none. Each annotation's ``generator``
(``creator`` for people) is its annotator's name. A line's, a word's and an edit's body has the ``language`` its
target records (``Transcription.language``: its own, else its line's, region's or page's); a region's body has none.

``from_annotation_page(data)`` reads such a page back, and annotation pages of other software that follow the same
conventions: ``classifying`` annotations with a box as regions (their body's value the role), ``supplementing`` ones
(also ``transcribing`` and ``commenting`` with ``textGranularity`` ``line``) as lines, those of granularity ``word``
as the words of the line whose box holds them, ``editing`` ones whose purpose is an edit kind as edits of their
line, ``describing`` ones as descriptions of their region. Targets are read as a media fragment (``#xywh=``, in
pixels, or ``percent:`` of the canvas size where it is given), a ``FragmentSelector`` or an ``SvgSelector`` with a
polygon; a target without one is the whole canvas (a line without a box). A line belongs to the region whose box
holds most of its own. Each body's ``language`` is recorded: on the page where every line states the same one, else
on each line (and on a word that states another). Annotators are the annotations' ``creator`` (people) and
``generator`` (software); without either, the file.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.refs import parse, word as word_ref
from ..data.geometry import BBox, bbox_of
from ..data.transcription import EDITS, AnnotationSet, Annotator, Description, Edit, Source, Transcription, Word
from ..data.writing import language_tag

CONTEXT = ["http://iiif.io/api/extension/text-granularity/context.json",
           "http://iiif.io/api/presentation/3/context.json"]


def _target(canvas: str, box) -> str:
    if box is None:
        return canvas
    x, y, w, h = (round(v) for v in box)
    return f"{canvas}#xywh={x},{y},{w},{h}"


def _by(t: AnnotationSet, annotator: int) -> dict[str, Any]:
    a = t.annotators[annotator] if 0 <= annotator < len(t.annotators) else None
    if a is None:
        return {}
    agent = {"id": f"https://linecaster.invalid/annotator/{annotator}", "type": "Person" if a.kind == "human"
             else "Software", "name": a.name}
    return {"creator" if a.kind == "human" else "generator": agent}


def _body(value: str, purpose: str | None = None, language: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "TextualBody", "value": value, "format": "text/plain"}
    if purpose:
        body["purpose"] = purpose
    if language:
        body["language"] = language
    return body


def to_annotation_page(t: AnnotationSet, canvas: str, id: str,
                       policy: RenderingPolicy = DEFAULT_POLICY) -> dict[str, Any]:
    """The annotation page of ``t`` on ``canvas`` (the page's canvas URI), with ``id`` as its id (annotations
    ``<id>/<n>``). Regions the policy puts nowhere are left out, with their lines."""
    items: list[dict[str, Any]] = []
    hidden = {r.id for r in t.regions if policy.layer_of(t, r.id) == "none"}
    line_ids: dict[str, str] = {}

    def add(motivation: str, body: dict, target: str, annotator: int, **extra) -> str:
        aid = f"{id}/{len(items)}"
        items.append({"id": aid, "type": "Annotation", "motivation": motivation, "body": body, "target": target,
                      **_by(t, annotator), **extra})
        return aid

    for r in t.ordered_regions():
        if r.id in hidden:
            continue
        add("classifying", _body(t.role(r.id) or "paragraph", "classifying"), _target(canvas, r.box), r.annotator)
    if isinstance(t, Transcription):
        hidden_lines = {c.target for c in t.classifications if c.scheme == "status"
                        and policy.layer(None, status=c.value) == "none"}
        for ln in t.ordered_lines(hidden=True):
            if ln.reading is None or t.region_of(ln) in hidden or ln.id in hidden_lines:
                continue
            line_ids[ln.id] = add("supplementing", _body(t.text_of(ln), language=t.language(ln.id)),
                                  _target(canvas, ln.box or (t.region(t.region_of(ln)).box
                                                             if t.region_of(ln) and t.region(t.region_of(ln))
                                                             else None)),
                                  ln.reading.annotator, textGranularity="line")
            for k, w in enumerate(ln.reading.words):
                add("supplementing", _body(w.text, language=t.language(word_ref(ln.id, k))), _target(canvas, w.box),
                    ln.reading.annotator, textGranularity="word")
        for e in t.edits:
            ref = parse(e.target)
            target = line_ids.get(ref.id)
            if target is not None and ref.page is None:
                add("editing", _body(e.text, e.kind, t.language(e.target)), target, e.annotator)
    for d in t.descriptions:
        r = t.region(d.target)
        if r is not None and r.id not in hidden:
            add("describing", _body(d.text, d.kind), _target(canvas, r.box), d.annotator)
    return {"@context": CONTEXT, "id": id, "type": "AnnotationPage", "items": items}


_XYWH = re.compile(r"xywh=(?:(pixel|percent):)?\s*([\d.]+),([\d.]+),([\d.]+),([\d.]+)")
_POINTS = re.compile(r"points\s*=\s*[\"']([^\"']+)[\"']")
_LINES = ("supplementing", "transcribing", "commenting", "painting")


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _selector_shape(selector: dict, size: tuple[float, float] | None) -> tuple[list | None, list | None]:
    """A selector's box (x, y, w, h) and polygon."""
    kind, value = selector.get("type"), str(selector.get("value", ""))
    if kind == "SvgSelector":
        m = _POINTS.search(value)
        if m:
            nums = [float(v) for v in re.split(r"[\s,]+", m.group(1).strip()) if v]
            polygon = [[nums[i], nums[i + 1]] for i in range(0, len(nums) - 1, 2)]
            if len(polygon) >= 3:
                b = bbox_of(polygon)
                return [b.x0, b.y0, b.width, b.height], polygon
        return None, None
    return _fragment_box(value, size), None


def _fragment_box(fragment: str, size: tuple[float, float] | None) -> list | None:
    m = _XYWH.search(fragment)
    if not m:
        return None
    x, y, w, h = (float(v) for v in m.groups()[1:])
    if m.group(1) == "percent":
        if size is None:
            return None
        x, w, y, h = x * size[0] / 100, w * size[0] / 100, y * size[1] / 100, h * size[1] / 100
    return [x, y, w, h]


def _target_shape(target, size) -> tuple[str | None, list | None, list | None]:
    """The target's source (a canvas or an annotation's id), box and polygon."""
    target = _first(target)
    if isinstance(target, str):
        source, _, fragment = target.partition("#")
        return source, _fragment_box(fragment, size) if fragment else None, None
    if isinstance(target, dict):
        source = target.get("source")
        source = source.get("id") if isinstance(source, dict) else source
        selector = _first(target.get("selector"))
        if isinstance(selector, dict):
            return source, *_selector_shape(selector, size)
        return source or target.get("id"), None, None
    return None, None, None


def _text_bodies(body) -> list[dict]:
    bodies = body if isinstance(body, list) else [body]
    return [b for b in bodies if isinstance(b, dict) and ("value" in b or "chars" in b)]


def _value(body: dict) -> str:
    return str(body.get("value", body.get("chars", "")))


def from_annotation_page(data: bytes | str | dict, uri: str | None = None, ground_truth: bool = False,
                         image_width: int | None = None, image_height: int | None = None) -> Transcription:
    """An IIIF annotation page (JSON) as a transcription (the module's docstring); ``image_width`` and
    ``image_height``: the canvas's size, for boxes in percent; ``ground_truth``: the annotations' people and the file
    are read as people's (kind ``human``)."""
    page = data if isinstance(data, dict) else json.loads(data)
    size = (float(image_width), float(image_height)) if image_width and image_height else None
    t = Transcription(source=Source(kind="ground_truth" if ground_truth else "converted", format="iiif", uri=uri,
                                    image_width=image_width, image_height=image_height))
    agents: dict[tuple, int] = {}

    def annotator(item: dict) -> int:
        agent = _first(item.get("creator")) or _first(item.get("generator"))
        person = bool(item.get("creator")) or (isinstance(agent, dict) and agent.get("type") == "Person")
        name = (agent.get("name") or agent.get("id") if isinstance(agent, dict) else agent) or "annotation page"
        name = _value(name) if isinstance(name, dict) else str(_first(name))
        kind = "human" if person or ground_truth else ("model" if agent else "file")
        key = (kind, name)
        if key not in agents:
            agents[key] = t.add_annotator(Annotator(kind=kind, step="transcription", name=name))
        return agents[key]

    items = page.get("items") or page.get("resources") or []
    regions: list[tuple[str, BBox]] = []
    lines: dict[str, Any] = {}                       # annotation id -> line
    words: list[tuple[dict, int, list]] = []
    rest: list[dict] = []
    languages: dict[str, str] = {}                   # line id -> its body's language
    for item in items:
        motivation = _first(item.get("motivation"))
        granularity = item.get("textGranularity")
        bodies = _text_bodies(item.get("body") or item.get("resource"))
        if motivation == "classifying":
            _src, box, polygon = _target_shape(item.get("target"), size)
            if box is None:
                continue
            rid = f"r{len(regions)}"
            role = _value(bodies[0]) if bodies else None
            t.add_region(annotator(item), rid, box, polygon, label=role or "", role=role or None)
            regions.append((rid, BBox(box[0], box[1], box[0] + box[2], box[1] + box[3])))
        elif motivation in _LINES and granularity == "word":
            words.append((item, annotator(item), bodies))
        elif motivation in _LINES and (granularity in (None, "line") and bodies):
            if motivation == "commenting" and granularity is None:
                continue                              # a comment, not a transcription
            _src, box, polygon = _target_shape(item.get("target"), size)
            a = annotator(item)
            ln = t.add_line(a, f"l{len(t.lines)}", box, polygon, text=_value(bodies[0]))
            if item.get("id"):
                lines[item["id"]] = ln
            if language_tag(bodies[0].get("language")):
                languages[ln.id] = language_tag(bodies[0].get("language"))
        else:
            rest.append(item)
    for ln in t.lines:                                 # a line is in the region that holds most of it
        if ln.box is None:
            continue
        lb = BBox(ln.box[0], ln.box[1], ln.box[0] + ln.box[2], ln.box[1] + ln.box[3])
        area = max(lb.width * lb.height, 1e-9)
        best = max(regions, key=lambda r: r[1].intersection_area(lb), default=None)
        if best is not None and best[1].intersection_area(lb) / area > 0.5:
            ln.region = best[0]
    for item, a, bodies in words:
        _src, box, _polygon = _target_shape(item.get("target"), size)
        if box is None or not bodies:
            continue
        wb = BBox(box[0], box[1], box[0] + box[2], box[1] + box[3])
        owner = max((ln for ln in t.lines if ln.box is not None and ln.reading is not None),
                    key=lambda ln: wb.intersection_area(BBox(ln.box[0], ln.box[1], ln.box[0] + ln.box[2],
                                                             ln.box[1] + ln.box[3])), default=None)
        if owner is None:
            continue
        owner.reading.words.append(Word(text=_value(bodies[0]), box=box))
        lang = language_tag(bodies[0].get("language"))
        if lang and lang != languages.get(owner.id):
            languages[f"{owner.id}/{len(owner.reading.words) - 1}"] = lang
    for item in rest:
        motivation = _first(item.get("motivation"))
        bodies = _text_bodies(item.get("body"))
        if not bodies:
            continue
        target = _first(item.get("target"))
        if motivation == "editing":
            ln = lines.get(target if isinstance(target, str) else (target or {}).get("id"))
            kind = bodies[0].get("purpose")
            if ln is not None and kind in EDITS:
                t.edits.append(Edit(annotator=annotator(item), target=ln.id, kind=kind, text=_value(bodies[0])))
        elif motivation == "describing":
            _src, box, _polygon = _target_shape(target, size)
            match = [rid for rid, rb in regions if box is not None and rb == BBox(box[0], box[1], box[0] + box[2],
                                                                                    box[1] + box[3])]
            if match:
                t.descriptions.append(Description(annotator=annotator(item), target=match[0],
                                                  kind=bodies[0].get("purpose") or "description",
                                                  text=_value(bodies[0])))
    lines_by_id = {ln.id: ln for ln in t.lines}
    if languages:                       # by the annotator of the line that states it
        line_languages = {v for k, v in languages.items() if "/" not in k}
        if len(line_languages) == 1 and len([k for k in languages if "/" not in k]) == len(t.lines):
            page_language = line_languages.pop()
            t.classify(t.lines[0].annotator, "", "language", page_language)
            languages = {k: v for k, v in languages.items() if "/" in k and v != page_language}
        for target, lang in languages.items():
            t.classify(lines_by_id[target.split("/")[0]].annotator, target, "language", lang)
    if t.lines or regions:
        t.add_order(t.lines[0].annotator if t.lines else t.region(regions[0][0]).annotator,
                    [rid for rid, _b in regions], [ln.id for ln in t.lines])
    return t
