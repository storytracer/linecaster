# The data model

`linecaster.transcription` holds what a page's text recognition produces; `linecaster.page` the row it
travels in. Importing either needs neither datatrove nor saturate nor an engine.

## Classes

| Class | Is | Key |
|---|---|---|
| `Item` | any multi-page unit: book, issue, manuscript, file | `item_id` |
| `Page` | one row: the page image and its named transcriptions | `page_id` = `item_id` + sequence |
| `PageImage` | the image's location, size, format and hashes | |
| `Transcription` | OCR, HTR or ground truth of one page | |
| `Text` | one text per item and variant (`linecaster.text`) | |

## A page in a pipeline

A page is one datatrove `Document`: `id` is the page id, `text` the primary transcription's text, `media[0]`
the image bytes, `metadata["page"]` the page row.

## `Transcription`

| Part | Holds |
|---|---|
| `regions` | the layout: id, `label` (a DoclingDocument label), `raw_label` (the producer's), polygon, bbox, score, `reading_order`, `heading_level`, `extra` |
| `lines` | id, `region_id`, `reading_order`, `row`, bbox, polygon, baseline, score, `text`, confidence, alternatives, `words`, `extra` |
| `docling` | the page's composed DoclingDocument, as docling-core dumps it |
| `language` | |
| `model` | one `ModelInfo` per step that ran: step, name, revision, preset and its hash, recipe and its hash, backend, settings, measurements |
| `source` | `kind` (`produced`, `converted`, `ground_truth`), `format`, `uri`, image size |
| derived | `text` (as written, as laid out, full page; tables as Markdown), `confidence` (line confidences weighted by length) |

- **`regions` are the contract between steps.** Lines and recognisers need the layout (label, polygon,
  reading order, score) long before a DoclingDocument can be built, so regions are a primary part next to
  `lines`; `docling` is composed from regions, lines and tables. Region ids are the producer's own
  (PP-DocLayout: `<raw label>_<index>`; rows outside every region: `orphan_<n>`); lines refer to them with
  `region_id`.
- **Words are the finest level**; there is no glyph level. Engines with character positions turn them into
  words by the engine's own rule (kraken: split at whitespace, a word's box the bounding box of its cuts).
- **A line's `text` is `None` until a recogniser ran**; an empty string is a line recognised as empty.
- **Text-only transcriptions** (a delivered plain text) are lines without geometry (`bbox` and `polygon`
  `None`), one per text line, `source.kind = "converted"`, `source.format = "text"`. They cannot be written as
  ALTO, PAGE or hOCR.

## Geometry

Every `bbox` is `[x, y, width, height]` in pixels of the received image. Polygons and baselines are float
lists exactly as the engine returned them. Algorithms derive boxes from the polygon (`geometry.bbox_of`), so
their arithmetic matches the engine's (no `x + width` rounding). `Transcription.scaled(sx, sy)` moves every
coordinate to another image size.

## Order

- **Processing order** is the list order of `Transcription.lines` after the line steps: regions in the layout
  step's order, orphan rows last, rows within each region. A recogniser processes and batches lines in this
  order.
- **Reading order** is separate: `reading_order` ranks the lines on the page (regions by their reading order,
  then rows); `row` is the visual row within a region.

## Unicode

The as-written layer is NFC, made by a step of its own: `NormalizeUnicode` (`linecaster.unicode`) right after
recognition, recorded as `ModelInfo(step="unicode", settings={"form": "NFC", "unicode_version": ...})`. Each
engine's raw output stays exactly what the engine produced. Only canonical forms (NFC, NFD) are allowed; never
NFKC, whose folding is the readable variants' job (`linecaster.text`).

## Typography (`linecaster.retyper`)

The retyper edits regions and lines in place:

- A split-off headline is region `<region id>_head` (raw label `<raw>/split`); its lines keep their ids and get
  the new `region_id`.
- Removed regions (drop capitals, uncertain page numbers) leave `regions` with their lines and are recorded in
  `Transcription.extra["retyper_dropped"]` (id, labels, text, line ids, reason, confidence).
- A drop capital's letter is prepended to the target line's text (`line.extra["drop_capital"]`); words are not
  touched.
- Regions are re-ranked and lines re-ordered afterwards.

## Documents (`linecaster.document`)

- **Page composition** (`ComposePage`): `docling` from regions, lines and tables; page headers and footers always
  in Docling's furniture layer. Exports choose whether to include them (`furniture=True`).
- **Binding** (`BindItem`, `DocumentBuilder`): an item's pages bound into one DoclingDocument whose page `n` is the item's
  `n`-th page (by sequence, then page id). In reflow mode paragraphs continue across page breaks; sections are
  optional; `region_of` (item ref → `"<page_no>:<region id>"`) travels with the document for Markdown
  dividers. A task must see whole items; the run layout buckets page rows by item.
