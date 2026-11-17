"""A ground truth published as a dataset for the Hugging Face Hub (``linecaster truth publish``): its page records as
Parquet, one row per page (``id``, ``item_id``, ``image``, ``text``, ``language``, ``script``, ``page``), in
``OUT/data/<split>-<n>-of-<m>.parquet``, and a dataset card, ``OUT/README.md``, generated from the records: their
sources and licenses, the conventions they were read with (with their hashes), the languages and scripts recorded
(with page counts), what the ground truth supports (as ``linecaster benchmark init`` says), the normalizations it
embodies, its counts and the linecaster that wrote it.

The image column is the Hub's ``Image`` feature (``{"bytes", "path"}``): the bytes of each page's image, from a
folder (``images``: the file of the image's name, else of the page id) or read by the caller's ``read_image`` (the
page record's ``image.uri``); a page whose image is not found has none. ``page`` is the page record as JSON
(``linecaster.page/N``: ``Page.model_validate(json.loads(row["page"]))`` reads it), ``text`` the transcription's text
(``Transcription.text``: literal, as laid out). Splits (``splits``) are by item (``linecaster.data.sample.split_of``:
all pages of an item in one split). Import-light: the page records are read as ``linecaster.scoring.truth`` reads
them."""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from linecaster.data.page import Page
from linecaster.scoring.truth import check_page, read_pages, summarize, supports

#: the columns, in order, as the Hub's dataset features
FEATURES = {"id": {"dtype": "string", "_type": "Value"}, "item_id": {"dtype": "string", "_type": "Value"},
            "image": {"_type": "Image"}, "text": {"dtype": "string", "_type": "Value"},
            "language": {"dtype": "string", "_type": "Value"}, "script": {"dtype": "string", "_type": "Value"},
            "page": {"dtype": "string", "_type": "Value"}}


def _licenses(page: Page, transcription: str) -> set[str]:
    """The licenses a page records: an extension field or metadata key ``<ns>__license``, on the transcription's
    source or the page."""
    t = page.transcriptions.get(transcription)
    found = set()
    for d in (t.source.extensions if t is not None else {}, page.metadata):
        for k, v in d.items():
            if k.endswith("__license") and isinstance(v, str) and v.strip():
                found.add(v.strip())
    return found


def _image(page: Page, images: str | None, read_image: Callable[[str], bytes] | None) -> dict | None:
    uri = page.image.uri if page.image is not None else None
    name = uri.rsplit("/", 1)[-1].split("#", 1)[0] if uri else None
    if images is not None:
        folder = Path(images)
        candidates = ([folder / name] if name else []) + sorted(folder.glob(f"{page.page_id}.*"))
        for c in candidates:
            if c.is_file():
                return {"bytes": c.read_bytes(), "path": c.name}
        return None
    if uri and read_image is not None:
        try:
            return {"bytes": read_image(uri), "path": name}
        except Exception:  # noqa: BLE001 - a page without its image is counted, not a failed publish
            return None
    return None


def _size(n: int) -> str:
    for limit, name in ((1_000, "n<1K"), (10_000, "1K<n<10K"), (100_000, "10K<n<100K"), (1_000_000, "100K<n<1M"),
                        (10_000_000, "1M<n<10M")):
        if n < limit:
            return name
    return "n>10M"


def publish(truth: str, out: str, transcription: str = "ground_truth", images: str | None = None,
            read_image: Callable[[str], bytes] | None = None, splits: dict[str, float] | None = None, seed: int = 0,
            license: str | None = None, name: str | None = None, shard_pages: int = 1000) -> dict[str, Any]:
    """The ground truth's page records (a folder) as a Hub dataset in ``out`` (module docstring). ``splits``: named
    fractions of the items (default: every page in ``train``); ``license``: the card's license where the records
    record none (else ``other``); ``name`` the card's title. Returns the counts: ``pages``, ``images``, ``splits``
    (pages per split), ``files``."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from linecaster.data.sample import split_of
    from linecaster.data.transcription import producer

    pages = [p for p in read_pages(truth) if transcription in p.transcriptions]
    if not pages:
        raise ValueError(f"{truth}: no page records with a transcription {transcription!r}")
    reports = [check_page(p, transcription) for p in pages]
    rows: dict[str, list[dict]] = {}
    licenses: Counter = Counter()
    datasets: Counter = Counter()
    found = 0
    for page in pages:
        t = page.transcriptions[transcription]
        split = split_of(seed, page.item_id or "", splits) if splits else "train"
        image = _image(page, images, read_image)
        found += image is not None
        licenses.update(_licenses(page, transcription))
        if t.source.dataset:
            datasets[t.source.dataset] += 1
        rows.setdefault(split, []).append({
            "id": page.page_id, "item_id": page.item_id, "image": image, "text": t.text,
            "language": t.language(""), "script": t.script(""),
            "page": json.dumps(page.record(), ensure_ascii=False, separators=(",", ":"))})
    schema = pa.schema([("id", pa.string()), ("item_id", pa.string()),
                        ("image", pa.struct([("bytes", pa.binary()), ("path", pa.string())])),
                        ("text", pa.string()), ("language", pa.string()), ("script", pa.string()),
                        ("page", pa.string())],
                       metadata={b"huggingface": json.dumps({"info": {"features": FEATURES}}).encode(),
                                 b"linecaster": producer().encode()})
    folder = Path(out)
    (folder / "data").mkdir(parents=True, exist_ok=True)
    files = []
    for split, chunk in sorted(rows.items()):
        shards = [chunk[i:i + shard_pages] for i in range(0, len(chunk), shard_pages)]
        for k, shard in enumerate(shards):
            path = folder / "data" / f"{split}-{k:05d}-of-{len(shards):05d}.parquet"
            pq.write_table(pa.Table.from_pylist(shard, schema=schema), path, compression="zstd")
            files.append(path)
    total = summarize(reports)
    card = dataset_card(total, supports(reports), licenses, datasets, sorted(rows), name or folder.resolve().name,
                        license, transcription, {s: len(c) for s, c in rows.items()}, found, splits, seed)
    (folder / "README.md").write_text(card, encoding="utf-8")
    return {"pages": len(pages), "images": found, "splits": {s: len(c) for s, c in sorted(rows.items())},
            "files": [str(f) for f in files]}


def dataset_card(total: dict, sup: dict, licenses: Counter, datasets: Counter, split_names: list[str], name: str,
                 license: str | None, transcription: str, split_pages: dict[str, int], images: int,
                 splits: dict[str, float] | None, seed: int) -> str:
    """The dataset card (``README.md``): YAML front matter for the Hub, then what the records say (module
    docstring)."""
    import yaml

    from linecaster.data.page import PAGE_SCHEMA as PAGE
    from linecaster.data.transcription import producer

    recorded = sorted(licenses)
    card_license = (recorded[0].lower() if len(recorded) == 1 else "other") if recorded else (license or "other")
    languages = sorted({tag.split("-")[0].lower() for tag in [*total["languages"], *total["any_languages"]]}
                       - {"mul", "und", "zxx", "mis"})
    front: dict[str, Any] = {"license": card_license}
    if languages:
        front["language"] = languages
    front.update({"task_categories": ["image-to-text"], "tags": ["ocr", "ground-truth", "linecaster"],
                  "size_categories": [_size(total["pages"])],
                  "configs": [{"config_name": "default",
                               "data_files": [{"split": s, "path": f"data/{s}-*"} for s in split_names]}]})
    lines = ["---", yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip(), "---", "", f"# {name}", "",
             f"A ground truth of {total['pages']:,} pages ({total['items']:,} items), its page records as written by "
             f"linecaster ({producer()}), the transcription `{transcription}` of each.", ""]
    lines += ["## Sources", ""]
    if datasets:
        lines += ["| Dataset | Pages |", "|---|---|"] + [f"| `{d}` | {n:,} |" for d, n in sorted(datasets.items())]
    else:
        lines.append("The page records name no dataset.")
    lines += ["", "Each page record names the file or row it was read from (`source.record`, `source.uri`) and "
                  "who made it (its annotators)."]
    if recorded:
        lines += ["", "Licenses recorded: " + ", ".join(f"`{x}`" for x in recorded) + "."]
    elif license:
        lines += ["", f"License: `{license}` (the records record none)."]
    else:
        lines += ["", "The records record no license: `other` until the publisher states one."]
    lines += ["", "## Conventions", ""]
    if total["conventions"]:
        lines += ["| Conventions | Hash | Pages |", "|---|---|---|"] + [
            f"| `{c['conventions']}` | `{c['sha256']}` | {c['pages']:,} |" for c in total["conventions"]]
    else:
        lines.append("Read without conventions of a source.")
    lines += ["", "## Languages and scripts", "", "Recorded on the page (a value is never guessed into a record):", "",
              "| Scheme | Value | Pages |", "|---|---|---|"]
    for scheme, many in (("language", "languages"), ("script", "scripts"), ("direction", "directions")):
        for value, n in total[many].items():
            lines.append(f"| {scheme} | `{value}` | {n:,} |")
        lines.append(f"| {scheme} | (none) | {total[f'pages_without_{scheme}']:,} |")
    lines += ["", "## What it supports", "",
              f"- roles: {', '.join(f'`{r}`' for r in sup['roles']) or 'none'}",
              f"- boxes: {'yes' if sup['boxes'] else 'no'}",
              f"- reading order: {'yes' if sup['reading_order'] else 'no'}",
              f"- notes: {'yes' if sup['notes'] else 'no'}",
              f"- continuations: {'yes' if sup['continuations'] else 'no'}", "",
              "## Normalizations it embodies", ""]
    if total["normalized"]:
        lines += [f"- `{k}`: {n:,} pages" for k, n in total["normalized"].items()]
    else:
        lines.append("None declared (`source.normalized`): its text is as its source wrote it.")
    lines += ["", "## Counts", "", "| | |", "|---|---|",
              f"| pages | {total['pages']:,} |", f"| items | {total['items']:,} |",
              f"| pages with an image | {images:,} |",
              f"| lines | {total['lines']:,} (with text {total['lines_with_text']:,}) |",
              f"| regions | {total['regions']:,} |",
              f"| tables | {total['tables']:,} |",
              f"| formulas | {total['formulas']['regions']:,} regions, {total['formulas']['inline']:,} inline |",
              f"| characters | {total['characters']:,} (illegible {total['illegible_characters']:,}) |"]
    lines += ["", "## Splits", ""]
    if splits:
        lines.append("By item (every page of an item in one split; `linecaster.data.sample.split_of`, seed "
                     f"{seed}): " + ", ".join(f"`{s}` {f:g}" for s, f in splits.items()) + ".")
    lines += ["", "| Split | Pages |", "|---|---|"] + [f"| `{s}` | {n:,} |" for s, n in sorted(split_pages.items())]
    lines += ["", "## Format", "",
              "One row per page: `id` (the page id), `item_id`, `image` (the page image), `text` (the transcription's "
              "literal text, as laid out), `language` and `script` (recorded on the page), and `page`, the page "
              f"record as JSON (`{PAGE}`), which linecaster reads with "
              "`linecaster.data.Page.model_validate(json.loads(row[\"page\"]))`.", ""]
    return "\n".join(lines)
