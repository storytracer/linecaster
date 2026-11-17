# The data model

`linecaster.data` holds what is read from a page and how it is rendered; `linecaster.data.page` the page record it
travels in. A stored page record names its format in its row's `schema`: `linecaster.page/6`. Importing
`linecaster.data` needs neither datatrove nor saturate nor an engine.

## Principles

1. **Raw output is kept.** What a model answered (a completion, an engine's native result) is stored verbatim, once
   per request, next to what linecaster parsed from it (`RawOutput`).
2. **Nothing is discarded or overwritten.** Every step adds annotations; a correction, a removal, a relabelling is a
   new annotation that refers to the one it is about. A page record holds everything any step said, and who said it.
3. **The record holds the text as read.** A reading is what the model or the source gave, exactly, not even in NFC.
   No step changes it or stores a derived form of it: a normalization (NFC, the long s, ligatures, a division mark
   removed, rows joined) is applied when a text is written, by the transcription strategy the text names
   (`linecaster.document.strategy`), and never by default. Edits are the source's own (an editor's correction, a
   word the source marks as divided).
4. **Rendering is a recorded, overridable policy.** Which annotations end up in which text (body, page furniture,
   notes, metadata, nowhere) is decided by a rendering policy at rendering time, never by a parser or a step. The
   policy is a catalog entry; run records and evidence name it with its hash.
5. **Definitions generic, vocabularies specific.** The classes hold any input (a scanned book, a manuscript, a
   born-digital PDF, a newspaper issue); what a region is, how it was made and what a range is are words from
   vocabularies borrowed from the standards (PAGE-XML first), extended where they lack a word.
6. **Records are lean.** Shared things are stored once per page and referred to by number (annotators, raw
   outputs); geometry is numbers; parts are nested where they never move (words in readings, glyphs in words);
   renderings (documents, texts) are written out, not stored; defaults are not written.

The concepts are borrowed from IIIF Presentation 3 and the W3C Web Annotation model (annotations with a target, a
motivation and a body), PAGE-XML (region types, production) and PROV (derivation), under linecaster's names; the
mappings are below ([mappings](#mappings)). Exports conform to each standard.

## Units

| Class | Is | Key |
|---|---|---|
| `Item` | a named, ordered container of one or more pages | `item_id` |
| `Page` | one page of an item: its image and its annotation sets | `page_id` |
| `PageImage` | the image a page's coordinates refer to: its location, size, format and hashes | |
| `DocumentRange` | a unit of continuous content within or across items (a work, an article, a letter); see [ranges](#ranges) | `id` |

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
handed the page over to when it reached the first component that writes pages, binds or serves (the components' times
between, waiting in served windows and queues included), and `datetime`, when the reader handed it over (ISO 8601,
UTC). `linecaster.core.observers.PageTiming` sets them on every page stage that writes pages; a record read from
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
| `edits` | `Edit`s: the source's corrected, expanded, regularized or joined forms of a reading, a word, a cell or a span | `Transcription` |

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
| `revision` | the revision of the source text that the zones' anchors refer to (a wiki page's revision id, a commit) |
| `image_sha256`, `image_width`, `image_height` | the image the set's coordinates refer to |
| `scale` | the factors (`[sx, sy]`) a set was scaled by onto this image (`AnnotationSet.scaled`) |
| `normalized` | for a ground truth: the normalizations its transcription already embodies (catalog ids, from its conventions' `transcription`: `long-s` where it writes ſ as s); scoring warns where a lane does not apply one |

## Annotators and raw output

An **annotator** (`Annotator`) is one thing that worked on a set: a model step, a rule-based step, a delivered file,
or people. Annotations name it by its index in `annotators`.

| Field | Holds |
|---|---|
| `kind` | `model`, `rule`, `file`, `human` |
| `step` | the catalog step: `layout`, `lines`, `recognition`, `tables`, `formulas`, `hierarchy`, `paragraphs`, `assignment`, `ordering`, `import`, ...; for a file or people: `transcription` |
| `name` | the model (`kraken-ppocrv6-medium`); for a rule, what ran (`unicodedata`, the engine's id); for people, the group (`proofreaders`) |
| `engine`, `revision` | the engine's code id, the model's revision |
| `preset`, `preset_sha256`, `recipe`, `recipe_sha256` | the preset and recipe it ran as, and their hashes |
| `conventions`, `conventions_sha256` | an importer's: the conventions it applied, resolved (the chain, `mediawiki>enwikisource`), and the hash of what their rules do |
| `linecaster` | the linecaster that added the annotator (`producer()`: version and commit) |
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
| `body_size`, `leveled`, `demoted`, `split`, `drop_capitals`, `numbers_dropped` | the hierarchy step: the body type size in pixels, headings given a level, section headers classified as text, headlines split off, drop capitals joined, page numbers classified removed |
| `paragraphs`, `continuations`, `marks_removed`, `marks_kept` | the paragraphs step: paragraphs made, continued, division marks removed, hyphens kept |

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
| `anchor` | where its text comes from in the source text it was read from: `{start, end}`, characters of the source at `Source.revision`; set by importers, `None` for zones found on the image | `Zone` |
| `label` | the annotator's own label (PP-DocLayout's `aside_text`, LightOn's `page_number`), verbatim | `Region` |
| `region` | the region the line belongs to: set once, by the step that assigned it | `Line` |
| `baseline` | `[[x, y], ...]` | `Line` |
| `reading` | the line's `Reading`, `None` until a recognizer ran | `Line` |

Lines are found across the whole page and assigned to regions later; zones are therefore flat lists with stable ids,
and a line names its region, set once by the step that assigned it. A later step that moves a line into another
region (the hierarchy step splitting a headline off) adds a `part_of` link; the line's region is the latest `part_of`
target, else `Line.region` (`Transcription.region_of`). A line's `confidence` is its detection score; its
reading's is the recognizer's.

### Readings, words and glyphs

A **reading** (`Reading`) is what a recognizer read on one line: `text` (exactly as the engine produced it, `""` for
a line read as empty), `alternatives`, `words`, `formatting`, and its own annotator, raw output and confidence.
A `Word` (`Shape`) has `text`, `confidence`, `hyphen` (it ends in a division mark), `alternatives`, `formatting`
and `glyphs`, and an `id` only where its source gave one other than `<line>_w<n>`; a `Glyph` (`Shape`) `text` and `confidence`. Engines with character positions keep them as glyphs.

`Formatting` says how characters are set: `bold`, `italic`, `underline`, `strikethrough`, `script` (`baseline`,
`sub`, `super`); on a word, it covers the word; on a reading, each `Formatting` has a `charspan` (`[start, end]` in the
reading's text).

### Tables and formulas

A `Table` transcribes a region (`target`), stored lean: `num_rows`, `num_cols`, `cells`, and `html` when the model
wrote the table as HTML. A `Cell` (`Shape`) has `start_row`, `end_row`, `start_col`, `end_col` (offsets, end
exclusive), `text`, `column_header`, `row_header`, `row_section`. Spans and the grid are not stored (they follow
from the offsets). A chart's data, when a model gives it, is a `Table` too, on the chart's region.

A `Formula` transcribes a region as `latex`; `source` is the LaTeX as the source wrote it, where the reading's
differs (a wiki's formula as its software normalizes it).

### Classifications

A `Classification` gives one `target` one `value` in one `scheme`. Several annotators may classify the same target
in the same scheme (the layout model and the hierarchy rules); none overwrites another.

| Scheme | Values | Typical annotator |
|---|---|---|
| `role` | what the content is ([content roles](#content-roles)) | layout, hierarchy, a grounding VLM, a ground truth |
| `production` | how it was made: `printed`, `typewritten`, `handwritten`, `stamped`, `born_digital` | layout, a ground truth |
| `heading_level` | `1`, `2`, ... (1 the highest below the title) | hierarchy |
| `language` | a BCP 47 tag (well-formed), on the page (`""`), a zone, a word or a span | recognition, a ground truth, an importer |
| `script` | an ISO 15924 code (`Latn`, `Arab`, `Jpan`), on the page, a zone, a word or a span | a ground truth, an importer |
| `direction` | the writing direction: `horizontal-lr`, `horizontal-rl` (right to left), `vertical-rl` (columns, right to left: Chinese, Japanese, Korean set vertically), `vertical-lr` (columns, left to right: Mongolian) | a ground truth, an importer, a layout step |
| `status` | `illegible`, `gap` (text left out), `suppressed`, `duplicate`, `removed`; a status may say why (`reason`, below) | a ground truth, hierarchy, an importer |
| `picture_class` | what a picture shows (`photograph`, `map`, `stamp`, `signature`, `music`, ...) | a picture classifier |
| `code_language` | the programming language of a code region | a VLM |
| `degraded` | a property, `yes` or `no`: the content is harder to read than in a clean scan, because of the image's condition | a model tagger |
| `tiny` | a property, `yes` or `no`: the content is printed noticeably smaller than the page's body text | the geometry tagger, a model tagger |
| `rotated` | a property, `yes` or `no`: the content's text is turned or tilted by about 5 degrees or more | the geometry tagger, a model tagger |
| `multi_column` | a property, `yes` or `no`: the content sits inside one column of a page laid out in columns | the geometry tagger, a model tagger |
| `form` | a property, `yes` or `no`: the content is a field to fill in or a box to tick, or belongs to one | a model tagger |

The annotator's own label is the region's `label`, not a classification; the mapping from it to a role is catalog
data per engine (each engine's label map), applied by the annotator that made the region.

**Vocabularies.** What each value of a closed scheme means is its **vocabulary**, a catalog entry
(`vocabularies/<scheme>.yaml`, [catalog](catalog.md#vocabulary-vocabulariesschemeyaml)): every value with its
definition, what counts and what does not. The vocabularies of [`role`](../catalog/vocabularies/role.md),
[`status`](../catalog/vocabularies/status.md) (with the reasons), [`production`](../catalog/vocabularies/production.md)
and the property schemes list exactly the data model's values (`ROLES`, `STATUSES`, `REASONS`, `yes` and `no`), which
`linecaster catalog verify` checks. The definitions are the one text the docs, the taggers and the people who review
their answers share: a model tagger's questions are generated from them.

**Property schemes** (`linecaster.data.PROPERTIES`: [`degraded`](../catalog/vocabularies/degraded.md),
[`tiny`](../catalog/vocabularies/tiny.md), [`rotated`](../catalog/vocabularies/rotated.md),
[`multi_column`](../catalog/vocabularies/multi_column.md), [`form`](../catalog/vocabularies/form.md)) say what
content is like, as `yes` or `no` (`Transcription.classify` refuses another value); a vocabulary's `answers` name the
two answers a model is asked for after the property (`degraded`, `not_degraded`). They are a **tagger**'s, an engine
of the `tagging` step (`linecaster.engines.tagging`), on the narrowest target the property is true of (a line, a
region, the page), each with its evidence: the geometry tagger's measurements, or a panel of models' answers, as the
annotator's raw outputs, which the classification names (`output`). Where the evidence does not decide, nothing is
recorded: a property is never guessed into a record, and `None` (no classification) is not `no`.

**Writing systems.** `language`, `script` and `direction` are checked where they are made
(`linecaster.data.writing`: a well-formed BCP 47 tag, a four-letter ISO 15924 code, one of the four directions) and
read through what encloses a target: `Transcription.language(target)`, `.script(target)` and `.direction(target)`
take the value recorded on a span or word, else on its line, else on the line's region and the regions it lies in,
else on the page (`""`); `None` where nothing records one. A value is never guessed into a record: a source or a step
records it, and `linecaster.text.scripts` infers a text's script (`dominant_script`, with ISO 15924's `Jpan` and
`Kore` for the combinations) or direction (`first_strong_direction`, the Unicode bidirectional algorithm's paragraph
level) where a caller asks. What orders zones follows the direction (`linecaster.data.geometry.frames`: XY-cut,
XY-Cut++, the line assigner's rows, unordered regions slotted in, the paragraphs step's margins, drop capitals): boxes
are seen in the direction's frame, mirrored for `horizontal-rl` and turned for the vertical directions, so that
right-to-left text reads from the right and vertical text by columns, from the right for `vertical-rl` and from the
left for `vertical-lr`. The direction is a block's or engine's option where it has one, else the one recorded for
the region or page; without either, `horizontal-lr`.

A `status` classification's `reason` says why something present in a source is no text of the page
(`linecaster.data.REASONS`): `hidden` (not seen and taking no space), `invisible` (not seen but taking its space),
`generated` (the source's software or markup draws it), `editorial` (the source's editors wrote it), `error` (a
message of the source's software), `metadata` (markup that is no content), `apparatus` (the source's notation for
something the page prints differently), `elsewhere` (printed text that belongs to another page or place), `layout`
(markup that only arranges the page). An importer keeps such text, where its conventions say so, as a region with
status `removed` and its reason, which no rendering takes.

### Descriptions

A `Description` is text an annotator wrote about a zone that is not printed on the page (a VLM's description of a
figure, chart data it read off, an editor's note): `target`, `kind` (`description`, `data`, `note`), `text`, `format` (`text`, `markdown`, `html`).

### Edits

An `Edit` is another form of a target's text; the target's own text stays. `target` (a reading, a word, a cell, a
paragraph, a span of one), `kind`, `text`:

| `kind` | Is |
|---|---|
| `corrected` | an editor's correction of what is printed (a misprint); the reading keeps the printed form |
| `joined` | half of a word the source marks as divided across lines or pages (Wikisource's `{{hws}}`/`{{hwe}}`, ALTO's `SUBS_CONTENT`): the edit's target is the half's span, its text the whole word |
| `expanded`, `regularized` | abbreviations expanded, spelling regularized, as the source states them |

Every edit is the source's: linecaster's steps write none (since `linecaster.page/5`; the `nfc` and `normalized`
edits of page/4 are dropped when a record is read). A document carries them as spans of its literal text, and a
strategy applies them when it names them: `editors-corrections`, `editors-expansions`, `editors-regularizations`,
`divided-words` (the halves paired in reading order and written whole where the second stands).

### Links

A `Link` is a cross-reference: `kind`, `source`, `target`. Kinds: `caption_of`, `note_of` (a footnote and its mark,
`source` the note, `target` the mark's span), `continues` (`source` continues `target`: a paragraph or footnote
from an earlier column or page), `runs_into` (`source` runs on into `target`), `refers_to`, `part_of` (a line in
another region than the one it was assigned to; a drop capital's region, part of the line it begins: a document
writes its letter at that line's start).

### Reading orders

A `ReadingOrder` orders the page: `regions` (region ids in reading order), `lines` (line ids in reading order) and
`rows` (parallel to `lines`: each line's visual row within its region). An order of regions alone leaves `lines`
empty. A layout model that learned an order, the line assigner, the hierarchy step, XY-Cut++ and a ground truth each add
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
| `kind` | `chapter`, `section`, `list`, `ordered_list`, `inline`, `picture_area`, `form_area`, `key_value_area`, `comment_section`, `sheet`, `slide`, `document`, `article`, `work`, `paragraph`, `poem`, `stanza` |
| `parent` | the range it is part of |
| `parts` | the zones, spans and ranges of this piece, in order |
| `title` | the range's title, if known |

A **document range** (`DocumentRange`, `kind` `document`) is a document within or across items: an item holds one
document unless ranges say otherwise. A **paragraph** (`Paragraph`, `kind` `paragraph`) is the bottom range of
running text: structure only, no text of its own (since `linecaster.page/5`): `rows` (`ParagraphRow`: `lines`, the
ids of every line on the visual row, empty ones too) and `decisions` (`Decision`: `kind`, `reason`, `row`; the
vocabulary `DECISIONS`). Its text is its lines' readings, row by row; a strategy writes it (`flow` joins the rows).

| Decision `kind` | Reasons |
|---|---|
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

The `role` scheme's vocabulary, the **content roles**, is PAGE-XML's region types, with names of linecaster's own
where PAGE has no word. Each role has a **region label**, the coarser word layout models and page files use (a layout
preset maps its model's labels onto them), and a default layer:

| Role | PAGE-XML | Region label | Default layer |
|---|---|---|---|
| `paragraph` | `paragraph` | `text` | body |
| `heading` | `heading` | `section_header` | body |
| `title` | (`heading`) | `title` | body |
| `caption` | `caption` | `caption` | body |
| `list_item` | (`paragraph`) | `list_item` | body |
| `list_label` | `list-label` | `list_item` | body |
| `toc_entry` | `TOC-entry` | `document_index` | body |
| `footnote` | `footnote` | `footnote` | body |
| `footnote_continued` | `footnote-continued` | `footnote` | body |
| `endnote` | `endnote` | `footnote` | body |
| `marginalia` | `marginalia` | `text` | body |
| `drop_capital` | `drop-capital` | `text` | body |
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

Each role's definition, what counts as it and what does not, is in the [role vocabulary](../catalog/vocabularies/role.md).
A content role says what the content is, not where it is rendered: the layers in the last column are the default
policy's. A page number's region label depends on where it is: `page_header` when its centre lies in the top 15 %
of the page (or without a box), else `page_footer`. A label that is neither a role nor a region label (a model's own)
is kept as its own role and written as it is.

## Rendering

A **rendering policy** (`RenderingPolicy`, a catalog entry `policy`) decides which
annotations go into which **layer** of a rendering: `body`, `furniture` (running heads and feet, page numbers),
`background`, `invisible`, `notes`, plus `metadata` (kept out of the text, written to the rendering's metadata) and
`none`.

| `RenderingPolicy` field | Holds |
|---|---|
| `id` | as a preset's |
| `rules` | `RenderingRule`s, the first that matches wins: `role`, `production`, `status`, `motivation` (each `None`: any) → `to` (a layer, `metadata` or `none`) |
| `precedence` | whose annotations count where several annotators gave one of a kind: an ordered list of steps or annotator names, per scheme (`role: [hierarchy, layout]`), for reading orders (`order: [layout, ordering]`) and ranges |
| `tables`, `markdown` | what counts as a table when written out (`TableRules`); the Markdown a rendering writes (`MarkdownRules`) |

The default policy, `page-layers`, gives every role its default layer, `status` `suppressed`, `duplicate` and
`removed` → `none`, descriptions → `metadata`; without `precedence` the latest annotator's classifications count
(the hierarchy step's over the layout's). `page-layers-described` puts descriptions (`motivation` `describing`) in the
`body` instead: the texts, the elements and the document then have each one after its region (a picture without lines
in its place in the reading order; the page's last), a document as a `paragraph` block with the role `description`
(`RenderingPolicy.described`). A policy decides layers, never text. A run names its policy (`--policy`); without one
it uses the default, and the run record says which.

Renderings are made from a set under a policy and are not stored: the document (below), ALTO, PAGE-XML, hOCR, the
IIIF annotation page, and the texts.

### The document (`linecaster.document`)

A page's or an item's **document** (`Document`, `linecaster.document/2`) is what a reader reads, in reading order:
its pages and its **blocks**. A block (`Block`) is one unit of the rendering, of a `kind` made from its region's
content role: `title`, `heading` (with its `level`), `paragraph`, `list_item`, `caption`, `footnote`, `toc_entry`,
`reference`, `code`, `page_header`, `page_footer`, `formula` (its LaTeX the text), `table` (its `grid`: size and
cells) or `picture` (its `file` and the text read inside it). Each block has its content `role`, the `layer` the
policy put it in, its `text` (literal: the readings as read, rows separated by `\n`; `wraps`: the positions of the
`\n` that are breaks of the layout, which `flow` joins) with formatting, languages, inline formulas and the source's
edits over `spans` of it (an edit span: `edit`, `edit_text`; a span's `language` and `direction` where they are
not its block's), its `language` and `direction` where they are not the document's, the `section` it is in (the heading block that opens it, with sections), and an `Origin` per piece:
the page, the region and lines it comes from, its box on the page image (clamped to the page; none without geometry)
and the characters of the block's text it gives. The document's `language` and `direction` are its pages' where
every page records the same one; like a block's, they are only what the transcriptions record
(`Transcription.language`, `.direction`), never inferred, and absent from the JSON where nothing records one.

`DocumentBuilder` makes it ([the document step](#steps-and-what-they-add)), literal (`strategy: literal`): one block per
region as laid out (one row per visual row: lines share a row when the order says so and their boxes overlap), or
per paragraph where the paragraphs step ran (every break between its rows a wrap); a paragraph or region that continues another
(its `continues` link, on the same or an earlier page of the item) is one block with it, on a new row (a wrap, unless
a part has several rows and the first does not end in a division mark: verse). A drop capital (`part_of` its line) is
written at its line's start. `linecaster.document.strategy.apply(document, strategy)` writes a strategy's document
from it (`strategy` names it); `linecaster.document` writes either as HTML (HTML5 with DPUB-ARIA roles for notes and
page furniture), Markdown (by the policy's Markdown rules: a wrap a plain newline, another row break a hard break, a
row that would start a Markdown block escaped), text and JSON; the JSON is the complete document and reads back
(`from_json`; a document/1 file is read as it is, its strategy not stated).

### Texts and transcription strategies

A **text** is a document written by a **transcription strategy** in a format: `<strategy>:<format>`
(`literal:txt`, `latin-historic+unicode-marks+flow:md`). `literal` changes nothing; a strategy of the catalog
(`linecaster.catalog`: normalizations and strategies) applies its normalizations in order: rules on characters
(`linecaster.normalization.rules`: `nfc`, `long-s`, `ligatures`, `r-rotunda`, `superscript-e`, ...) to every block's text
and cell, and rules on the document: the source's edits, `divided-words`, `unicode-marks` (division marks resolved
by squiddleocr's rule, the document's words as the lexicon), `flow` (the wraps joined: by a space, or none where
Unicode's line breaking joins the words; a row that still ends in a division mark joined without a space, the mark
kept). Spans, wraps and origins move with the text they cover. Nothing is written unless a run names it: by default
the document as JSON, literal. The scope (full page or body only) is the layer choice when it is written
(`furniture`).

## Steps and what they add

| Step | Adds |
|---|---|
| layout | regions, `role` and `production` classifications (by the engine's label map), a reading order if the model learned one |
| lines | lines (geometry only) |
| assignment | each line's `region` |
| recognition | readings (words, glyphs, formatting), raw outputs; `language`, `script` classifications |
| tables, formulas | tables, formulas |
| hierarchy | `role` and `heading_level` classifications (a demoted heading is classified `paragraph` again), `status` `removed` for what it drops, a `part_of` link from a drop capital's region to the line it begins, a split-off headline as a region with `parent` and `part_of` links, a new reading order |
| ordering | a reading order (XY-cut, XY-Cut++) |
| tagging | classifications in property schemes (and other closed schemes), each naming the raw output that holds its evidence: the geometry tagger's measurements, or every panel member's answer |
| paragraphs | paragraphs (rows and decisions, no text) and their `runs_into` and `continues` links |
| a VLM page step | regions, lines with readings, tables, formulas, descriptions, classifications, raw outputs |
| a ground-truth import | everything its source has, `source.kind` `ground_truth`, an annotator of kind `human` or `file` |

Composition (the `DocumentComposer`) adds nothing: it renders the set as a document (`linecaster.document`), which travels
with the datatrove document (`doc.metadata["document"]`) to the writers and is not stored in the page record.

**Nothing is overwritten**: an engine call appends one annotator and adds annotations; it changes none that was there
(setting a line's `region` or `reading` from `None` aside). The conformance checks (`linecaster.testing.check_engine`,
`check_component`) check it.

## Geometry

Every `box` is `[x, y, width, height]` in pixels of the page image; polygons and baselines are lists of `[x, y]`
points exactly as the annotator gave them. Algorithms derive boxes from the polygon (`geometry.bbox_of`). `AnnotationSet.scaled(sx,
sy)` moves every coordinate to another image size and records the factors in `source.scale`.

## Item records (`linecaster.core.item`)

An item travels as one datatrove `Document`: `id` is the item id, `metadata["item"]` the item record, `{"item_id":
..., "pages": [...]}`, its page records (as JSON-compatible dicts) in order (sequence, then page id), without the
image bytes. The `ItemAssembler` makes it from a page stream; the item-unit blocks add to the page records inside it
(`ParagraphBuilder(unit="item")`: paragraphs whose pieces span pages), and `DocumentComposer(unit="item")` adds the item's
document next to it; the renderers join a range's pieces across pages; the `ItemSplitter` passes the pages on again, each with what the
item-level blocks added.

## Mappings

| linecaster | IIIF Presentation 3 / W3C Web Annotation | PAGE-XML | PROV |
|---|---|---|---|
| `Item` | Manifest | (a METS file group) | Entity |
| `Page` | Canvas | `Page` | Entity |
| `AnnotationSet`, `Transcription` | AnnotationPage | `PcGts` | Collection |
| `Annotator` | `creator` / `generator` (Software, Person) | `Metadata/MetadataItem` | Agent, Activity |
| `RawOutput` | (none; a linecaster extension) | (none) | Entity, `wasGeneratedBy` |
| `Annotation` | Annotation | (an element) | Entity |
| `derived_from` | (extension) | (none) | `wasDerivedFrom` |
| `Zone.box`, `polygon` | `FragmentSelector` `xywh=`, `SvgSelector` | `Coords` | |
| `Region` + `role` | Annotation, motivation `classifying` | `TextRegion@type`, other regions | |
| `Line`, `Reading` | Annotation, motivation `supplementing`, `textGranularity` `line` | `TextLine`, `TextEquiv` | |
| `Word`, `Glyph` | `textGranularity` `word`, `glyph` | `Word`, `Glyph` | |
| `Edit` | motivation `editing` | `TextEquiv@index` | `wasRevisionOf` |
| `Classification` | motivation `classifying` | `@type`, `@production`, `TextStyle` | |
| `Description` | motivation `describing` | (none) | |
| `Link` | motivation `linking` | `Relations` | |
| `ReadingOrder` | Range of canvases' annotations | `ReadingOrder` | |
| `Range`, `DocumentRange` | Range | (none) | |
| `Paragraph` | Annotation, `textGranularity` `paragraph` | (`TextRegion` of type paragraph) | |
| `Table`, `Cell` | (body as HTML) | `TableRegion`, `TableCell` | |

The IIIF export (`linecaster.formats.iiif.to_annotation_page`) writes one AnnotationPage per set and page: regions
(`classifying`, the content role as the body), readings and words (`supplementing`, IIIF's motivation for a
transcription, with the text granularity extension's `textGranularity`), edits (`editing`) and descriptions
(`describing`), each targeting the canvas with a media fragment (`#xywh=`), with its annotator as `generator`
(`creator` for people). It is validated against the IIIF Presentation 3 JSON Schema in the tests.

## From `linecaster.page/2`

`PageRecordReader` upgrades a page/2 record when it reads one (`linecaster.data.upgrade.page_2_to_3`). What page/2
had already lost cannot come back: text before the `unicode` step, labels before the hierarchy step, regions that step
dropped beyond `extra["retyper_dropped"]`. Every field:

| page/2 | page/3 |
|---|---|
| `Page.page_id`, `item_id`, `sequence`, `image`, `metadata`, `measurements` | the same |
| `Page.transcriptions` | the same, each upgraded |
| `PageImage.uri`, `format`, `width`, `height`, `sha256`, `pixels_sha256`, `source_width`, `source_height`, `scale`, `decoder`, `extra` | the same |
| `Transcription.regions` | `regions` |
| `Region.id` | `Region.id` |
| `Region.label` | a `role` classification (region label → role), by the layout annotator; by the hierarchy step where it changed it |
| `Region.raw_label` | `Region.label` |
| `Region.polygon` | `Region.polygon` |
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
| `Line.bbox`, `polygon`, `baseline` | `Line.box`, `polygon`, `baseline` |
| `Line.score` | `Line.confidence` |
| `Line.text`, `confidence`, `alternatives`, `words` | `Line.reading`: `text`, `confidence`, `alternatives`, `words` |
| `Line.normalized` | dropped (page/5 stores no derived text) |
| `Line.extra` | extension fields `page2__<key>` |
| `Word.id` | `None` where it was `<line>_w<n>` (its index in the reading); kept otherwise |
| `Word.text`, `confidence`, `hyphen`, `alternatives` | the same |
| `Word.bbox` | `Word.box` |
| `Word.extra` | extension fields `page2__<key>` |
| `Transcription.paragraphs` | `Paragraph` ranges |
| `Paragraph.id`, `region_id` | `Paragraph.id`, `parts` |
| `Paragraph.rows` | `rows` |
| `ParagraphRow.lines` | the same |
| `ParagraphRow.start`, `end` | dropped (page/5) |
| `Paragraph.text`, `decisions` | `decisions` (page/5: no text, no mark decisions) |
| `Paragraph.normalized` | dropped (page/5) |
| `Paragraph.continues`, `continues_from` | `runs_into` and `continues` links |
| `ParagraphRef.id`, `page_id` | the links' target: `<id>` or `<page_id>#<id>` |
| `Decision.kind`, `reason`, `row`, `separator` | `kind`, `reason`, `row` (page/5) |
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
| `Transcription.extra["retyper_dropped"]` | the regions again, with one line holding their text, classified `status` `removed` by the hierarchy step |
| `Transcription.extra` (other keys) | extension fields `page2__<key>` |

## From `linecaster.page/4`

A page/4 record is upgraded when it is read (`linecaster.data.upgrade.page_4_to_5`), and so is every older one,
through page/4: the derived text goes, the source's stays. Dropped: the `nfc` and `normalized` edits, `Paragraph.text`,
`ParagraphRow.charspan`, the decisions on division marks (`mark_removed`, `hyphen_kept`) and `Decision.separator`. A
drop capital's whole-line `joined` edit (the hierarchy step's) becomes a `part_of` link from its region to the line, and the
`removed` status the hierarchy step gave the region goes. The source's edits (`corrected`, `expanded`, `regularized`, a
divided word's halves) stay as they were.
