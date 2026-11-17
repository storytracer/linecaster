"""What a ground truth holds, checked before it is scored or published (``linecaster truth check``), and the
benchmark definition its data supports (``linecaster benchmark init``).

``check_page`` reports one page: its lines (with text, empty), its regions and boxes (those outside the image), its
reading order (present, complete: every region and line ranked), its conventions' coverage (an importer's
``unmapped`` measurement), its illegible characters (``status`` ``illegible`` spans and lines), the language, script
and direction it records (on the page and anywhere), its roles, statuses, tables (by ``linecaster.evaluation.tables``'s
kinds), formulas, notes and continuations. ``check`` reads a folder of page records and adds the totals and the pages
whose texts are the same (duplicates). ``supports`` is what a benchmark's ``supports`` says of those pages;
``benchmark`` writes a ``linecaster.benchmark/2`` definition from them, ``page_values`` gives a page's value for a
stratified sample (``linecaster.data.sample``).

Import-light, like the rest of ``linecaster.evaluation``: a folder is read through datatrove's ``DataFolder``, imported
when it is read."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Iterator
from typing import Any

from linecaster.data.page import Page
from linecaster.data.refs import parse
from linecaster.data.transcription import Transcription

SCHEMA = "linecaster.truth-check/1"
#: the page values a stratified sample or a benchmark's strata may name besides a classification scheme:
#: ``metadata.<key>`` (the page's metadata), ``source.<field>`` (the transcription's source, an extension field too)
VALUE_PREFIXES = ("metadata.", "source.")
#: the roles of notes (``supports.notes``), besides ``note_of`` links
NOTE_ROLES = frozenset({"footnote", "footnote_continued", "endnote"})
#: scripts written without spaces between words
UNSPACED = frozenset({"Hani", "Hans", "Hant", "Jpan", "Hira", "Kana", "Thai", "Laoo", "Khmr", "Mymr", "Tibt", "Bopo",
                      "Yiii", "Tale", "Talu", "Lana"})
#: scripts whose letters take combining marks as a rule (vowel signs, points)
MARKED = frozenset({"Deva", "Beng", "Guru", "Gujr", "Orya", "Taml", "Telu", "Knda", "Mlym", "Sinh", "Arab", "Hebr",
                    "Syrc", "Thaa", "Nkoo", "Thai", "Laoo", "Khmr", "Mymr", "Tibt", "Ethi"})


# ------------------------------------------------------------------------------------------------ reading
def read_rows(folder: str, ids: set[str] | None = None) -> Iterator[dict]:
    """The stored rows of a folder of page records (local path or fsspec URI; JSON Lines, gzipped or not, or
    Parquet), upgraded; with ``ids``, only those pages (their lines decoded only)."""
    from datatrove.io import get_datafolder

    from linecaster.data.upgrade import upgrade
    from linecaster.evaluation.run import _ID

    df = get_datafolder(folder)
    for name in sorted(df.list_files()):
        if name.endswith((".jsonl", ".jsonl.gz")):
            with df.open(name, "rt", compression="gzip" if name.endswith(".gz") else None, encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    if ids is not None:
                        m = _ID.search(line, 0, 400)
                        if m is None or json.loads(f'"{m.group(1)}"') not in ids:
                            continue
                    yield upgrade(json.loads(line))
        elif name.endswith(".parquet"):
            import pyarrow.parquet as pq

            with df.open(name, "rb") as fh:
                for row in pq.read_table(fh).to_pylist():
                    if ids is not None and row.get("id") not in ids:
                        continue
                    for key in ("page", "errors"):
                        if isinstance(row.get(key), str):
                            row[key] = json.loads(row[key])
                    yield upgrade(row)


def read_pages(folder: str, ids: set[str] | None = None) -> Iterator[Page]:
    """The pages of a folder of page records (``read_rows``), each once (the first row of an id)."""
    seen: set[str] = set()
    for row in read_rows(folder, ids):
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        yield Page.model_validate(row["page"])


# ------------------------------------------------------------------------------------------------ one page
def page_values(page: Page, name: str, transcription: str = "ground_truth") -> str | None:
    """A page's value of ``name``: a classification scheme recorded on the page (``language``, ``script`` and
    ``direction`` as ``Transcription.language`` reads them: on the page), ``metadata.<key>`` (the page's metadata)
    or ``source.<field>`` (the transcription's source: a field or an extension field); ``None`` where it records
    none."""
    t = page.transcriptions.get(transcription)
    if name.startswith("metadata."):
        value = page.metadata.get(name.removeprefix("metadata."))
    elif t is None:
        return None
    elif name.startswith("source."):
        field = name.removeprefix("source.")
        value = getattr(t.source, field, None) if field in type(t.source).model_fields else t.source.extensions.get(
            field)
    elif name in ("language", "script", "direction"):
        value = t.written("", name)
    else:
        value = t.classification("", name)
    if value is None or value == "" or value == []:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def _outside(box, width: int | None, height: int | None, tolerance: float = 0.5) -> bool:
    x, y, w, h = box
    return x < -tolerance or y < -tolerance or x + w > width + tolerance or y + h > height + tolerance


def _order(t: Transcription) -> tuple[str, int, int]:
    """The reading order's state (``none``, ``partial``, ``complete``) and the regions and lines it leaves unranked:
    with an order of regions, a region outside it is unranked, and so is a line whose region is; with an order of
    lines, a line outside it; with only an order of lines, a region none of whose lines it ranks."""
    ro, lo = t.order("regions"), t.order("lines")
    if ro is None and lo is None:
        return ("none" if t.regions or t.lines else "complete"), len(t.regions), len(t.lines)
    ranked_regions = set(ro.regions) if ro is not None else {t.region_of(ln) for ln in t.lines if ln.id in set(lo.lines)}
    regions = sum(1 for r in t.regions if r.id not in ranked_regions)
    if lo is not None:
        ranked_lines = set(lo.lines)
        lines = sum(1 for ln in t.lines if ln.id not in ranked_lines)
    else:
        lines = sum(1 for ln in t.lines if t.region_of(ln) not in ranked_regions)
    return ("complete" if regions == lines == 0 else "partial"), regions, lines


def _illegible(t: Transcription) -> int:
    """The characters of ``t``'s readings classified ``status`` ``illegible``: a span of a line, a word or a line."""
    spans: dict[str, list[tuple[int, int]]] = {}
    whole: set[str] = set()
    for c in t.classifications:
        if c.scheme != "status" or c.value != "illegible":
            continue
        ref = parse(c.target)
        if ref.page is not None:
            continue
        ln = t.line(ref.id)
        if ln is None or ln.reading is None:
            continue
        if ref.word is not None and ref.word < len(ln.reading.words):
            word = ln.reading.words[ref.word].text or ""
            spans.setdefault(ln.id, []).append((0, len(word)))          # a word: its characters
        elif ref.span is not None:
            spans.setdefault(ln.id, []).append(ref.span)
        else:
            whole.add(ln.id)
    count = 0
    for ln in t.lines:
        if ln.reading is None:
            continue
        if ln.id in whole:
            count += len(ln.reading.text)
            continue
        covered: set[int] = set()
        for a, b in spans.get(ln.id, ()):
            covered.update(range(max(0, a), min(b, len(ln.reading.text))))
        count += len(covered)
    return count


def check_page(page: Page, transcription: str = "ground_truth") -> dict[str, Any]:
    """One page's report (module docstring); ``missing`` where the page has no such transcription."""
    from linecaster.evaluation.tables import table_kind

    t = page.transcriptions.get(transcription)
    out: dict[str, Any] = {"page_id": page.page_id, "item_id": page.item_id}
    if t is None:
        return {**out, "missing": True}
    width = t.source.image_width or (page.image.width if page.image else None)
    height = t.source.image_height or (page.image.height if page.image else None)
    zones = [*t.regions, *t.lines]
    boxed = [z for z in zones if z.box is not None]
    order, unranked_regions, unranked_lines = _order(t)
    read = [ln for ln in t.lines if ln.reading is not None]
    with_text = sum(1 for ln in read if ln.reading.text.strip())
    unmapped: Counter = Counter()
    conventions = []
    for a in t.annotators:
        if a.conventions:
            conventions.append({"conventions": a.conventions, "sha256": a.conventions_sha256})
        unmapped.update({str(k): int(v) for k, v in (a.measurements.get("unmapped") or {}).items()})
    any_of = {s: sorted({c.value for c in t.classifications if c.scheme == s}) for s in ("language", "script",
                                                                                         "direction")}
    roles = Counter(t.role(r.id) or "" for r in t.regions)
    statuses = Counter(c.value for c in t.classifications if c.scheme == "status")
    tables = [tb for tb in t.tables if tb.cells]
    region_ids = {r.id for r in t.regions}
    text = t.text
    return {**out, "missing": False,
            "lines": len(t.lines), "lines_with_text": with_text, "empty_lines": len(t.lines) - with_text,
            "regions": len(t.regions), "regions_with_box": sum(1 for r in t.regions if r.box is not None),
            "boxes": len(boxed), "image_size": [width, height] if width and height else None,
            "boxes_outside": sum(1 for z in boxed if _outside(z.box, width, height)) if width and height else None,
            "reading_order": order, "unranked_regions": unranked_regions, "unranked_lines": unranked_lines,
            "conventions": conventions, "unmapped": dict(unmapped.most_common()),
            "characters": sum(len(ln.reading.text) for ln in read), "illegible_characters": _illegible(t),
            "language": t.language(""), "script": t.script(""), "direction": t.direction(""),
            "languages": any_of["language"], "scripts": any_of["script"], "directions": any_of["direction"],
            "roles": dict(sorted(roles.items())), "statuses": dict(sorted(statuses.items())),
            "tables": len(tables), "table_kinds": dict(sorted(Counter(table_kind(tb) for tb in tables).items())),
            "formulas": {"regions": sum(1 for f in t.formulas if f.target in region_ids),
                         "inline": sum(1 for f in t.formulas if f.target not in region_ids)},
            "notes": sum(1 for r in t.regions if t.role(r.id) in NOTE_ROLES) + sum(
                1 for ln in t.links if ln.kind == "note_of"),
            "continuations": sum(1 for ln in t.links if ln.kind == "continues"),
            "normalized": list(t.source.normalized),
            "text_sha256": hashlib.sha256(" ".join(text.split()).encode()).hexdigest() if text.strip() else None}


# ------------------------------------------------------------------------------------------------ all pages
def _merge(counter: Counter, value: dict) -> None:
    counter.update(value or {})


def summarize(pages: list[dict]) -> dict[str, Any]:
    """The totals of page reports (``check_page``'s)."""
    present = [p for p in pages if not p.get("missing")]
    total: dict[str, Any] = {"pages": len(pages), "items": len({p["item_id"] for p in pages}),
                             "missing": len(pages) - len(present)}
    for key in ("lines", "lines_with_text", "empty_lines", "regions", "regions_with_box", "boxes", "tables",
                "notes", "continuations", "characters", "illegible_characters", "unranked_regions",
                "unranked_lines"):
        total[key] = sum(p[key] for p in present)
    total["boxes_outside"] = sum(p["boxes_outside"] or 0 for p in present)
    total["pages_with_boxes_outside"] = sum(1 for p in present if p["boxes_outside"])
    total["pages_without_image_size"] = sum(1 for p in present if p["image_size"] is None)
    total["pages_without_text"] = sum(1 for p in present if p["text_sha256"] is None)
    total["reading_order"] = dict(sorted(Counter(p["reading_order"] for p in present).items()))
    total["illegible_share"] = (total["illegible_characters"] / total["characters"]) if total["characters"] else None
    for key in ("roles", "statuses", "table_kinds", "unmapped"):
        c: Counter = Counter()
        for p in present:
            _merge(c, p[key])
        total[key] = dict(sorted(c.items())) if key != "unmapped" else dict(c.most_common())
    total["formulas"] = {k: sum(p["formulas"][k] for p in present) for k in ("regions", "inline")}
    conventions: dict[tuple, int] = {}
    for p in present:
        for c in {(c["conventions"], c["sha256"]) for c in p["conventions"]}:
            conventions[c] = conventions.get(c, 0) + 1
    total["conventions"] = [{"conventions": c, "sha256": h, "pages": n} for (c, h), n in sorted(conventions.items())]
    for scheme, many in (("language", "languages"), ("script", "scripts"), ("direction", "directions")):
        total[many] = dict(sorted(Counter(p[scheme] for p in present if p[scheme]).items()))
        total[f"pages_without_{scheme}"] = sum(1 for p in present if not p[scheme])
        total[f"any_{many}"] = sorted({v for p in present for v in p[many]})
    normalized: Counter = Counter()
    for p in present:
        normalized.update(set(p["normalized"]))
    total["normalized"] = dict(sorted(normalized.items()))
    by_text: dict[str, list[str]] = {}
    for p in present:
        if p["text_sha256"]:
            by_text.setdefault(p["text_sha256"], []).append(p["page_id"])
    total["duplicates"] = sorted(sorted(ids) for ids in by_text.values() if len(ids) > 1)
    return total


def check(truth: str, transcription: str = "ground_truth", ids: set[str] | None = None) -> dict[str, Any]:
    """A folder of page records checked (module docstring): ``{"schema", "truth", "transcription", "producer",
    "total", "pages"}``; with ``ids``, only those pages (one a folder lacks is reported ``missing``)."""
    from linecaster.data.transcription import producer

    pages = [check_page(p, transcription) for p in read_pages(truth, ids)]
    for pid in sorted((ids or set()) - {p["page_id"] for p in pages}):
        pages.append({"page_id": pid, "item_id": None, "missing": True})
    return {"schema": SCHEMA, "truth": str(truth), "transcription": transcription, "producer": producer(),
            "total": summarize(pages), "pages": pages}


def supports(pages: Iterable[dict]) -> dict[str, Any]:
    """What a benchmark's ``supports`` says of the pages reported (``check_page``'s): the roles marked, whether every
    region has a box, whether every page with zones is ordered, whether notes and continuations are marked."""
    present = [p for p in pages if not p.get("missing")]
    regions = sum(p["regions"] for p in present)
    return {"roles": sorted({r for p in present for r in p["roles"] if r}),
            "boxes": regions > 0 and all(p["regions_with_box"] == p["regions"] for p in present),
            "reading_order": bool(present) and all(p["reading_order"] != "none" for p in present),
            "notes": any(p["notes"] for p in present),
            "continuations": any(p["continuations"] for p in present)}


def render(report: dict[str, Any], limit: int = 10) -> str:
    """A check's report as text: the totals, then the pages with problems (at most ``limit`` named of each)."""
    tot, pages = report["total"], [p for p in report["pages"] if not p.get("missing")]

    def named(ids: list[str]) -> str:
        return ", ".join(ids[:limit]) + (f", … ({len(ids) - limit} more)" if len(ids) > limit else "")

    def counts(d: dict) -> str:
        return ", ".join(f"{k or '(none)'} {v:,}" for k, v in d.items()) or "none"

    share = tot["illegible_share"]
    out = [f"truth {report['truth']} ({report['transcription']})",
           f"pages {tot['pages']:,} (items {tot['items']:,}); missing the transcription {tot['missing']:,}; "
           f"without text {tot['pages_without_text']:,}",
           f"lines {tot['lines']:,}: with text {tot['lines_with_text']:,}, empty {tot['empty_lines']:,}",
           f"regions {tot['regions']:,} (with a box {tot['regions_with_box']:,}); boxes outside the image "
           f"{tot['boxes_outside']:,} on {tot['pages_with_boxes_outside']:,} pages; pages without an image size "
           f"{tot['pages_without_image_size']:,}",
           f"reading order: {counts(tot['reading_order'])}; unranked regions {tot['unranked_regions']:,}, lines "
           f"{tot['unranked_lines']:,}",
           f"illegible characters {tot['illegible_characters']:,} of {tot['characters']:,}"
           + (f" ({share:.4%})" if share is not None else "")]
    for scheme, many in (("language", "languages"), ("script", "scripts"), ("direction", "directions")):
        out.append(f"{scheme} (page): {counts(tot[many])}; pages without one {tot[f'pages_without_{scheme}']:,}; "
                   f"recorded anywhere: {', '.join(tot[f'any_{many}']) or 'none'}")
    out.append(f"roles: {counts(tot['roles'])}")
    out.append(f"statuses: {counts(tot['statuses'])}")
    out.append(f"tables {tot['tables']:,} ({counts(tot['table_kinds'])}); formulas: regions "
               f"{tot['formulas']['regions']:,}, inline {tot['formulas']['inline']:,}; notes {tot['notes']:,}; "
               f"continuations {tot['continuations']:,}")
    for c in tot["conventions"]:
        out.append(f"conventions {c['conventions']} ({c['sha256']}): {c['pages']:,} pages")
    if tot["unmapped"]:
        out.append(f"unmapped by the conventions: {sum(tot['unmapped'].values()):,} "
                   f"({counts(dict(list(tot['unmapped'].items())[:limit]))})")
    if tot["normalized"]:
        out.append(f"normalizations embodied: {counts(tot['normalized'])}")
    s = supports(report["pages"])
    out.append(f"supports: roles {', '.join(s['roles']) or 'none'}; boxes {s['boxes']}; reading order "
               f"{s['reading_order']}; notes {s['notes']}; continuations {s['continuations']}")
    problems = [("pages missing the transcription", [p["page_id"] for p in report["pages"] if p.get("missing")]),
                ("pages without text", [p["page_id"] for p in pages if p["text_sha256"] is None]),
                ("pages with boxes outside the image", [p["page_id"] for p in pages if p["boxes_outside"]]),
                ("pages without a reading order", [p["page_id"] for p in pages if p["reading_order"] == "none"]),
                ("pages with a partial reading order", [p["page_id"] for p in pages if p["reading_order"] == "partial"]),
                ("pages without a language", [p["page_id"] for p in pages if not p["language"]])]
    for what, ids in problems:
        if ids:
            out.append(f"{what} ({len(ids):,}): {named(ids)}")
    for group in tot["duplicates"][:limit]:
        out.append(f"same text: {', '.join(group)}")
    if len(tot["duplicates"]) > limit:
        out.append(f"… {len(tot['duplicates']) - limit} more groups of pages with the same text")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ benchmark init
def script_note(script: str) -> str:
    """What a benchmark's lanes and tokenizer do with ``script`` (an ISO 15924 code), for the comment
    ``benchmark`` writes."""
    notes = []
    if script in UNSPACED:
        notes.append("written without spaces between words: words uax29 (the default) cuts its text by Unicode's "
                     "word boundaries (ideographs, Hiragana and Thai one word per character); whitespace would make "
                     "each run between spaces one word")
    if script in MARKED:
        notes.append("its letters take combining marks: unit grapheme (the default) counts a letter with its marks "
                     "as one character, and the word metrics keep the marks")
    from linecaster.text.scripts import RIGHT_TO_LEFT

    if script in RIGHT_TO_LEFT:
        notes.append("written right to left: both sides are compared in the order stored (logical order)")
    if not notes:
        notes.append("diplomatic keeps case, punctuation and diacritics; reading casefolds and removes markup")
    return "; ".join(notes)


def _scripts(pages: list[dict]) -> Counter:
    """Pages per script recorded: the page's or any script classification, else the script subtag of the language
    recorded (``zh-Hans``: ``Hans``)."""
    found: Counter = Counter()
    for p in pages:
        if p.get("missing"):
            continue
        scripts = set(p["scripts"]) | ({p["script"]} if p["script"] else set())
        if not scripts:
            for tag in [p["language"], *p["languages"]]:
                for sub in (tag or "").split("-")[1:]:
                    if len(sub) == 4 and sub.isalpha():
                        scripts.add(sub.title())
        found.update(scripts)
    return found


def benchmark(truth: str, id: str, transcription: str = "ground_truth", rule=None, dataset: str | None = None,
              importer: str | None = None) -> tuple[dict, list[str]]:
    """A ``linecaster.benchmark/2`` definition of the ground truth's pages (a folder of page records), checked by
    ``Benchmark.model_validate``, and the comment lines that go above it: ``pages`` its page ids with their hash
    (and ``rule``, a ``linecaster.data.sample.SampleRule``, where one chose them; its ``stratify`` names a page
    value, ``page_values``), ``supports`` from the data (``supports``), the lanes ``diplomatic`` and ``reading``, and
    the dataset (``dataset``, else the one its sources name) and importer (``importer``, else the preset or engine
    of the import annotator, else the source's format). A comment per script recorded says what the lanes and the
    tokenizer do with it."""
    from linecaster.data.sample import listing_sha256, sample_pairs
    from linecaster.data.transcription import producer
    from linecaster.evaluation.benchmark import SCHEMA as BENCHMARK
    from linecaster.evaluation.benchmark import Benchmark

    pages = list(read_pages(truth))
    if not pages:
        raise ValueError(f"{truth}: no page records")
    if rule is not None:
        strata = None
        if rule.stratify is not None:
            values = {p.page_id: page_values(p, rule.stratify, transcription) for p in pages}
            strata = values
        chosen = sample_pairs([(p.item_id, p.page_id) for p in pages], rule, strata)
        wanted = {s.page_id for s in chosen.selected}
        pages = [p for p in pages if p.page_id in wanted]
    reports = [check_page(p, transcription) for p in pages]
    lacking = [r["page_id"] for r in reports if r.get("missing")]
    if lacking:
        raise ValueError(f"{len(lacking)} pages have no transcription {transcription!r} (e.g. {lacking[0]})")
    if dataset is None:
        named = {p.transcriptions[transcription].source.dataset for p in pages}
        if len(named) != 1 or None in named:
            raise ValueError("name the ground truth's dataset (repo@revision): its sources name "
                             + (", ".join(sorted(x for x in named if x)) or "none"))
        dataset = named.pop()
    if importer is None:
        found = set()
        for p in pages:
            t = p.transcriptions[transcription]
            rules = [a for a in t.annotators if a.kind == "rule" and a.step == "import"]
            found.add(rules[-1].preset or rules[-1].engine if rules else t.source.format)
        if len(found) != 1 or None in found:
            raise ValueError("name the importer that made the page records: they name "
                             + (", ".join(sorted(x for x in found if x)) or "none"))
        importer = found.pop()
    ids = sorted(p.page_id for p in pages)
    data: dict[str, Any] = {"schema": BENCHMARK, "id": id,
                            "dataset": {"repo": dataset, "transcription": transcription, "importer": importer},
                            "pages": {**({"rule": rule.to_dict()} if rule is not None else {}), "ids": ids,
                                      "sha256": listing_sha256(ids)},
                            "supports": supports(reports), "lanes": ["diplomatic", "reading"]}
    if rule is not None and rule.stratify is not None:
        data["strata"] = [rule.stratify]
    Benchmark.model_validate(data)
    s = data["supports"]
    comments = [f"written by linecaster benchmark init ({producer()}) from {truth} ({transcription}): "
                f"{len(ids):,} pages",
                "supports: from the ground truth's data (linecaster truth check)"]
    possible = [m for m, ok in (("role_words", bool(s["roles"])), ("confusion", s["boxes"])) if ok]
    if possible:
        comments.append(f"metrics it supports besides the defaults: {', '.join(possible)}")
    for script, n in sorted(_scripts(reports).items()):
        comments.append(f"script {script} (recorded on {n:,} pages): {script_note(script)}")
    return data, comments


def write_benchmark(data: dict, comments: list[str], path) -> None:
    """The definition as YAML with its comment lines above it."""
    from pathlib import Path

    import yaml

    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
    text = "".join(f"# {c}\n" for c in comments) + body
    Path(path).write_text(text, encoding="utf-8")
