# The data model

`linecaster.data` holds what is read from a page and how it is rendered; `linecaster.data.page` the page record it
travels in. A stored page record names its format in its row's `schema`: `linecaster.page/3`. Importing
`linecaster.data` needs neither datatrove nor saturate nor an engine.

## Principles

1. **Raw output is kept.** What a model answered (a completion, an engine's native result) is stored verbatim, once
   per request, next to what linecaster parsed from it (`RawOutput`).
2. **Nothing is discarded or overwritten.** Every step adds annotations; a normalization, a correction, a removal,
   a relabelling is a new annotation that refers to the one it is about. A page record holds everything any step
   said, and who said it.
3. **Rendering is a recorded, overridable policy.** Which annotations end up in which text (body, page furniture,
   notes, metadata, nowhere) is decided by a rendering policy at rendering time, never by a parser or a step. The
   policy is a catalog entry with an edition; run records and evidence name it.
4. **Definitions generic, vocabularies specific.** The classes hold any input (a scanned book, a manuscript, a
   born-digital PDF, a newspaper issue); what a region is, how it was made and what a range is are words from
   vocabularies borrowed from the standards (PAGE-XML, docling-core), extended where they lack a word.
5. **Records are lean.** Shared things are stored once per page and referred to by number (annotators, raw
   outputs); geometry is numbers; parts are nested where they never move (words in readings, glyphs in words);
   renderings (Docling documents, texts) are written out, not stored; defaults are not written.

The concepts are borrowed from IIIF Presentation 3 and the W3C Web Annotation model (annotations with a target, a
motivation and a body), PAGE-XML (region types, production), PROV (derivation) and docling-core (tables, content
layers, group labels, formatting, picture classes), under linecaster's names; the mappings are below
([mappings](#mappings)). Exports conform to each standard.

## Units

| Class | Is | Key |
|---|---|---|
| `Item` | a named, ordered container of one or more pages | `item_id` |
| `Page` | one page of an item: its image and its annotation sets | `page_id` |
| `PageImage` | the image a page's coordinates refer to: its location, size, format and hashes | |
| `DocumentRange` | a unit of continuous content within or across items (a work, an article, a letter); see [ranges](#ranges) | `id` |
| `Text` | one rendering of an item (or of a document range) as text: per variant, under a policy | `item_id`, `variant` |

**An item** is what the input names: it gives the item's id (`item_id`) and its pages' order (`sequence`).
linecaster assumes nothing about what an item is or how its pages came about: a scanned book, an issue, a PDF, a
folder of images. `page_id` is `<item_id>_<sequence:04d>` unless the source has stable page ids of its own; a page
id never contains `#`.

| `Page` field | Holds |
|---|---|
| `page_id`, `item_id`, `sequence` | the page's ids and its place in the item |
| `image` | its `PageImage` |
| `transcriptions` | name → `Transcription`: `ocr_new` (linecaster's), `ocr_original` (the library's own), `ground_truth`, `<source>` |
| `annotations` | name → `AnnotationSet`: sets without text (a layout of its own, an evaluation's markings) |
| `metadata` | the source's page metadata, namespaced keys (`<ns>__<field>`) |
| `measurements` | the page's time in the runs that worked on it: `seconds`, `datetime` (below) |

`PageImage` is unchanged from `linecaster.page/2`: `uri`, `format`, `width`, `height`, `sha256` (of the stored
bytes), `pixels_sha256` (of the decoded pixels), `source_width`, `source_height` and `scale` (for a derivative of a
master), `decoder`, `extra`.

### A page in a pipeline

A page is one datatrove `Document`: `id` is the page id, `text` the primary transcription's text
(`Transcription.text`, under the default policy), `media[0]` the image bytes, `metadata["page"]` the page record.

**A page's time in the run** is on its record, `Page.measurements`: `seconds`, the wall time from when the reader
handed the page over to when it reached the first block that writes pages, binds or serves (the blocks' times
between, waiting in served windows and queues included), and `datetime`, when the reader handed it over (ISO 8601,
UTC). `linecaster.runtime.observers.PageTiming` sets them on every page stage that writes pages; a record read from
an earlier run adds the new run's time to the one it carries and keeps the first `datetime`. Each annotator's own
time is in its `measurements`.

## Annotation sets

An **annotation set** (`AnnotationSet`) is everything one source said about one page: the annotators that worked on
it, their raw outputs, and their annotations. A **transcription** (`Transcription`, a subclass) is an annotation set
that also holds text: readings, tables, formulas, paragraphs, edits. A page has any number of each, by name.

| Field | Holds | In |
|---|---|---|
| `source` | where the set comes from (`Source`, below) | both |
| `annotators` | who worked on it, in the order they ran (`Annotator`) | both |
| `outputs` | their raw outputs, one per request (`RawOutput`) | both |
| `regions` | `Region`s: the layout's zones | both |
| `ranges` | `Range`s, `DocumentRange`s and `Paragraph`s: the logical units, their pieces on this page | both |
| `classifications` | `Classification`s: role, production, the annotator's own label, heading level, language, status, ... | both |
| `descriptions` | `Description`s: what an annotator wrote about a zone that is not on the page | both |
| `links` | `Link`s: cross-references (caption of, note of) | both |
| `orders` | `ReadingOrder`s: one per annotator that ordered the page | both |
| `lines` | `Line`s: the line zones, each with its `Reading` | `Transcription` |
| `tables` | `Table`s: a region's table structure | `Transcription` |
| `formulas` | `Formula`s: a region's formula | `Transcription` |
| `edits` | `Edit`s: NFC, normalized, corrected, joined forms of a reading, a word, a cell or a paragraph | `Transcription` |

Derived, not stored: `text` (the set rendered under a policy), `confidence` (reading confidences weighted by
length), `objects` (regions in the shape of a Hugging Face `objects` column).

**One of each per target and set**: a line has at most one reading, a region at most one table and one formula in a
set. A second recognizer of the same lines writes a transcription of its own; a second classifier of the same scheme
adds a classification next to the first, and the policy's `precedence` says whose counts.

### `Source`

| Field | Holds |
|---|---|
| `kind` | `produced` (made by linecaster's annotators), `converted` (read from a delivered file), `ground_truth` (a reference transcription, made or checked by people) |
| `format` | for converted sets and ground truth: `alto`, `page`, `hocr`, `docling`, `text`, `markdown`, or an evaluation's own name |
| `uri`, `sha256` | the delivered file and its hash |
| `dataset`, `record` | for ground truth and converted sets from a dataset: `repo@revision`, and the row or file the set was read from |
| `image_sha256`, `image_width`, `image_height` | the image the set's coordinates refer to |
| `scale` | the factors (`[sx, sy]`) a set was scaled by onto this image (`AnnotationSet.scaled`) |

## Annotators and raw output

An **annotator** (`Annotator`) is one thing that worked on a set: a model step, a rule-based step, a delivered file,
or people. Annotations name it by its index in `annotators`.

| Field | Holds |
|---|---|
| `kind` | `model`, `rule`, `file`, `human` |
| `step` | the catalog step: `layout`, `lines`, `recognition`, `tables`, `formulas`, `unicode`, `typography`, `recomposition`, `normalization`, `assignment`, `ordering`, ...; for a file or people: `transcription` |
| `name` | the model (`kraken-ppocrv6-medium`); for a rule, what ran (`unicodedata`, the engine's id); for people, the group (`proofreaders`) |
| `engine`, `revision` | the engine's code id, the model's revision |
| `preset`, `preset_sha256`, `recipe`, `recipe_sha256` | the preset and recipe editions it ran as, and their hashes |
| `backend` | in-process, or served with the server's address |
| `run` | the run that produced the annotator's work (its run id, `RunRecord.run_id`); `None` for files and people |
| `settings` | what decided the output besides the preset: the engine's options, a VLM's prompt and sampling; for people, their review: `review` (`transcribed`, `proofread`, `validated`, or the source's own word) |
| `measurements` | numbers of this page, in the measurements vocabulary (below) |

A **raw output** (`RawOutput`) is one request's answer, verbatim:

| Field | Holds |
|---|---|
| `annotator` | its annotator |
| `content` | the completion as the model wrote it, or an engine's native result (JSON) |
| `format` | `text`, `json`, or the engine's own name |
| `pass_` | which pass of the page it is (1, 2 after a [repair pass](glossary.md)); stored as `pass` |
| `kept` | whether the annotations were parsed from it (a repair pass keeps one) |
| `settings` | what this request was sent with when it differs from the annotator's: `max_tokens`, `temperature`, `top_p`, `preset` |
| `image_size` | the size of the image sent, when it is not the page image's |
| `finish_reason`, `prompt_tokens`, `completion_tokens` | as the server reported them |
| `error` | the request's error, when it failed |

Engines that answer in-process with Python objects (a detector's boxes) store no raw output: their annotations are
the output, and their raw form is not kept beyond them.

### Measurements

`linecaster.data.MEASUREMENTS` is the vocabulary of `Annotator.measurements` and `Page.measurements`, key →
meaning; linecaster code writes no other key. Values vary from run to run.

| Key | Meaning |
|---|---|
| `seconds` | wall time of the step on the page (the engine's call, in-process or in the server); on the page record, the page's time in the run |
| `datetime` | when the step started on the page, ISO 8601 in UTC; on the page record, when its reader handed it over |
| `device` | the device the step ran on |
| `request_seconds` | a served step: from its request being built to its (last) answer |
| `queue_seconds`, `decode_seconds` | a step served by `linecaster serve`: the wait in the server's queue, the decoding of the page image |
| `decoder` | what decoded the page image the step read (`linecaster.images.pixels`) |
| `prompt_tokens`, `completion_tokens` | a VLM's tokens, summed over the page's requests (each request's are on its raw output) |
| `finish_reason` | the kept request's: `stop`, `length`, `repetition`, `content_filter`, `tool_calls`, `function_call`, `abort` (`FINISH_REASONS`), or `None` |
| `regions`, `failed` | regions sent to a VLM one by one, and those whose request failed |
| `tables`, `formulas` | table regions given a structure, formula regions read |
| `changed` | strings a normalization changed |
| `body_size`, `leveled`, `demoted`, `split`, `drop_capitals`, `numbers_dropped` | typography: the body type size in pixels, headings given a level, section headers classified as text, headlines split off, drop capitals joined, page numbers classified removed |
| `paragraphs`, `continuations`, `marks_removed`, `marks_kept` | recomposition: paragraphs made, continued, division marks removed, hyphens kept |

## Annotations

Every annotation has an annotator and may name the raw output it was parsed from, what it was derived from, and a
confidence:

| `Annotation` field | Holds |
|---|---|
| `annotator` | the index of its annotator in the set |
| `output` | the index of the raw output it was parsed from, if any |
| `derived_from` | [references](#references) to what it was made from (PROV's `wasDerivedFrom`): a paragraph's lines, an edit's source, a classification's evidence |
| `confidence` | the annotator's confidence, 0 to 1, if it gave one |
| `<ns>__<field>` | extension fields, namespaced: an adapter's or a step's own (`lighton__continuation`, `typography__reason`), never shared vocabulary |

| Class | Motivation | Target | Is |
|---|---|---|---|
| `Region` | segmenting | the page | a zone found by a layout step |
| `Line` | segmenting | the page | a zone found by a line step |
| `Reading` | transcribing | its line | a line's text, with words and glyphs |
| `Table` | transcribing | a region | a region's table structure |
| `Formula` | transcribing | a region | a region's formula, as LaTeX |
| `Classification` | classifying | a zone, a range, a reading span, the page | one value of one scheme |
| `Description` | describing | a zone | text about the zone that is not on the page |
| `Edit` | editing | a reading, a word, a cell, a paragraph, a span | another form of the target's text |
| `Link` | linking | two references | a cross-reference |
| `ReadingOrder` | ordering | the page | an order of the page's regions and lines |
| `Range`, `DocumentRange`, `Paragraph` | structuring | zones, spans, ranges | a logical unit: its piece on this page |

The motivation is the class's, not a stored field. IIIF exports `transcribing` as `supplementing` (IIIF's word for
a transcription), the others as W3C Web Annotation motivations (`classifying`, `describing`, `editing`, `linking`)
or linecaster's own (`segmenting`, `ordering`, `structuring`).

### Zones

A **zone** (`Zone`) is a place on the page image an annotator found; `Region` and `Line` are zones. Geometry without
an annotator of its own (a word, a glyph, a cell) is a **shape** (`Shape`).

| Field | Holds | In |
|---|---|---|
| `box` | `[x, y, width, height]` in pixels of the page image, or `None` (no geometry: a text-only answer, a ground truth without boxes) | `Shape` |
| `polygon` | `[[x, y], ...]` as the annotator gave it, or `None` | `Shape` |
| `id` | unique within the page and set (`r3`, `l17`); never contains `#`, `/` or `[` | `Zone` |
| `parent` | the zone it lies in (a running head's title and page number inside the running head) | `Zone` |
| `label` | the annotator's own label (PP-DocLayout's `aside_text`, LightOn's `page_number`), verbatim | `Region` |
| `region` | the region the line belongs to: set once, by the step that assigned it | `Line` |
| `baseline` | `[[x, y], ...]` | `Line` |
| `reading` | the line's `Reading`, `None` until a recognizer ran | `Line` |

Lines are found across the whole page and assigned to regions later; zones are therefore flat lists with stable ids,
and a line names its region, set once by the step that assigned it. A later step that moves a line into another
region (typography splitting a headline off) adds a `part_of` link; the line's region is the latest `part_of`
target, else `Line.region` (`Transcription.region_of`). A line's `confidence` is its detection score; its
reading's is the recognizer's.

### Readings, words and glyphs

A **reading** (`Reading`) is what a recognizer read on one line: `text` (exactly as the engine produced it, `""` for
a line read as empty), `alternatives`, `words`, `formatting`, and its own annotator, raw output and confidence.
A `Word` (`Shape`) has `text`, `confidence`, `hyphen` (it ends in a division mark), `alternatives`, `formatting`
and `glyphs`, and an `id` only where its source gave one other than `<line>_w<n>`; a `Glyph` (`Shape`) `text` and `confidence`. Engines with character positions keep them as glyphs.

`Formatting` is docling-core's: `bold`, `italic`, `underline`, `strikethrough`, `script` (`baseline`, `sub`,
`super`); on a word, it covers the word; on a reading, each `Formatting` has a `charspan` (`[start, end]` in the
reading's text).

### Tables and formulas

A `Table` transcribes a region (`target`) as docling-core's table model, stored lean: `num_rows`, `num_cols`,
`cells`, and `html` when the model wrote the table as HTML. A `Cell` (`Shape`) has docling-core's `TableCell`
fields: `start_row`, `end_row`, `start_col`, `end_col` (docling-core's `*_offset_idx`, end exclusive), `text`,
`column_header`, `row_header`, `row_section`. Spans and the grid are not stored (they follow from the offsets);
`linecaster.formats.docling.table_data` and `from_table_data` convert to and from docling-core's `TableData`
losslessly. A chart's data, when a model gives it, is a `Table` too, on the chart's region.

A `Formula` transcribes a region as `latex`.

### Classifications

A `Classification` gives one `target` one `value` in one `scheme`. Several annotators may classify the same target
in the same scheme (the layout model and the typography rules); none overwrites another.

| Scheme | Values | Typical annotator |
|---|---|---|
| `role` | what the content is ([content roles](#content-roles)) | layout, typography, a grounding VLM, a ground truth |
| `production` | how it was made: `printed`, `typewritten`, `handwritten`, `stamped`, `born_digital` | layout, a ground truth |
| `heading_level` | `1`, `2`, ... (docling-core's `SectionHeaderItem.level`) | typography |
| `language` | a BCP 47 tag, on the page (`""`), a zone or a span | recognition, a ground truth |
| `script` | an ISO 15924 code | recognition |
| `status` | `illegible`, `gap` (text left out), `suppressed`, `duplicate`, `removed` | a ground truth, typography |
| `picture_class` | docling-core's `PictureClassificationLabel` (`photograph`, `map`, `stamp`, `signature`, `music`, ...) | a picture classifier |
| `code_language` | docling-core's `CodeLanguageLabel` | a VLM |

The annotator's own label is the region's `label`, not a classification; the mapping from it to a role is catalog
data per engine (each engine's label map), applied by the annotator that made the region.

### Descriptions

A `Description` is text an annotator wrote about a zone that is not printed on the page (a VLM's description of a
figure, chart data it read off, an editor's note): `target`, `kind` (`description`, `data`, `note`), `text`, `format` (`text`, `markdown`, `html`).
docling-core's `DescriptionMetaField`.

### Edits

An `Edit` is another form of a target's text; the target's own text stays. `target` (a reading, a word, a cell, a
paragraph, a span of one), `kind`, `text`:

| `kind` | Is |
|---|---|
| `nfc` | the text in Unicode NFC (the `unicode` step); only when it differs |
| `normalized` | the text normalized (`CharacterNormalizer`: ſ, ligatures, r rotunda ...) |
| `corrected` | an editor's correction of what is printed (a misprint); the reading keeps the printed form |
| `joined` | a word divided across lines or pages, joined: on its first half, `derived_from` naming the other half |
| `expanded`, `regularized` | abbreviations expanded, spelling regularized (the text dimensions' later steps) |

Edits chain: an edit may target another edit's result through `derived_from`; a renderer takes, per target, the
last edit of the kinds the text variant asks for.

### Links

A `Link` is a cross-reference: `kind`, `source`, `target`. Kinds: `caption_of`, `note_of` (a footnote and its mark,
`source` the note, `target` the mark's span), `continues` (`source` continues `target`: a paragraph or footnote
from an earlier column or page), `runs_into` (`source` runs on into `target`), `refers_to`, `part_of` (a line in
another region than the one it was assigned to).

### Reading orders

A `ReadingOrder` orders the page: `regions` (region ids in reading order), `lines` (line ids in reading order) and
`rows` (parallel to `lines`: each line's visual row within its region). An order of regions alone leaves `lines`
empty. A layout model that learned an order, the line assigner, typography, XY-Cut++ and a ground truth each add
their own; the latest counts unless the policy's `precedence` says otherwise.

**Processing order** is separate: the list order of `lines` (regions in the layout step's order, orphan rows last,
rows within each region), in which a recognizer processes and batches lines.

### Ranges

A **range** (`Range`) is a logical unit of content: a document, a chapter, a section, an article, a list, a
paragraph. A page stores only the **piece** of a range that lies on it, under the range's `id`; pieces with the same
id on other pages of the item are the same range, and the item record joins them in page order. Paragraphs are the
exception: their ids are page-local, and a paragraph continued in the next column or on the next page is two
paragraphs joined by links (`runs_into`, `continues`).

| Field | Holds |
|---|---|
| `id` | unique within the item (paragraphs: within the page, `<region id>_p<n>`); never contains `#`, `/` or `[` |
| `kind` | docling-core's `GroupLabel` (`chapter`, `section`, `list`, `ordered_list`, `inline`, `picture_area`, `form_area`, `key_value_area`, `comment_section`, `sheet`, `slide`) plus `document`, `article`, `work`, `paragraph`, `poem`, `stanza` |
| `parent` | the range it is part of |
| `parts` | the zones, spans and ranges of this piece, in order |
| `title` | the range's title, if known |

A **document range** (`DocumentRange`, `kind` `document`) is a document within or across items: an item holds one
document unless ranges say otherwise. A **paragraph** (`Paragraph`, `kind` `paragraph`) is the bottom range that
carries running text: `text` (as written, flowed: the rows joined, the division marks the recomposition removed
gone), `rows` (`ParagraphRow`: `lines`, the ids of every line on the visual row, empty ones too, and `charspan`, the
row's part of `text`), and `decisions` (`Decision`: `kind`, `reason`, `row`, `separator`; the vocabulary
`DECISIONS`). A paragraph's `continuation` decision's `separator` joins its text to the paragraph it runs on into.

| Decision `kind` | Reasons |
|---|---|
| `mark_removed` | `letter_follows` |
| `hyphen_kept` | `capital_follows`, `digit_follows`, `no_letter_follows`, `script_change`, `attested` |
| `paragraph_break` | `indent`, `gap`, `short_row` |
| `continuation` | `division_mark`, `end_margin` |

### References

A reference (`Ref`) names something in the same set:

| Form | Names |
|---|---|
| `<id>` | a zone or a range piece on this page |
| `<line>/<n>`, `<line>/<n>/<m>` | word `n` of the line's reading, glyph `m` of that word |
| `<region>/r<row>c<col>` | the cell of the region's table that starts at that row and column |
| `<ref>[<start>:<end>]` | characters `start` to `end` (end exclusive) of the text the reference names |
| `""` | the page |
| `<page_id>#<ref>` | something on another page of the item |

## Content roles

The `role` scheme's vocabulary, the **content roles**, is PAGE-XML's region types, with docling-core's labels where PAGE has no word:

| Role | PAGE-XML | docling-core label | Default layer |
|---|---|---|---|
| `paragraph` | `paragraph` | `text` | body |
| `heading` | `heading` | `section_header` | body |
| `title` | (`heading`) | `title` | body |
| `caption` | `caption` | `caption` | body |
| `list_item` | (`paragraph`) | `list_item` | body |
| `list_label` | `list-label` | (the list item's `marker`) | body |
| `toc_entry` | `TOC-entry` | `document_index` | body |
| `footnote` | `footnote` | `footnote` | body |
| `footnote_continued` | `footnote-continued` | `footnote` | body |
| `endnote` | `endnote` | `footnote` | body |
| `marginalia` | `marginalia` | `text` (`aside_text` before) | body |
| `drop_capital` | `drop-capital` | (joined to its word) | body |
| `credit` | `credit` | `text` | body |
| `floating` | `floating` | `text` | body |
| `reference` | (`paragraph`) | `reference` | body |
| `code` | (`other`) | `code` | body |
| `table` | `TableRegion` | `table` | body |
| `formula` | `MathsRegion` | `formula` | body |
| `chemistry` | `ChemRegion` | `formula` | body |
| `music` | `MusicRegion` | `picture` | body |
| `picture` | `ImageRegion`, `GraphicRegion`, `LineDrawingRegion` | `picture` | body |
| `chart` | `ChartRegion` | `chart` | body |
| `map` | `MapRegion` | `picture` | body |
| `advert` | `AdvertRegion` | `picture` | body |
| `form` | (`other`) | `form` | body |
| `key_value` | (`other`) | `key_value_region` | body |
| `header` | `header` | `page_header` | furniture |
| `footer` | `footer` | `page_footer` | furniture |
| `page_number` | `page-number` | `page_header`, `page_footer` | furniture |
| `catch_word` | `catch-word` | `page_footer` | furniture |
| `signature_mark` | `signature-mark` | `page_footer` | furniture |
| `separator` | `SeparatorRegion` | `picture` | none |
| `noise` | `NoiseRegion` | `picture` | none |
| `other` | `other` | `text` | body |

A content role says what the content is, not where it is rendered: the layers in the last column are the default
policy's. A page number's Docling label depends on where it is: `page_header` when its centre lies in the top 15 %
of the page (or without a box), else `page_footer`. A label that is neither a role nor a Docling label (a model's own) is kept as
its own role and written as it is.

## Rendering

A **rendering policy** (`RenderingPolicy`, a catalog entry `policy` with editions, like a preset) decides which
annotations go into which **layer** of a rendering. The layers are docling-core's `ContentLayer` (`body`,
`furniture`, `background`, `invisible`, `notes`), plus `metadata` (kept out of the text, written to the rendering's
metadata) and `none`.

| `RenderingPolicy` field | Holds |
|---|---|
| `id`, `edition` | as a preset's |
| `rules` | `RenderingRule`s, the first that matches wins: `role`, `production`, `status`, `motivation` (each `None`: any) → `to` (a layer, `metadata` or `none`) |
| `precedence` | whose annotations count where several annotators gave one of a kind: an ordered list of steps or annotator names, per scheme (`role: [typography, layout]`), for reading orders (`order: [layout, ordering]`) and ranges |
| `edits` | which edits a text variant applies, by variant (`readable_txt: [nfc, joined, normalized]`) |

The default policy, `page-layers@1`, gives every role its default layer, `status` `suppressed`, `duplicate` and
`removed` → `none`, descriptions → `metadata`; without `precedence` the latest annotator's classifications count
(typography's over the layout's). Its `verbatim_txt` applies `nfc` and `joined` (a drop capital joined to its line),
the readable variants also `normalized`. A run names its
policy (`--policy`); without one it uses the default, and the run record says which.

Renderings are made from a set under a policy and are not stored: the Docling document (`linecaster.formats.docling`,
one item per paragraph or region, the layer as the item's `content_layer`, roles as Docling labels), DocLang, ALTO,
PAGE-XML, hOCR, the IIIF annotation page, and the texts.

### Text variants (`linecaster.text.variants`)

Three variants per item, each a choice of layers and edits from the policy:

| Variant | Layers | Edits | Flow |
|---|---|---|---|
| `verbatim_txt` | body, furniture | `nfc`, `joined` | as laid out: each page's readings in reading order, tables as Markdown or HTML, pages joined with a form feed |
| `readable_txt` | body | `nfc`, `joined`, `normalized` | flowed: the item's paragraphs, a paragraph's pieces joined with their separator, tables one row per line with tab-separated cells, a formula's LaTeX |
| `readable_md` | body | as `readable_txt` | the same as Markdown: `#` title, `##` heading (by heading level), `- ` list item, tables as pipe tables (HTML when a cell spans) |

The vocabulary is era-neutral, on three dimensions: character fidelity (as written → normalized → expanded →
regularized), flow (as laid out → flowed) and scope (full page → body only). All text is NFC; the normalization folds
ſ, ligatures, r rotunda and superscript e over a, o, u by an explicit mapping table, and keeps æ, œ, ø, å and ß;
never NFKC; spelling is never modernized.

## Steps and what they add

| Step | Adds |
|---|---|
| layout | regions, `role` and `production` classifications (by the engine's label map), a reading order if the model learned one |
| lines | lines (geometry only) |
| assignment | each line's `region` |
| recognition | readings (words, glyphs, formatting), raw outputs; `language`, `script` classifications |
| tables, formulas | tables, formulas |
| unicode | `nfc` edits |
| typography | `role` and `heading_level` classifications (a demoted heading is classified `paragraph` again, by typography), `status` `removed` for what it drops, a `joined` edit for a drop capital joined to its line, a split-off headline as a region with `parent` and `part_of` links, a new reading order |
| ordering | a reading order (XY-cut, XY-Cut++) |
| recomposition | paragraphs and their `runs_into` and `continues` links |
| normalization | `normalized` edits |
| a VLM page step | regions, lines with readings, tables, formulas, descriptions, classifications, raw outputs |
| a ground-truth import | everything its source has, `source.kind` `ground_truth`, an annotator of kind `human` or `file` |

Composition (the `Composer`) adds nothing: it renders the set as a Docling document, which travels with the
datatrove document (`doc.metadata["docling"]`) to the writers and is not stored in the page record.

**Nothing is overwritten**: an engine call appends one annotator and adds annotations; it changes none that was there
(setting a line's `region` or `reading` from `None` aside). The conformance checks (`linecaster.testing.check_engine`,
`check_block`) check it.

## Geometry

Every `box` is `[x, y, width, height]` in pixels of the page image; polygons and baselines are lists of `[x, y]`
points exactly as the annotator gave them. Algorithms derive boxes from the polygon (`geometry.bbox_of`). `AnnotationSet.scaled(sx,
sy)` moves every coordinate to another image size and records the factors in `source.scale`.

## Item records (`linecaster.blocks.base.item`)

An item travels as one datatrove `Document`: `id` is the item id, `metadata["item"]` the item record, `{"item_id":
..., "pages": [...]}`, its page records (as JSON-compatible dicts) in order (sequence, then page id), without the
image bytes. The `Binder` makes it from a page stream; the item-unit blocks add to the page records inside it
(`Recomposer(unit="item")`: paragraphs whose pieces span pages; `CharacterNormalizer(unit="item")`: edits); the
renderers join a range's pieces across pages; the `Splitter` passes the pages on again, each with what the
item-level blocks added.

## Mappings

| linecaster | IIIF Presentation 3 / W3C Web Annotation | PAGE-XML | PROV | docling-core |
|---|---|---|---|---|
| `Item` | Manifest | (a METS file group) | Entity | (a document's origin) |
| `Page` | Canvas | `Page` | Entity | `PageItem` |
| `AnnotationSet`, `Transcription` | AnnotationPage | `PcGts` | Collection | `DoclingDocument` (rendered) |
| `Annotator` | `creator` / `generator` (Software, Person) | `Metadata/MetadataItem` | Agent, Activity | `created_by` |
| `RawOutput` | (none; a linecaster extension) | (none) | Entity, `wasGeneratedBy` | (none) |
| `Annotation` | Annotation | (an element) | Entity | `DocItem` |
| `derived_from` | (extension) | (none) | `wasDerivedFrom` | `ProvenanceItem` |
| `Zone.box`, `polygon` | `FragmentSelector` `xywh=`, `SvgSelector` | `Coords` | | `BoundingBox` (`l, t, r, b`) |
| `Region` + `role` | Annotation, motivation `classifying` | `TextRegion@type`, other regions | | `DocItemLabel` |
| `Line`, `Reading` | Annotation, motivation `supplementing`, `textGranularity` `line` | `TextLine`, `TextEquiv` | | `TextItem.orig` |
| `Word`, `Glyph` | `textGranularity` `word`, `glyph` | `Word`, `Glyph` | | |
| `Edit` | motivation `editing` | `TextEquiv@index` | `wasRevisionOf` | `TextItem.text` (the edited form) |
| `Classification` | motivation `classifying` | `@type`, `@production`, `TextStyle` | | `label`, `level`, `meta` |
| `Description` | motivation `describing` | (none) | | `DescriptionMetaField` |
| `Link` | motivation `linking` | `Relations` | | (`captions`, `footnotes` refs) |
| `ReadingOrder` | Range of canvases' annotations | `ReadingOrder` | | the body's order |
| `Range`, `DocumentRange` | Range | (none) | | `GroupItem` (`GroupLabel`) |
| `Paragraph` | Annotation, `textGranularity` `paragraph` | (`TextRegion` of type paragraph) | | `TextItem` with provenance per row |
| `Table`, `Cell` | (body as HTML) | `TableRegion`, `TableCell` | | `TableData`, `TableCell` |
| `RenderingPolicy` layers | (none) | (none) | | `ContentLayer` |

The IIIF export (`linecaster.formats.iiif.to_annotation_page`) writes one AnnotationPage per set and page: regions
(`classifying`, the content role as the body), readings and words (`supplementing`, IIIF's motivation for a
transcription, with the text granularity extension's `textGranularity`), edits (`editing`) and descriptions
(`describing`), each targeting the canvas with a media fragment (`#xywh=`), with its annotator as `generator`
(`creator` for people). It is validated against the IIIF Presentation 3 JSON Schema in the tests.

## From `linecaster.page/2`

`PageRecordReader` upgrades a page/2 record when it reads one (`linecaster.data.upgrade.page_2_to_3`). What page/2
had already lost cannot come back: text before the `unicode` step, labels before typography, regions typography
dropped beyond `extra["retyper_dropped"]`. Every field:

| page/2 | page/3 |
|---|---|
| `Page.page_id`, `item_id`, `sequence`, `image`, `metadata`, `measurements` | the same |
| `Page.transcriptions` | the same, each upgraded |
| `PageImage.uri`, `format`, `width`, `height`, `sha256`, `pixels_sha256`, `source_width`, `source_height`, `scale`, `decoder`, `extra` | the same |
| `Transcription.regions` | `regions` |
| `Region.id` | `Region.id` |
| `Region.label` | a `role` classification (Docling label → role), by the layout annotator; by typography where its step changed it |
| `Region.raw_label` | `Region.label` |
| `Region.polygon` | `Region.polygon`, flattened |
| `Region.bbox` | `Region.box` |
| `Region.score` | `Region.confidence` |
| `Region.reading_order` | the layout annotator's `ReadingOrder` |
| `Region.heading_level` | a `heading_level` classification |
| `Region.extra["table"]` | a `Table` |
| `Region.extra["formula"]` | a `Formula` |
| `Region.extra["generated"]` | a `Description` |
| `Region.extra` (other keys) | extension fields `page2__<key>` |
| `Transcription.lines` | `lines` |
| `Line.id` | `Line.id` |
| `Line.region_id` | `Line.region` |
| `Line.reading_order`, `Line.row` | the `ReadingOrder`'s `lines` and `rows` |
| `Line.bbox`, `polygon`, `baseline` | `Line.box`, `polygon`, `baseline` (flattened) |
| `Line.score` | `Line.confidence` |
| `Line.text`, `confidence`, `alternatives`, `words` | `Line.reading`: `text`, `confidence`, `alternatives`, `words` |
| `Line.normalized` | a `normalized` edit |
| `Line.extra` | extension fields `page2__<key>` |
| `Word.id` | `None` where it was `<line>_w<n>` (its index in the reading); kept otherwise |
| `Word.text`, `confidence`, `hyphen`, `alternatives` | the same |
| `Word.bbox` | `Word.box` |
| `Word.extra` | extension fields `page2__<key>` |
| `Transcription.paragraphs` | `Paragraph` ranges |
| `Paragraph.id`, `region_id` | `Paragraph.id`, `parts` |
| `Paragraph.rows` | `rows` |
| `ParagraphRow.lines` | the same |
| `ParagraphRow.start`, `end` | `ParagraphRow.charspan` |
| `Paragraph.text`, `decisions` | the same |
| `Paragraph.normalized` | a `normalized` edit |
| `Paragraph.continues`, `continues_from` | `runs_into` and `continues` links |
| `ParagraphRef.id`, `page_id` | the links' target: `<id>` or `<page_id>#<id>` |
| `Decision.kind`, `reason`, `row`, `separator` | the same |
| `Paragraph.extra` | extension fields `page2__<key>` |
| `Transcription.docling` | not stored: rendered on demand |
| `Transcription.language` | a `language` classification on the page |
| `Transcription.steps` | `annotators` |
| `StepInfo.step`, `name`, `engine`, `revision`, `preset`, `preset_sha256`, `recipe`, `recipe_sha256`, `backend`, `settings`, `measurements` | the same `Annotator` fields; `kind` from the step |
| `Transcription.source` | `source` |
| `Source.kind`, `format`, `uri`, `image_sha256`, `image_width`, `image_height` | the same |
| `Source.extra["scale"]` | `Source.scale` |
| `Source.extra` (other keys) | extension fields `page2__<key>` |
| `Transcription.extra["raw"]`, `["passes"]`, `["kept"]`, `["finish_reason"]` | `outputs` |
| `Transcription.extra["retyper_dropped"]` | the regions again, with one line holding their text, classified `status` `removed` by typography |
| `Transcription.extra` (other keys) | extension fields `page2__<key>` |
