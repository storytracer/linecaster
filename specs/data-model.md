# Data model decisions (overnight 2026-11-03, for review)

Decisions taken while building the first version, with the reason for each. Open for review.

1. **`regions` is a third primary part next to `docling` and `lines`.** The EBDC deck's PageOCR has two
   primary parts (`docling`, `lines`). Free combination of steps needs a layout contract that exists
   before any text: a line step and a recogniser read regions (label, polygon, reading order, score)
   long before a DoclingDocument can be built. `docling` stays the assembled document (built from
   regions + lines by an assembly step); `regions` is the contract between steps. Region ids are the
   producer's own (PP-DocLayout: `<raw label>_<index>`, orphan rows: `orphan_<n>`), and lines refer
   to them with `region_id`.
2. **Coordinates keep the producer's precision.** Polygons and baselines are float lists exactly as
   the engine returned them; `bbox` is `[x, y, width, height]` for readers, but algorithms derive
   boxes from the polygon (`geometry.bbox_of`) so their arithmetic matches the engine's (no
   `x + width` rounding).
3. **A line's `text` is `None` until a recogniser ran** (empty string = recognised as empty). Lines
   carry `reading_order` (page rank) and `row` (visual row within the region).
4. **Words are the finest level.** kraken's character cuts become words in the kraken backend with
   kraken's own rule (split at whitespace, a word's box = the bounding box of its cuts), so word
   boxes match kraken's serialiser.
5. **`model` is a list of `ModelInfo`, one per step that ran** (step, name, revision, backend,
   settings, measurements), so a composed chain records every model it used.
6. **A page is one datatrove `Document`**: `id` = page_id, `text` = the primary transcription's text,
   image bytes in `media[0]`, the page row under `metadata["page"]`.
7. **Processing order vs reading order.** The list order of `Transcription.lines` after the line
   steps is the order a recogniser processes (and batches) lines: regions in the layout step's order,
   orphan rows last, rows within each region — exactly squiddleocr's order, so batches are composed
   the same way. `reading_order` is the separate reading rank (regions by reading order, then rows).

8. **Text-only transcriptions** (a delivered plain text such as the Common Pile's BHL text) are lines
   without geometry (`bbox`, `polygon` None), one per text line, `source.kind = "converted"`,
   `source.format = "text"`. They cannot be written as ALTO/PAGE/hOCR.

9. **The retyper edits regions and lines in place** (`linecaster.retyper`, squiddleocr's rules, arithmetic
   unchanged). A split-off headline is region `<region id>_head` (raw label `<raw>/split`); its lines keep
   their ids and get the new `region_id`. Removed regions (drop capitals, uncertain page numbers) leave
   `regions` with their lines and are recorded in `Transcription.extra["retyper_dropped"]` (id, labels,
   text, line ids, reason, confidence). A drop capital's letter is prepended to the target line's text
   (`line.extra["drop_capital"]`); words are not touched. Regions are re-ranked, lines re-ordered.
10. **`docling` is assembled from regions + lines + tables** (`linecaster.document`), one document per
    page, page headers/footers always in Docling's furniture layer; exports choose whether to include
    them (`furniture=True` = squiddleocr's `--furniture`).

11. **The as-written layer is NFC, by a step of its own** (`NormalizeUnicode`, right after recognition;
    `linecaster.unicode`). Recognisers do not all deliver NFC (kraken's PP-OCRv6 models write `ä` as
    `a` + U+0308). Normalising in a separate, recorded step (`ModelInfo(step="unicode", settings={"form":
    "NFC", "unicode_version"})`) keeps each engine's raw output exactly what the engine produced, so a
    backend stays testable against the engine itself, and parity with a reference that did not
    normalise is "byte-exact after NFC on both sides" (the parity scripts normalise the goldens by
    default). Only canonical forms (NFC, NFD) are allowed; NFKC folding is the readable variants' job.
12. **One `DoclingDocument` per item** (`AssembleItemDocument`, `linecaster.document.DocumentBuilder`):
    page `n` of the document is the item's `n`-th page (sequence, then page id); paragraphs continue
    across page breaks in reflow mode; optional sections; `region_of` (item ref -> `"<page_no>:<region
    id>"`) travels with the document for Markdown dividers. A task must see whole items (the run layout
    buckets page rows by item).

## Environment lesson (2026-11-03)

`[tool.uv.sources]` applies only to a project's own dependencies. The engine environment listed the
kraken fork as a source, but kraken came in transitively (through `linecaster-kraken`), so uv
resolved upstream kraken 7.1.1, whose `--precision` is inert: the chain silently ran fp32 and 69 of
1,560 lines differed from squiddleocr's bf16 goldens. Fix: kraken is a direct dependency of
the engine environment (now the recipe `pipelines/chain.py`), and the numerically relevant versions are pinned with
`constraint-dependencies` to the ones the goldens were recorded with. After the fix the
block-composed chain (in-process) reproduces squiddleocr's goldens exactly on the 60-page sample:
1,560/1,560 lines identical in line box, text and word boxes.
