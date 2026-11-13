"""An annotation set as an IIIF Presentation 3 annotation page (W3C Web Annotations on the page's canvas).

``to_annotation_page(t, canvas, id)`` writes one annotation per region (motivation ``classifying``, its content
role as the body), per line with a reading (``supplementing``, IIIF's motivation for a transcription, with the
text granularity extension's ``textGranularity`` ``line``), per word (``word``), per description (``describing``)
and per edit (``editing``, targeting the line's annotation). Targets are the canvas with a media fragment
(``#xywh=``) where the annotation has a box, the canvas itself where it has none. Each annotation's ``generator``
(``creator`` for people) is its annotator's name.
"""
from __future__ import annotations

from typing import Any

from ..data.policy import DEFAULT_POLICY, RenderingPolicy
from ..data.refs import parse
from ..data.transcription import AnnotationSet, Transcription

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
    language = t.classification("", "language")
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
        for ln in t.ordered_lines():
            if ln.reading is None or t.region_of(ln) in hidden:
                continue
            line_ids[ln.id] = add("supplementing", _body(t.text_of(ln), language=language),
                                  _target(canvas, ln.box or (t.region(t.region_of(ln)).box
                                                             if t.region_of(ln) and t.region(t.region_of(ln))
                                                             else None)),
                                  ln.reading.annotator, textGranularity="line")
            for w in ln.reading.words:
                add("supplementing", _body(w.text, language=language), _target(canvas, w.box),
                    ln.reading.annotator, textGranularity="word")
        for e in t.edits:
            ref = parse(e.target)
            target = line_ids.get(ref.id)
            if target is not None and ref.page is None:
                add("editing", _body(e.text, e.kind), target, e.annotator)
    for d in t.descriptions:
        r = t.region(d.target)
        if r is not None and r.id not in hidden:
            add("describing", _body(d.text, d.kind), _target(canvas, r.box), d.annotator)
    return {"@context": CONTEXT, "id": id, "type": "AnnotationPage", "items": items}
