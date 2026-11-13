"""Conformance checks for engines (``check_engine``) and blocks (``check_block``): what every engine and every
block must do, whoever wrote it. Each check collects every problem it finds and raises one ``AssertionError``
listing them, so a test is one call."""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterable
from typing import Any

from .samples import sample_documents, sample_layout, sample_page, sample_png

#: a code id: two or three dotted names and a version (``kraken.recognition.v1``, ``recomposition.unicode.v1``)
ENGINE_ID = re.compile(r"[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*){1,2}\.v[0-9]+")
#: a part any declared part of the transcription accounts for (``source``, ``language``, ``extra``)
ANY = frozenset({"*"})
#: what varies from run to run in a step's record
VARYING = ("seconds", "datetime")


# ------------------------------------------------------------------------------------- what changed, by part

def _changes(where: str, before, after, parts: Iterable[str], out: list) -> None:
    if before != after:
        out.append((where, frozenset(parts)))


def _by_id(items: list[dict]) -> dict[str, dict]:
    return {x.get("id"): x for x in items}


def _full(t: dict | None) -> dict:
    """A transcription dump with every field (a stored record leaves defaults out)."""
    from ..data import Transcription

    return Transcription.model_validate(t or {}).model_dump(mode="json", by_alias=True)


#: the fields every annotation has, besides its own
_ANNOTATION = ("annotator", "output", "derived_from", "confidence")


def _extensions(x: dict, known: Iterable[str]) -> dict:
    return {k: v for k, v in x.items() if k not in known and k not in _ANNOTATION}


#: line field -> the parts that may change it
LINE_FIELDS = {
    "region": ("lines", "line_regions", "hierarchy"), "box": ("lines",), "polygon": ("lines",),
    "confidence": ("lines",), "baseline": ("lines", "baselines"), "parent": ("lines", "hierarchy"),
}
#: a line's reading field -> the parts that may change it (words: ``_word_changes``)
READING_FIELDS = {"text": ("text", "nfc"), "alternatives": ("text", "nfc"), "confidence": ("line_confidences", "text"),
                  "formatting": ("text", "words")}
#: region field -> the parts that may change it
REGION_FIELDS = {"label": ("regions",), "box": ("regions", "hierarchy"), "polygon": ("regions", "hierarchy"),
                 "confidence": ("regions",), "parent": ("regions", "hierarchy")}
#: a classification's scheme -> the parts that may add it (other schemes: any part, ``ANY``)
SCHEME_PARTS = {"role": ("regions", "hierarchy"), "heading_level": ("hierarchy", "regions"),
                "status": ("regions", "hierarchy"), "production": ("regions", "text")}
#: an edit's kind -> the parts that may add it
EDIT_PARTS = {"nfc": ("nfc", "text"), "normalized": ("normalized",),
              "joined": ("text", "lines", "regions", "hierarchy", "paragraphs"), "corrected": ("text",),
              "expanded": ("text", "normalized"), "regularized": ("text", "normalized")}
#: a link's kind -> the parts that may add it
LINK_PARTS = {"part_of": ("lines", "line_regions", "hierarchy"), "runs_into": ("paragraphs",),
              "continues": ("paragraphs",), "caption_of": ("hierarchy", "regions"),
              "note_of": ("hierarchy", "regions"), "refers_to": ("hierarchy", "regions")}
#: what descriptions (text about a region that is not on the page) need
DESCRIPTION_PARTS = ("regions", "hierarchy", "tables", "formulas", "text", "markdown")


def _word_changes(where: str, before: list[dict], after: list[dict], out: list) -> None:
    def strip(words, *keys):
        return [{k: v for k, v in w.items() if k not in keys} for w in words]

    _changes(f"{where}.words", strip(before, "confidence", "hyphen"), strip(after, "confidence", "hyphen"),
             ("words", "text", "nfc"), out)
    _changes(f"{where}.words.confidence", [w.get("confidence") for w in before], [w.get("confidence") for w in after],
             ("word_confidences", "words"), out)
    _changes(f"{where}.words.hyphen", [w.get("hyphen") for w in before], [w.get("hyphen") for w in after],
             ("words", "paragraphs", "text"), out)


def _multiset_changes(where: str, before: list[dict], after: list[dict], parts_of, out: list) -> None:
    """Annotations without ids, added or gone: each with the parts ``parts_of(annotation)`` names."""
    rest = [json.dumps(x, sort_keys=True) for x in before]
    for x in after:
        key = json.dumps(x, sort_keys=True)
        if key in rest:
            rest.remove(key)
        else:
            out.append((f"{where}.{x.get('scheme') or x.get('kind') or 'added'}", frozenset(parts_of(x))))
    for key in rest:
        x = json.loads(key)
        out.append((f"{where}.{x.get('scheme') or x.get('kind') or 'removed'}", frozenset(parts_of(x))))


def _resolved_order(t: dict, of: str):
    found = [o for o in t["orders"] if o.get(of)]
    if not found:
        return None
    o = found[-1]
    return o[of] if of == "regions" else list(zip(o["lines"], o["rows"]))


def transcription_changes(before: dict | None, after: dict | None) -> list[tuple[str, frozenset[str]]]:
    """Returns what differs between two transcriptions (their JSON dumps, a stored record's or a full one), each
    difference with the parts that may account for it.

    Regions, lines and ranges are compared by id: a region or line added or gone is ``regions`` or ``lines``, and of
    the ones in both their fields (a line's ``region``: ``line_regions``, its reading's ``text``: ``text``, a word's
    ``confidence``: ``word_confidences``, ...). The other annotations are compared as they are, added or gone, each
    by what it is: a classification by its scheme (``role``: ``regions`` or ``hierarchy``), an edit by its kind
    (``nfc``, ``normalized``), a link by its kind (``part_of``: ``line_regions``, ``runs_into``: ``paragraphs``),
    tables as ``tables``, formulas as ``formulas``, paragraphs as ``paragraphs``; the reading order as it resolves
    (the regions' ``reading_order``, the lines' ``lines``). The annotators are left out (checked on their own); the
    source, the raw outputs, the set's extension fields and the other schemes are accounted for by any part of the
    transcription (``ANY``).

    Args:
        before, after: the two transcriptions as JSON-compatible dicts; ``None``: none (an empty transcription).
    """
    b, a, out = _full(before), _full(after), []
    rb, ra = _by_id(b["regions"]), _by_id(a["regions"])
    _changes("regions", sorted(rb, key=str), sorted(ra, key=str), ("regions",), out)
    for rid in rb.keys() & ra.keys():
        for f, parts in REGION_FIELDS.items():
            _changes(f"regions.{f}", rb[rid].get(f), ra[rid].get(f), parts, out)
        _changes("regions.extensions", _extensions(rb[rid], REGION_FIELDS | {"id": 0}),
                 _extensions(ra[rid], REGION_FIELDS | {"id": 0}), ("regions", "hierarchy", "tables", "formulas"), out)
    if any(names == frozenset({"regions"}) for where, names in out if where == "regions"):
        out = [(w, n) for w, n in out if not w.startswith("regions.")]   # regions made anew: their fields with them
    _changes("orders.regions", _resolved_order(b, "regions"), _resolved_order(a, "regions"),
             ("reading_order", "regions", "line_regions"), out)
    lb, la = _by_id(b["lines"]), _by_id(a["lines"])
    _changes("lines", sorted(lb, key=str), sorted(la, key=str), ("lines",), out)
    _changes("orders.lines", _resolved_order(b, "lines"), _resolved_order(a, "lines"),
             ("lines", "line_regions", "hierarchy"), out)
    lines_from = len(out)
    empty = {"text": None, "alternatives": [], "confidence": None, "formatting": [], "words": []}
    for lid in lb.keys() & la.keys():
        for f, parts in LINE_FIELDS.items():
            _changes(f"lines.{f}", lb[lid].get(f), la[lid].get(f), parts, out)
        _changes("lines.extensions", _extensions(lb[lid], LINE_FIELDS | {"id": 0, "reading": 0}),
                 _extensions(la[lid], LINE_FIELDS | {"id": 0, "reading": 0}), ("lines", "text"), out)
        rdb, rda = lb[lid].get("reading") or empty, la[lid].get("reading") or empty
        for f, parts in READING_FIELDS.items():
            _changes(f"lines.reading.{f}", rdb.get(f), rda.get(f), parts, out)
        _word_changes("lines.reading", rdb.get("words") or [], rda.get("words") or [], out)
    # the lines' geometry made anew (a line step): what they carried goes with them
    if any(w in ("lines.box", "lines.polygon") for w, _ in out[lines_from:]):
        out = out[:lines_from] + [(w, n | {"lines"}) for w, n in out[lines_from:]]
    gb, ga = _by_id(b["ranges"]), _by_id(a["ranges"])
    for rid in gb.keys() | ga.keys():
        x = ga.get(rid) or gb.get(rid)
        _changes(f"ranges.{x.get('kind')}", gb.get(rid), ga.get(rid),
                 ("paragraphs",) if x.get("kind") == "paragraph" else ("hierarchy", "paragraphs"), out)
    _multiset_changes("classifications", b["classifications"], a["classifications"],
                      lambda c: ANY if c["target"] == "" else SCHEME_PARTS.get(c["scheme"], ANY), out)
    _multiset_changes("edits", b["edits"], a["edits"], lambda e: EDIT_PARTS.get(e["kind"], ("text",)), out)
    _multiset_changes("links", b["links"], a["links"], lambda ln: LINK_PARTS.get(ln["kind"], ("hierarchy",)), out)
    _multiset_changes("tables", b["tables"], a["tables"], lambda _: ("tables", "html"), out)
    _multiset_changes("formulas", b["formulas"], a["formulas"], lambda _: ("formulas", "latex"), out)
    _multiset_changes("descriptions", b["descriptions"], a["descriptions"], lambda _: DESCRIPTION_PARTS, out)
    known = {"source", "annotators", "outputs", "regions", "ranges", "classifications",
                                        "descriptions", "links", "orders", "lines", "tables", "formulas", "edits"}
    _changes("source", b.get("source"), a.get("source"), ANY, out)
    _changes("outputs", b.get("outputs"), a.get("outputs"), ANY, out)
    _changes("extensions", {k: v for k, v in b.items() if k not in known},
             {k: v for k, v in a.items() if k not in known}, ANY, out)
    return out


def _covered(names: frozenset[str], declared: set[str]) -> bool:
    return names == ANY and bool(declared) or bool(names & declared) or "*" in declared


# ------------------------------------------------------------------------------------- nothing overwritten

#: the lists of a transcription whose annotations have ids
_ZONES = ("regions", "lines", "ranges")
#: the lists of annotations without ids: appended to, never changed
_APPENDED = ("outputs", "classifications", "descriptions", "links", "orders", "tables", "formulas", "edits")


def _kept(before, after) -> bool:
    """Whether ``after`` keeps ``before``: equal, or a dict whose fields that were ``None`` (and only those) are
    set, the others kept the same way."""
    if before is None:
        return True
    if isinstance(before, dict) and isinstance(after, dict):
        return before.keys() <= after.keys() and all(_kept(v, after[k]) for k, v in before.items())
    return before == after


def _without_measurements(annotators: list[dict]) -> list[dict]:
    return [{k: v for k, v in a.items() if k != "measurements"} for a in annotators]


def made_anew(before: dict | None, after: dict | None) -> bool:
    """Whether ``after`` is another annotation set than ``before`` (its annotators do not begin with
    ``before``'s): a transcription made anew, as a page engine returns one, rather than added to."""
    b, a = _full(before), _full(after)
    ab, aa = _without_measurements(b["annotators"]), _without_measurements(a["annotators"])
    return len(aa) < len(ab) or not all(_kept(x, y) for x, y in zip(ab, aa))


#: the parts a contract's ``replaces`` may name for a change to the annotations of a list that were there (``ANY``:
#: any part of the transcription; annotators: none, they are only appended)
OVERWRITE_PARTS = {
    "annotators": frozenset(), "outputs": ANY, "source": ANY,
    "classifications": frozenset({"regions", "hierarchy", "text"}),
    "descriptions": frozenset(DESCRIPTION_PARTS),
    "links": frozenset({"lines", "line_regions", "hierarchy", "paragraphs", "regions"}),
    "orders": frozenset({"reading_order", "regions", "lines", "line_regions", "hierarchy"}),
    "tables": frozenset({"tables", "html"}), "formulas": frozenset({"formulas", "latex"}),
    "edits": frozenset({"nfc", "normalized", "text", "paragraphs", "lines"}),
    "regions": frozenset({"regions"}), "lines": frozenset({"lines"}), "ranges": frozenset({"paragraphs", "hierarchy"}),
}


def overwrites(before: dict | None, after: dict | None) -> list[tuple[str, frozenset[str]]]:
    """What ``after`` changed of what ``before`` held (``overwritten``), each with the parts whose replacement
    accounts for it (``OVERWRITE_PARTS``; a line whose reading changed also ``text``)."""
    b, a, problems = _full(before), _full(after), []
    ab, aa = _without_measurements(b["annotators"]), _without_measurements(a["annotators"])
    if len(aa) < len(ab) or not all(_kept(x, y) for x, y in zip(ab, aa)):
        problems.append(("changed or removed an annotator that was there (annotators are only appended)",
                         OVERWRITE_PARTS["annotators"]))
    for key in _APPENDED:
        if a[key][:len(b[key])] != b[key]:
            problems.append((f"changed or removed {key} that were there (they are only appended)",
                             OVERWRITE_PARTS[key]))
    for key in _ZONES:
        after_by = _by_id(a[key])
        for x in b[key]:
            y = after_by.get(x["id"])
            if y is None:
                problems.append((f"removed {key} {x['id']!r}", OVERWRITE_PARTS[key] | ({"text"} if key == "lines"
                                                                                       else set())))
            elif not _kept(x, y):
                fields = sorted(k for k in x if not _kept(x[k], y.get(k)))
                parts = OVERWRITE_PARTS[key] | ({"text"} if key == "lines" and "reading" in fields else set())
                problems.append((f"changed {key} {x['id']!r} ({', '.join(fields)})", parts))
    if not _kept(b["source"], a["source"]):
        problems.append(("changed the source", OVERWRITE_PARTS["source"]))
    return problems


def overwritten(before: dict | None, after: dict | None) -> list[str]:
    """Returns what ``after`` changed of what ``before`` held: every annotation must still be there as it was.

    Annotators are only appended (an earlier one may get a field that was ``None``, e.g. its run or preset, and
    its measurements are left out); raw outputs and the annotations without ids (classifications, descriptions,
    links, orders, tables, formulas, edits) only appended; regions, lines and ranges matched by id, each kept with
    its fields, of which those that were ``None`` may be set (a line's ``region`` and ``reading`` once). The source
    may gain fields (its image size, ...).

    Args:
        before, after: the two transcriptions as JSON-compatible dicts.
    """
    return [p for p, _ in overwrites(before, after)]


def _annotators(t: dict) -> list[dict]:
    return t.get("annotators") or []


def _named(t: dict, b: dict, index: int) -> list[str]:
    """The annotations ``t`` added to ``b`` that do not name the annotator ``index``."""
    full, fb, bad = _full(t), _full(b), []
    for key in (*_APPENDED, "regions", "ranges"):
        for x in full[key][len(fb[key]):] if key in _APPENDED else [x for x in full[key] if x["id"] not in
                                                                     _by_id(fb[key])]:
            if x.get("annotator") != index:
                bad.append(f"{key} {x.get('id') or x.get('scheme') or x.get('kind') or ''}".rstrip())
    known = _by_id(fb["lines"])
    for ln in full["lines"]:
        old = known.get(ln["id"])
        if old is None and ln.get("annotator") != index:
            bad.append(f"lines {ln['id']}")
        if ln.get("reading") is not None and (old is None or old.get("reading") is None) \
                and ln["reading"].get("annotator") != index:
            bad.append(f"the reading of {ln['id']}")
    return bad


def _without_varying(value: Any) -> Any:
    """``value`` (a dump) without the measurements that vary from run to run."""
    value = copy.deepcopy(value)

    def strip(t):
        for s in t.get("annotators") or []:
            for k in VARYING:
                (s.get("measurements") or {}).pop(k, None)

    for t in value if isinstance(value, list) else [value]:
        if isinstance(t, dict):
            strip(t)
    return value


# ------------------------------------------------------------------------------------------------ engines

def _rendered(out) -> str:
    """A rendering's result (a document and its map, ...) as canonical JSON, to compare two calls."""
    def plain(x):
        if hasattr(x, "model_dump"):
            return x.model_dump(mode="json")
        if isinstance(x, (list, tuple)):
            return [plain(v) for v in x]
        if isinstance(x, dict):
            return {str(k): plain(v) for k, v in x.items()}
        return x

    return json.dumps(plain(out), sort_keys=True, default=str)


def _step_input(step: str, unit: str | None):
    """The transcription an engine or block of ``step`` and ``unit`` gets by default: what the steps before it
    made of a sample page (``sample_layout``)."""
    from ..data import Annotator, Source, Transcription
    from .samples import box

    t = sample_layout(text=step not in ("recognition",))
    if step == "layout" or (step == "recognition" and unit == "page"):    # a page engine reads the page itself
        return Transcription(source=Source(**t.source.model_dump()))
    if step == "lines":
        out = Transcription(source=Source(**t.source.model_dump()))
        a = out.add_annotator(Annotator(step="layout", name="sample"))
        r = t.regions[0]
        out.add_region(a, r.id, r.box, r.polygon, label=r.label, role=t.role(r.id), confidence=r.confidence)
        out.add_order(a, [r.id])
        return out
    if step in ("tables", "formulas"):
        label = "table" if step == "tables" else "formula"
        t.add_region(0, f"{label}_1", [80, 40, 640, 60], box(80, 40, 640, 60), label=label, role=label)
        o = t.orders[-1]
        t.orders[-1] = o.model_copy(update={"regions": [*o.regions, f"{label}_1"]})
    return t


def _engine_input(cls, transcription):
    """The transcription an engine of ``cls``'s step and unit gets by default (``_step_input``)."""
    if transcription is not None:
        return transcription
    return _step_input(cls.step, (cls.capabilities or {}).get("unit"))


def check_engine(engine_cls, *, options: dict | None = None, image=None, transcription=None):
    """Checks that an engine class follows the engine protocol, and returns what its first call returned.

    The checks: ``engine_id`` is a code id (``<provider>.<step>[.<variant>].v<n>`` or ``<step>.<variant>.v<n>``)
    that names the engine's ``step``, one of the catalog's steps; ``capabilities`` (unit, produces) validate
    against the vocabulary and produce something; ``Options`` is a pydantic model whose fields all have a
    description, and the engine constructs with ``options``. Then it is loaded and called on the input, twice:

    * a model engine (the steps that are not rule-based) as ``engine(image, transcription)`` (the image as an RGB
      array, or as a PNG file's bytes for an engine whose ``image_input`` is ``"bytes"``): it returns a
      ``Transcription`` in which only the parts its ``capabilities.produces`` declares changed
      (``transcription_changes``), and leaves the image array as it was;
    * a rule-based engine by its unit: ``engine(transcription)`` (page), ``engine([t1, t2])`` (item, the
      transcriptions of two pages), ``engine(image_bytes) -> (bytes, info)`` (the image step);

    a composition (a rendering) returns what it renders and changes nothing in the transcription it reads; every
    other call gives each transcription exactly one more ``Annotator``, of kind ``rule`` for a rule-based step
    (``model`` or ``rule`` for a model step: one without a model is a rule), naming the engine's step, the engine id (or no engine: the block fills it in) and only measurements of the vocabulary
    (``linecaster.data.MEASUREMENTS``); every annotation the call added names it, and nothing that was there changed
    (``overwritten``: annotations only appended, a field that was ``None`` set at most). The second call returns the
    same as the first, apart from the measurements that vary from run to run (``seconds``, ``datetime``). An engine with
    weights loads them in ``load()``: a test that checks it needs them (mark it ``network``).

    Args:
        engine_cls: the engine class.
        options: keyword arguments that construct it (a preset's options and ``weights``); ``None``: none.
        image: the page image, an RGB array (the image step and an engine whose ``image_input`` is ``"bytes"``: an
            image file's bytes); default ``sample_page()`` (``sample_png()``).
        transcription: the transcription it is called with; default a sample layout fit for its step and unit
            (``sample_layout``: recognition gets lines without readings, layout an empty transcription, lines a
            region, tables and formulas a region of their label besides a recognized one, a page engine
            (recognition, unit page) an empty transcription, rule-based engines a recognized page).

    Example:
        from linecaster.testing import check_engine
        from linecaster_tesseract import TesseractRecognitionEngine

        out = check_engine(TesseractRecognitionEngine, options={"lang": "eng"})
        assert all(line.reading.text for line in out.lines)
    """
    import numpy as np
    from pydantic import BaseModel

    from ..catalog.schema import RULE_STEPS, STEPS, Capabilities
    from ..data import Transcription
    from ..data.measurements import unknown_measurements

    problems: list[str] = []
    name = getattr(engine_cls, "__name__", repr(engine_cls))
    eid, step = getattr(engine_cls, "engine_id", None), getattr(engine_cls, "step", None)
    if not isinstance(eid, str) or not ENGINE_ID.fullmatch(eid):
        problems.append(f"engine_id {eid!r} is not a code id <provider>.<step>[.<variant>].v<n>")
    if step not in STEPS:
        problems.append(f"step {step!r} is not a catalog step ({', '.join(STEPS)})")
    elif isinstance(eid, str) and step not in eid.split(".")[:-1]:
        problems.append(f"engine_id {eid!r} does not name its step {step!r}")
    caps = None
    try:
        caps = Capabilities.model_validate(getattr(engine_cls, "capabilities", None) or {})
        if caps.unit is None or not caps.produces:
            problems.append(f"capabilities {engine_cls.capabilities!r} name no unit or produce nothing")
    except Exception as e:  # noqa: BLE001 - reported
        problems.append(f"capabilities: {e}")
    opts = getattr(engine_cls, "Options", None)
    if not (isinstance(opts, type) and issubclass(opts, BaseModel)):
        problems.append("Options is not a pydantic model")
    else:
        undocumented = [f for f, info in opts.model_fields.items() if not info.description]
        if undocumented:
            problems.append(f"Options fields without a description: {', '.join(undocumented)}")
    if problems:
        raise AssertionError(f"{name}:\n" + "\n".join(f"- {p}" for p in problems))

    engine = engine_cls(**(options or {}))
    engine.load()
    produces = set(caps.produces)
    rule = step in RULE_STEPS
    first = None
    for attempt in range(2):
        if rule and step == "image":
            data = image if image is not None else sample_png()
            out = engine(data)
            if not (isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], (bytes, bytearray))
                    and isinstance(out[1], dict)):
                problems.append(f"the image step returns (bytes, info), not {type(out).__name__}")
                break
            result, dump = out, (out[0], json.dumps(out[1], sort_keys=True, default=str))
        elif step == "composition":         # a rendering: it returns the document and adds nothing
            t = _engine_input(engine_cls, copy.deepcopy(transcription))
            kept = t.model_dump(mode="json", by_alias=True)
            out = engine(t)
            if t.model_dump(mode="json", by_alias=True) != kept:
                problems.append("a composition changed the transcription it renders (it adds nothing)")
            result, dump = out, _rendered(out)
        else:
            t = _engine_input(engine_cls, copy.deepcopy(transcription))
            inputs = [t, copy.deepcopy(t)] if rule and caps.unit == "item" else [t]
            before = [x.model_dump(mode="json", by_alias=True) for x in inputs]
            if rule:
                out = engine(inputs) if caps.unit == "item" else engine(t)
                outs = out if caps.unit == "item" else [out]
            elif getattr(engine_cls, "image_input", "rgb") == "bytes":       # the image file, as a reader brings it
                out = engine(image if image is not None else sample_png(), t)
                outs = [out]
            else:
                array = np.array(image if image is not None else sample_page())      # a writable copy
                kept = array.copy()
                out = engine(array, t)
                outs = [out]
                if not np.array_equal(array, kept):
                    problems.append("the call changed the image array it was given")
            if not isinstance(outs, list) or len(outs) != len(inputs) or not all(
                    isinstance(o, Transcription) for o in outs):
                problems.append(f"the call returns {type(out).__name__}, not "
                                f"{'a list of Transcriptions' if caps.unit == 'item' else 'a Transcription'}")
                break
            dump = [o.model_dump(mode="json", by_alias=True) for o in outs]
            if attempt == 0:
                for b, a in zip(before, dump):
                    for where, parts in transcription_changes(b, a):
                        if not _covered(parts, produces):
                            problems.append(f"changed {where}, which needs one of {sorted(parts)}; capabilities "
                                            f"produce {sorted(produces)}")
                    problems.extend(overwritten(b, a))
                    new = _annotators(a)[len(_annotators(b)):]
                    if len(new) != 1:
                        problems.append(f"{len(new)} annotators appended, not one")
                    for s in new:
                        if s.get("step") != step:
                            problems.append(f"Annotator step {s.get('step')!r}, not {step!r}")
                        kinds = ("rule",) if rule else ("model", "rule")        # a model step without a model: a rule
                        if s.get("kind") not in kinds:
                            problems.append(f"Annotator kind {s.get('kind')!r}, not {' or '.join(map(repr, kinds))}")
                        if s.get("engine") not in (None, eid):
                            problems.append(f"Annotator engine {s.get('engine')!r}, not {eid!r}")
                        if bad := unknown_measurements(s.get("measurements") or {}):
                            problems.append(f"Annotator measurements outside the vocabulary: {bad}")
                    if len(new) == 1 and (bad := _named(a, b, len(_annotators(a)) - 1)):
                        problems.append(f"annotations that do not name the call's annotator: {', '.join(bad)}")
            result = out
            dump = _without_varying(dump)
        if attempt == 0:
            first, first_dump = result, dump
        elif dump != first_dump:
            problems.append("a second call on the same input returned something else (not deterministic)")
    if problems:
        raise AssertionError(f"{name} ({eid}):\n" + "\n".join(f"- {p}" for p in dict.fromkeys(problems)))
    return first


# ------------------------------------------------------------------------------------------------- blocks

def _media(doc, kind):
    return next((m.media_bytes for m in doc.media if m.type == kind and m.media_bytes is not None), None)


def page_changes(before, after) -> list[tuple[str, frozenset]]:
    """Returns what differs between a page's datatrove document before and after a block, each difference with the
    parts (``Part``) that may account for it, or ``("removed", part)`` for a part that is gone.

    Page-level: ``image`` (the image media's bytes), ``transcription_file`` (a document media's bytes),
    ``metadata`` (the page record apart from its transcriptions); each transcription by
    ``transcription_changes``, its parts in that transcription. The page's ``errors`` and ``trace`` are not parts, nor
    its ``measurements`` (the run's time for the page, ``PageTiming``).

    Args:
        before, after: the page's document before and after.
    """
    from datatrove.data import MediaType

    from ..blocks.base.contract import Part
    from ..data.page import PAGE_KEY

    out: list[tuple[str, frozenset]] = []
    for part, kind in (("image", MediaType.IMAGE), ("transcription_file", MediaType.DOCUMENT)):
        b, a = _media(before, kind), _media(after, kind)
        if b is not None and a is None:
            out.append(("removed", frozenset({Part(part)})))
        elif a != b:
            out.append((part, frozenset({Part(part)})))
    pb, pa = before.metadata.get(PAGE_KEY) or {}, after.metadata.get(PAGE_KEY) or {}
    rest = tuple({k: v for k, v in p.items() if k not in ("transcriptions", "measurements")} for p in (pb, pa))
    if rest[0] != rest[1]:
        out.append(("metadata", frozenset({Part("metadata")})))
    tb, ta = pb.get("transcriptions") or {}, pa.get("transcriptions") or {}
    for name in sorted(tb.keys() | ta.keys()):
        for where, names in transcription_changes(tb.get(name), ta.get(name)):
            out.append((f"{name}:{where}", frozenset(Part("*", name) if n == "*" else Part(n, name) for n in names)))
        if name in tb and name not in ta:
            out.append(("removed", frozenset({Part("*", name)})))
    return out


def _overwritten_on_page(before, after, contract) -> list[str]:
    """What a block changed of the transcriptions a page carried (``overwrites``, per transcription) that its
    contract does not replace: a change to the annotations of a part it replaces is the replacement (``*``: every
    part); a transcription it made anew (``made_anew``, as a page engine's) only where it replaces a part of it."""
    from ..data.page import PAGE_KEY

    tb = (before.metadata.get(PAGE_KEY) or {}).get("transcriptions") or {}
    ta = (after.metadata.get(PAGE_KEY) or {}).get("transcriptions") or {}
    out = []
    for name in sorted(tb.keys() & ta.keys()):
        replaced = {p.name for p in contract.replaces
                    if p.transcription == name or (p.name == "*" and p.transcription is None)}
        if made_anew(tb[name], ta[name]):
            if not replaced:
                out.append(f"made {name} anew, and the contract replaces nothing of it")
            continue
        for problem, parts in overwrites(tb[name], ta[name]):
            if "*" in replaced or (parts == ANY and replaced) or (parts & replaced):
                continue
            out.append(f"{name}: {problem}")
    return out


def _part_covers(declared, changed) -> bool:
    """Whether a declared part accounts for a changed one: ``*`` (of the page, or of the transcription) covers
    every part of it, and a change any part of a transcription accounts for (``ANY``) is covered by any of them."""
    if declared.covers(changed) or (declared.name == "*" and declared.transcription is None):
        return True
    return changed.name == "*" and changed.transcription is not None and declared.transcription == changed.transcription


def _sample_docs(unit: str, block=None) -> list:
    """Two sample pages of one item with a recognized layout, or (unit ``item``) their item record; for a layout or
    line model block, the pages as its step finds them (no layout; a layout without lines: ``_step_input``)."""
    docs = sample_documents(2)
    step = getattr(block, "step", None)
    if unit == "page" and step in ("layout", "lines") and hasattr(block, "backend"):
        from ..blocks.base.page import page_of, set_page

        for d in docs:
            page = page_of(d)
            page.transcriptions[getattr(block, "transcription", None) or "ocr_new"] = _step_input(step, "page")
            set_page(d, page)
    if unit != "item":
        return docs
    from ..blocks.binding import Binder

    return list(Binder().run(iter(docs)))


def check_block(block, docs=None, *, run: bool = True) -> list:
    """Checks that a block follows the block conventions, and returns what it passed on for ``docs``.

    The checks: ``contract()`` returns a ``Contract``; ``to_dict()`` is JSON-serializable and stable (the same
    twice, and the same for a copy pickled with dill before ``warm_up()``, as datatrove's executors pickle
    pipelines); ``warm_up()`` is idempotent (a second call keeps the loaded engine). With ``run``: the block runs on
    ``docs`` in this process (``run_pages``), and on each page only parts its contract adds or replaces changed and
    only parts it removes are gone (``page_changes``), and nothing a transcription held was changed (``overwritten``)
    but the annotations of the parts its contract replaces (a transcription made anew only where the contract
    replaces a part of it), not for a block that changes the unit (a binder or a splitter); a model block passes a page that carries an earlier error through unchanged; a page block that reads
    the image records a page without image bytes as that page's error and passes it on.

    Args:
        block: the block, built as a pipeline would build it.
        docs: the datatrove documents it runs on; ``None``: two sample pages of one item with a recognized layout
            (``sample_documents``; a layout or line model block gets them as its step finds them), as an item record
            for an item-unit block; a reader reads its own input after them.
        run: run the block; ``False`` (a server block) checks only what needs no run.

    Example:
        from linecaster.backends import InProcess
        from linecaster.blocks.lines import LineDetector
        from linecaster.testing import check_block, register_fakes

        register_fakes()
        out = check_block(LineDetector(InProcess("linecaster.testing:FakeLineEngine")))
    """
    import dill
    from datatrove.data import Document

    from ..blocks.base.contract import Contract, Part
    from ..blocks.base.page import ERRORS_KEY, PageBlock
    from ..runtime.builder import run_pages

    problems: list[str] = []
    label = f"{type(block).__name__}"
    contract = block.contract() if callable(getattr(block, "contract", None)) else None
    if not isinstance(contract, Contract):
        raise AssertionError(f"{label}: contract() returns {type(contract).__name__}, not a Contract")
    try:
        first = json.dumps(block.to_dict(), sort_keys=True)
    except (TypeError, ValueError) as e:
        raise AssertionError(f"{label}: to_dict() is not JSON-serializable: {e}") from e
    if json.dumps(block.to_dict(), sort_keys=True) != first:
        problems.append("to_dict() differs from one call to the next")
    try:
        clone = dill.loads(dill.dumps(block))
        if json.dumps(clone.to_dict(), sort_keys=True) != first:
            problems.append("to_dict() of the block pickled with dill differs from the block's")
    except Exception as e:  # noqa: BLE001 - reported
        problems.append(f"does not pickle with dill before warm_up(): {type(e).__name__}: {e}")
    out: list = []
    if run:
        block.warm_up()
        backend = getattr(block, "backend", None)
        loaded = getattr(backend, "_model", None)
        block.warm_up()
        if loaded is not None and getattr(backend, "_model", None) is not loaded:
            problems.append("a second warm_up() loaded the engine again")
        docs = list(docs) if docs is not None else (_sample_docs(contract.unit, block) if contract.role != "reader"
                                             else [])
        before = {d.id: copy.deepcopy(d) for d in docs}
        out = run_pages([block], docs)
        declared = contract.adds | contract.replaces
        removed = contract.removes
        if not contract.unit_out:
            for d in out:
                b = before.get(d.id)
                if b is None:           # a reader's own page: everything it carries must be declared
                    b = Document(text="", id=d.id, media=[], metadata={"page": {"transcriptions": {}}})
                for where, parts in page_changes(b, d):
                    ok = removed if where == "removed" else declared
                    if not any(_part_covers(p, q) for p in ok for q in parts):
                        what = "removed" if where == "removed" else f"changed {where}, which needs one of"
                        problems.append(f"page {d.id}: {what} {sorted(map(str, parts))}; the contract "
                                        f"{'removes' if where == 'removed' else 'adds or replaces'} "
                                        f"{sorted(map(str, ok)) or 'nothing'}")
                problems.extend(f"page {d.id}: {p}" for p in _overwritten_on_page(b, d, contract))
        if contract.role == "model" and contract.unit == "page" and docs:
            failed = copy.deepcopy(docs[0])
            failed.id = f"{failed.id}-failed"
            failed.metadata[ERRORS_KEY] = [{"block": "Earlier", "type": "error", "error": "failed before"}]
            kept = copy.deepcopy(failed)
            passed = list(block.run(iter([failed]), 0, 1))
            if len(passed) != 1 or passed[0].metadata != kept.metadata:
                problems.append("a page that carries an earlier error did not pass through unchanged")
        if (isinstance(block, PageBlock) and Part("image") in contract.reads and contract.unit == "page"
                and contract.role in ("model", "transform", "validator") and docs):
            bare = copy.deepcopy(docs[0])
            bare.id, bare.media = f"{bare.id}-no-image", []
            bare.metadata.pop(ERRORS_KEY, None)
            passed = list(block.run(iter([bare]), 0, 1))
            if len(passed) != 1 or not passed[0].metadata.get(ERRORS_KEY):
                problems.append("a page without image bytes was not passed on with its error")
            elif passed[0].metadata[ERRORS_KEY][-1].get("block") != type(block).__name__:
                problems.append(f"the error of a page without image bytes names "
                                f"{passed[0].metadata[ERRORS_KEY][-1].get('block')!r}, not {label!r}")
    if problems:
        raise AssertionError(f"{label}:\n" + "\n".join(f"- {p}" for p in dict.fromkeys(problems)))
    return out

