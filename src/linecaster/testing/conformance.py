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


def _word_changes(where: str, before: list[dict], after: list[dict], out: list) -> None:
    def strip(words, *keys):
        return [{k: v for k, v in w.items() if k not in keys} for w in words]

    _changes(f"{where}.words", strip(before, "confidence", "hyphen"), strip(after, "confidence", "hyphen"),
             ("words", "text", "nfc"), out)
    _changes(f"{where}.words.confidence", [w.get("confidence") for w in before], [w.get("confidence") for w in after],
             ("word_confidences", "words"), out)
    _changes(f"{where}.words.hyphen", [w.get("hyphen") for w in before], [w.get("hyphen") for w in after],
             ("words", "paragraphs", "text"), out)


#: line field -> the parts that may change it
LINE_FIELDS = {
    "region_id": ("lines", "line_regions", "hierarchy"), "row": ("lines", "line_regions", "hierarchy"),
    "reading_order": ("lines", "line_regions", "hierarchy"), "bbox": ("lines",), "polygon": ("lines",),
    "score": ("lines",), "baseline": ("lines", "baselines"), "text": ("text", "nfc"),
    "alternatives": ("text", "nfc"), "normalized": ("normalized",), "confidence": ("line_confidences", "text"),
    "extra": ("lines", "text"),
}
#: region field -> the parts that may change it
REGION_FIELDS = {
    "label": ("regions", "hierarchy"), "raw_label": ("regions",), "polygon": ("regions", "hierarchy"),
    "bbox": ("regions", "hierarchy"), "score": ("regions",), "reading_order": ("reading_order", "regions",
                                                                                 "line_regions"),
    "heading_level": ("hierarchy", "regions"),
}
#: a region's extra key -> the parts that may change it (other keys: any region part)
REGION_EXTRA = {"table": ("tables", "html"), "formula": ("formulas", "latex")}


def transcription_changes(before: dict | None, after: dict | None) -> list[tuple[str, frozenset[str]]]:
    """Returns what differs between two transcriptions (their ``model_dump(mode="json")``), each difference with the
    parts that may account for it.

    Regions, lines and words are compared by id and field (a region's ``reading_order``: ``reading_order``, a
    line's ``text``: ``text`` or ``nfc``, a word's ``confidence``: ``word_confidences``, ...); paragraphs as
    ``paragraphs`` (only their ``normalized``: ``normalized``), the DoclingDocument as ``document``. The steps are
    left out (checked on their own); ``source``, ``language`` and ``extra`` are accounted for by any part of the
    transcription (``ANY``).

    Args:
        before, after: the two transcriptions as JSON-compatible dicts; ``None``: none (an empty transcription).
    """
    from ..data import Transcription

    empty = Transcription().model_dump(mode="json")
    b, a, out = before or empty, after or empty, []
    rb, ra = _by_id(b["regions"]), _by_id(a["regions"])
    _changes("regions", sorted(rb, key=str), sorted(ra, key=str), ("regions",), out)
    _changes("regions.order", list(rb), list(ra), ("regions", "reading_order", "line_regions"), out)
    for rid in rb.keys() & ra.keys():
        for f, parts in REGION_FIELDS.items():
            _changes(f"regions.{f}", rb[rid].get(f), ra[rid].get(f), parts, out)
        eb, ea = rb[rid].get("extra") or {}, ra[rid].get("extra") or {}
        for k in eb.keys() | ea.keys():
            _changes(f"regions.extra.{k}", eb.get(k), ea.get(k),
                     REGION_EXTRA.get(k, ("regions", "hierarchy", "tables", "formulas")), out)
    if any(names == frozenset({"regions"}) for where, names in out if where == "regions"):
        out = [(w, n) for w, n in out if not w.startswith("regions.")]   # regions made anew: their fields with them
    lb, la = _by_id(b["lines"]), _by_id(a["lines"])
    _changes("lines", sorted(lb, key=str), sorted(la, key=str), ("lines",), out)
    _changes("lines.order", list(lb), list(la), ("lines", "line_regions", "hierarchy"), out)
    lines_from = len(out)
    for lid in lb.keys() & la.keys():
        for f, parts in LINE_FIELDS.items():
            _changes(f"lines.{f}", lb[lid].get(f), la[lid].get(f), parts, out)
        _word_changes("lines", lb[lid].get("words") or [], la[lid].get("words") or [], out)
    # the lines' geometry made anew (a line step): what they carried goes with them
    if any(w in ("lines.bbox", "lines.polygon") for w, _ in out[lines_from:]):
        out = out[:lines_from] + [(w, n | {"lines"}) for w, n in out[lines_from:]]
    strip = [{k: v for k, v in p.items() if k != "normalized"} for p in b["paragraphs"]]
    _changes("paragraphs", strip, [{k: v for k, v in p.items() if k != "normalized"} for p in a["paragraphs"]],
             ("paragraphs",), out)
    _changes("paragraphs.normalized", [p.get("normalized") for p in b["paragraphs"]],
             [p.get("normalized") for p in a["paragraphs"]], ("normalized", "paragraphs"), out)
    _changes("docling", b.get("docling"), a.get("docling"), ("document",), out)
    for f in ("source", "language", "extra"):
        _changes(f, b.get(f), a.get(f), ANY, out)
    return out


def _covered(names: frozenset[str], declared: set[str]) -> bool:
    return names == ANY and bool(declared) or bool(names & declared) or "*" in declared


def _steps(t: dict) -> list[dict]:
    return t.get("steps") or []


def _without_varying(value: Any) -> Any:
    """``value`` (a dump) without the measurements that vary from run to run."""
    value = copy.deepcopy(value)

    def strip(t):
        for s in t.get("steps") or []:
            for k in VARYING:
                (s.get("measurements") or {}).pop(k, None)

    for t in value if isinstance(value, list) else [value]:
        if isinstance(t, dict):
            strip(t)
    return value


# ------------------------------------------------------------------------------------------------ engines

def _engine_input(cls, transcription):
    """The transcription an engine of ``cls``'s step and unit gets by default."""
    from ..data import Region
    from .samples import box

    if transcription is not None:
        return transcription
    step, unit = cls.step, (cls.capabilities or {}).get("unit")
    t = sample_layout(text=step not in ("recognition",))
    if step in ("layout", "lines"):
        t.regions, t.lines = ([], []) if step == "layout" else (t.regions, [])
    elif step in ("tables", "formulas"):
        label = "table" if step == "tables" else "formula"
        t.regions.append(Region(id=f"{label}_1", label=label, raw_label=label, polygon=box(80, 40, 640, 60),
                                bbox=[80, 40, 640, 60], reading_order=1))
    elif step == "recognition" and unit == "page":      # a page engine reads the page itself
        t.regions, t.lines = [], []
    return t


def check_engine(engine_cls, *, options: dict | None = None, image=None, transcription=None):
    """Checks that an engine class follows the engine protocol, and returns what its first call returned.

    The checks: ``engine_id`` is a code id (``<provider>.<step>[.<variant>].v<n>`` or ``<step>.<variant>.v<n>``)
    that names the engine's ``step``, one of the catalog's steps; ``capabilities`` (unit, produces) validate
    against the vocabulary and produce something; ``Options`` is a pydantic model whose fields all have a
    description, and the engine constructs with ``options``. Then it is loaded and called on the input, twice:

    * a model engine (the steps that are not rule-based) as ``engine(image, transcription)`` (the image as an RGB
      array, or as a PNG file's bytes for an engine whose ``image_input`` is ``"bytes"``): it returns a
      ``Transcription`` in which only the parts its ``capabilities.produces`` declares changed
      (``transcription_changes``), with one more ``StepInfo``, and leaves the image array as it was;
    * a rule-based engine by its unit: ``engine(transcription)`` (page), ``engine([t1, t2])`` (item, the
      transcriptions of two pages), ``engine(image_bytes) -> (bytes, info)`` (the image step);

    every new ``StepInfo`` names the engine's step, the engine id (or no engine: the block fills it in) and only
    measurements of the vocabulary (``linecaster.data.MEASUREMENTS``), and the second call returns the same as the
    first, apart from the measurements that vary from run to run (``seconds``, ``datetime``). An engine with
    weights loads them in ``load()``: a test that checks it needs them (mark it ``network``).

    Args:
        engine_cls: the engine class.
        options: keyword arguments that construct it (a preset's options and ``weights``); ``None``: none.
        image: the page image, an RGB array (the image step and an engine whose ``image_input`` is ``"bytes"``: an
            image file's bytes); default ``sample_page()`` (``sample_png()``).
        transcription: the transcription it is called with; default a sample layout fit for its step and unit
            (``sample_layout``: recognition gets lines without text, layout an empty transcription, tables and
            formulas a region of their label, a page engine (recognition, unit page) an empty transcription,
            rule-based engines a recognized page).

    Example:
        from linecaster.testing import check_engine
        from linecaster_tesseract import TesseractRecognitionEngine

        out = check_engine(TesseractRecognitionEngine, options={"lang": "eng"})
        assert all(line.text for line in out.lines)
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
        else:
            t = _engine_input(engine_cls, copy.deepcopy(transcription))
            inputs = [t, copy.deepcopy(t)] if rule and caps.unit == "item" else [t]
            before = [x.model_dump(mode="json") for x in inputs]
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
            dump = [o.model_dump(mode="json") for o in outs]
            if attempt == 0:
                for b, a in zip(before, dump):
                    for where, parts in transcription_changes(b, a):
                        if not _covered(parts, produces):
                            problems.append(f"changed {where}, which needs one of {sorted(parts)}; capabilities "
                                            f"produce {sorted(produces)}")
                    new = _steps(a)[len(_steps(b)):]
                    if not new:
                        problems.append("no StepInfo added")
                    for s in new:
                        if s.get("step") != step:
                            problems.append(f"StepInfo step {s.get('step')!r}, not {step!r}")
                        if s.get("engine") not in (None, eid):
                            problems.append(f"StepInfo engine {s.get('engine')!r}, not {eid!r}")
                        if bad := unknown_measurements(s.get("measurements") or {}):
                            problems.append(f"StepInfo measurements outside the vocabulary: {bad}")
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
    ``transcription_changes``, its parts in that transcription. The page's ``errors`` and ``trace`` are not parts.

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
    rest = ({k: v for k, v in pb.items() if k != "transcriptions"}, {k: v for k, v in pa.items() if k != "transcriptions"})
    if rest[0] != rest[1]:
        out.append(("metadata", frozenset({Part("metadata")})))
    tb, ta = pb.get("transcriptions") or {}, pa.get("transcriptions") or {}
    for name in sorted(tb.keys() | ta.keys()):
        for where, names in transcription_changes(tb.get(name), ta.get(name)):
            out.append((f"{name}:{where}", frozenset(Part("*", name) if n == "*" else Part(n, name) for n in names)))
        if name in tb and name not in ta:
            out.append(("removed", frozenset({Part("*", name)})))
    return out


def _part_covers(declared, changed) -> bool:
    """Whether a declared part accounts for a changed one: ``*`` (of the page, or of the transcription) covers
    every part of it, and a change any part of a transcription accounts for (``ANY``) is covered by any of them."""
    if declared.covers(changed) or (declared.name == "*" and declared.transcription is None):
        return True
    return changed.name == "*" and changed.transcription is not None and declared.transcription == changed.transcription


def _sample_docs(unit: str) -> list:
    """Two sample pages of one item with a recognized layout, or (unit ``item``) their item record."""
    docs = sample_documents(2)
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
    only parts it removes are gone (``page_changes``; not for a block that changes the unit, a binder or a
    splitter); a model block passes a page that carries an earlier error through unchanged; a page block that reads
    the image records a page without image bytes as that page's error and passes it on.

    Args:
        block: the block, built as a pipeline would build it.
        docs: the datatrove documents it runs on; ``None``: two sample pages of one item with a recognized layout
            (``sample_documents``), as an item record for an item-unit block; a reader reads its own input after
            them.
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
        docs = list(docs) if docs is not None else (_sample_docs(contract.unit) if contract.role != "reader" else [])
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

