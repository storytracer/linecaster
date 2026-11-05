# The data model

`linecaster.data` holds what a page's text recognition produces; `linecaster.data.page` the page record it
travels in. Importing either needs neither datatrove nor saturate nor an engine.

## Classes

| Class | Is | Key |
|---|---|---|
| `Item` | any multi-page unit: book, issue, manuscript, file | `item_id` |
| `Page` | one page record: the page image and its named transcriptions | `page_id` = `item_id` + sequence |
| `PageImage` | the image's location, size, format and hashes | |
| `Transcription` | OCR, HTR or ground truth of one page | |
| `Text` | one text per item and variant (`linecaster.text.variants`) | |

## A page in a pipeline

A page is one datatrove `Document`: `id` is the page id, `text` the primary transcription's text, `media[0]`
the image bytes, `metadata["page"]` the page record.

## `Transcription`

| Part | Holds |
|---|---|
| `regions` | the layout: id, `label` (a DoclingDocument label), `raw_label` (the producer's), polygon, bbox, score, `reading_order`, `heading_level`, `extra` |
| `lines` | id, `region_id`, `reading_order`, `row`, bbox, polygon, baseline, score, `text`, `normalized`, confidence, alternatives, `words`, `extra` |
| `paragraphs` | the running text recomposed from the rows (`Paragraph`, below), in reading order |
| `docling` | the page's composed DoclingDocument, as docling-core dumps it |
| `language` | |
| `steps` | one `StepInfo` per step that worked on it, in order (below) |
| `source` | `kind` (`produced`, `converted`, `ground_truth`), `format`, `uri`, image size |
| derived | `text` (as written, as laid out, full page; tables as Markdown), `confidence` (line confidences weighted by length) |

- **`regions` are the contract between steps.** Lines and recognizers need the layout (label, polygon,
  reading order, score) long before a DoclingDocument can be built, so regions are a primary part next to
  `lines`; `docling` is composed from regions, lines and tables. Region ids are the producer's own
  (PP-DocLayout: `<raw label>_<index>`; rows outside every region: `orphan_<n>`); lines refer to them with
  `region_id`.
- **Words are the finest level**; there is no glyph level. Engines with character positions turn them into
  words by the engine's own rule (kraken: split at whitespace, a word's box the bounding box of its cuts).
- **A line's `text` is `None` until a recognizer ran**; an empty string is a line recognized as empty. Its
  `normalized` is `None` until the `CharacterNormalizer` ran; `text` is never overwritten.
- **Text-only transcriptions** (a delivered plain text) are lines without geometry (`bbox` and `polygon`
  `None`), one per text line, `source.kind = "converted"`, `source.format = "text"`. They cannot be written as
  ALTO, PAGE or hOCR.

## Steps (`StepInfo`)

Every step that worked on a transcription adds one `StepInfo`, model steps and rule-based steps alike:

| Field | Holds |
|---|---|
| `step` | the step: `layout`, `lines`, `recognition`, `tables`, `formulas`, `unicode`, `typography`, `recomposition`, `normalization`, `composition`, ... |
| `name` | the model (`kraken-ppocrv6-medium`, `PP-DocLayoutV3`); for a step without a model, what ran (`unicodedata`, `retyper`, the engine's id) |
| `engine` | the engine's code id (`kraken.recognition.v1`, `typography.ratios.v1`); `None` for a step no engine ran (`unicode`) |
| `revision` | the model's revision |
| `preset`, `preset_sha256` | the preset edition it ran as, and its hash |
| `recipe`, `recipe_sha256` | the recipe edition the run followed, and its hash (`RecipeStamper`) |
| `backend` | in-process, or served with the server's address |
| `settings` | what decided the output besides the preset: the engine's options, a VLM's prompt and sampling |
| `measurements` | numbers of this page, in the measurements vocabulary (below) |

The model blocks and `linecaster serve` fill `engine` from the engine's `engine_id`, `preset` from the backend, and
`seconds` and `datetime`. The page files (ALTO, PAGE, hOCR) carry every field but `measurements` (`datetime` aside)
and read them back ([serialization](serialization.md)).

### Measurements

`linecaster.data.MEASUREMENTS` is the vocabulary of `StepInfo.measurements`, key → meaning; linecaster code writes
no other key (a test reads the code for every place that writes one). Values vary from run to run.

| Key | Meaning |
|---|---|
| `seconds` | wall time of the step on the page (the engine's call, in-process or in the server) |
| `datetime` | when the step started on the page, ISO 8601 in UTC |
| `device` | the device the step ran on |
| `prompt_tokens`, `completion_tokens` | a VLM's tokens, summed over the page's requests |
| `finish_reason` | why generation stopped: `stop`, `length`, `content_filter`, `tool_calls`, `function_call`, `abort` (`FINISH_REASONS`), or `None` |
| `regions`, `failed` | regions sent to a VLM one by one, and those whose request failed |
| `tables`, `formulas` | table regions given a structure, formula regions read |
| `changed` | strings a normalization changed |
| `body_size`, `leveled`, `demoted`, `split`, `drop_capitals`, `numbers_dropped` | typography: the body type size in pixels, headings given a level, section headers made text, headlines split off, drop capitals joined, page numbers removed |
| `paragraphs`, `continuations`, `marks_removed`, `marks_kept` | recomposition: paragraphs made, paragraphs continued into the next region or page, division marks removed, hyphens kept |

A new key is added to the vocabulary before code writes it. Page records of other producers are read with whatever
keys they carry (`unknown_measurements` lists them).

## Paragraphs (`Paragraph`)

Running text recomposed from the rows of one region (the `Recomposer`), with the decisions that made it.

| Field | Holds |
|---|---|
| `id`, `region_id` | `<region id>_p<n>`, and the region |
| `rows` | one `ParagraphRow` per visual row with text: `lines` (the ids of every line on the row, as `Line.row` groups them, empty ones too) and `start`, `end` (the row's characters in `text`) |
| `text` | as written, flowed: the rows joined, the division marks the recomposition removed gone |
| `normalized` | the same text normalized (the `CharacterNormalizer`), else `None` |
| `continues`, `continues_from` | the paragraph it runs on into, and the one it continues (`ParagraphRef`: `id`, and `page_id` for a paragraph on another page of the item) |
| `decisions` | `Decision`s: `kind` and `reason` (`DECISIONS`), `row` (the index into `rows`), `separator` (for a continuation: what joins it to the paragraph it runs on into) |

The rows are what a document's provenance needs: an item made from a paragraph has one provenance entry per row,
whose box is the union of the row's lines' boxes (derived from their polygons, `geometry.bbox_of`) and whose
`charspan` is `start`, `end`, shifted by the text before it when the item continues a paragraph of an earlier region
or page. Rows without text belong to no paragraph; text-only transcriptions have rows without boxes.

| Decision `kind` | Reasons |
|---|---|
| `mark_removed` | `letter_follows`: the next row starts with a lowercase or caseless letter |
| `hyphen_kept` | `capital_follows`, `digit_follows`, `no_letter_follows`, `script_change` (a mark after a Hebrew letter before a row in another script), `attested` (the document has the hyphenated form and not the joined one) |
| `paragraph_break` | `indent`, `gap` (about a blank line), `short_row` (justified text: the row before stopped short of the end margin) |
| `continuation` | `division_mark`, `end_margin` (the last row reaches the end margin), without sentence-final punctuation |

## Geometry

Every `bbox` is `[x, y, width, height]` in pixels of the received image. Polygons and baselines are float
lists exactly as the engine returned them. Algorithms derive boxes from the polygon (`geometry.bbox_of`), so
their arithmetic matches the engine's (no `x + width` rounding). `Transcription.scaled(sx, sy)` moves every
coordinate to another image size.

## Order

- **Processing order** is the list order of `Transcription.lines` after the line steps: regions in the layout
  step's order, orphan rows last, rows within each region. A recognizer processes and batches lines in this
  order.
- **Reading order** is separate: `reading_order` ranks the lines on the page (regions by their reading order,
  then rows); `row` is the visual row within a region.

## Unicode

The as-written layer is NFC, made by a step of its own: `UnicodeNormalizer` (`linecaster.text.unicode`) right after
recognition, recorded as `StepInfo(step="unicode", name="unicodedata", settings={"form": "NFC", "unicode_version":
...})`. Each
engine's raw output stays exactly what the engine produced. Only canonical forms (NFC, NFD) are allowed; never
NFKC, whose folding is the readable variants' job (`linecaster.text.variants`).

## Typography (`linecaster.text.typography`)

The retyper edits regions and lines in place:

- A split-off headline is region `<region id>_head` (raw label `<raw>/split`); its lines keep their ids and get
  the new `region_id`.
- Removed regions (drop capitals, uncertain page numbers) leave `regions` with their lines and are recorded in
  `Transcription.extra["retyper_dropped"]` (id, labels, text, line ids, reason, confidence).
- A drop capital's letter is prepended to the target line's text (`line.extra["drop_capital"]`); words are not
  touched.
- Regions are re-ranked and lines re-ordered afterwards.

## Documents (`linecaster.formats.docling`)

- **Page composition** (`Composer`): `docling` from regions, lines and tables; page headers and footers always
  in Docling's furniture layer. Exports choose whether to include them (`furniture=True`).
- **Binding** (`BindItem`, `DocumentBuilder`): an item's pages bound into one DoclingDocument whose page `n` is the item's
  `n`-th page (by sequence, then page id). In `reflow` mode paragraphs continue across page breaks; sections are
  optional; `region_of` (item ref → `"<page_no>:<region id>"`) travels with the document for Markdown
  dividers. A task must see whole items; the run layout buckets page records by item.
