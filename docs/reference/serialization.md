# Serialization and working images

`linecaster.formats.{alto,pagexml,hocr}` write and read the three XML formats on lxml,
`linecaster.formats.iiif` writes an annotation set as an IIIF annotation page and reads one, `linecaster.document`
writes a page's or an item's document as HTML, Markdown, text and JSON, `linecaster.formats.docling` reads a
DoclingDocument (the `docling` extra), `linecaster.formats.tei` a page of a TEI P5 document and
`linecaster.formats.text` plain text (a line per line, or the text of a line image); `linecaster.images.convert`
turns any page image into the working image. None of them imports datatrove, saturate or an engine. Each writer
renders an annotation set under a [rendering policy](data-model.md#rendering); what it writes is a rendering, not
stored in the page record.

The importers (`linecaster.engines.importers`, step `import`) read these formats into transcriptions. A source
document's `context` may state the page's writing system, as a line-level dataset's columns do (`language`, a BCP
47 tag; `script`, an ISO 15924 code; `direction`): each becomes the page's classification by the importer where the
file records none of its own. `text-import` with the option `line_image` reads the text of an image of one line: the
page is that line, its box the whole image (`import_transcriptions --read-images` gives the importer the image's
size).

## Common rules for ALTO, PAGE and hOCR

1. **Native first, extension for the rest.** Every value goes into the format's own vocabulary
   where it has a place. What it cannot hold, or what a reader would infer differently, goes into a
   small JSON *extension* on the element: ALTO `OtherTag[@TYPE="linecaster"]/@DESCRIPTION`
   referenced by `TAGREFS`; PAGE `UserDefined/UserAttribute[@name="linecaster"]/@value`; hOCR
   `@data-linecaster`. Writers compute what their own reader would infer and only write the
   extension when it differs, so ordinary pages carry few (ALTO: line confidences and scores;
   PAGE: usually only `{"polygon": null}` for box-only lines). `extensions=False` writes pure
   files; they then round-trip only what the format holds natively. Foreign files have no
   extensions and readers fall back to the inferred values.
2. **What is written** (`linecaster.formats._xml.file_layout`): of the transcription `t`, under the policy
   `policy` (`to_alto`, `to_page`, `to_hocr`; default `page-layers`, `linecaster.data.DEFAULT_POLICY`):
   - **regions**: id, polygon and box, detection confidence (the region's *score*), the annotator's own label
     (`Region.label`, the **raw label**) and the region's **region label**, from its content role (`t.label`;
     `handwritten_text` for running text classified as handwritten), and its heading level (its `heading_level`
     classification, unless a later annotator classified its role anew);
   - **lines**: id, region (`t.region_of`: the latest `part_of` link, else `Line.region`), box, polygon, baseline,
     detection confidence (the line's *score*) and its reading: the literal text (`t.text_of`: the reading's text,
     exactly as read), confidence, alternatives, and the words with their ids,
     text, box, confidence, alternatives and `hyphen` flag, and a word the source marks as half of a divided word
     (a `joined` edit covering exactly the line's last or first word) as ALTO's `SUBS_TYPE` (`HypPart1`,
     `HypPart2`) and `SUBS_CONTENT` (the whole word), which the ALTO reader reads back as those edits; a line not
     read has no reading;
   - **the reading order** that counts (`t.order`): each region's rank in it, each line's rank on the page and row
     in its region;
   - **languages, scripts and directions** as recorded (`t.language`, `t.script`, `t.direction`: a target's own
     classification, else its line's, its region's or the page's; never an inferred one): the page's, and a
     region's, line's or word's where it differs from the level that encloses it in the file (a word's line, a
     line's region, else the page), so a value the page records is written once.

   Regions the policy puts in layer `none` (a `status` of removed, suppressed or duplicate under `page-layers`;
   the roles separator and noise) are left out with their lines, and so are lines whose own `status` the policy puts
   there (a line assignment's duplicates); ranks are counted among what is written. **Not serialized**: the other
   classifications (production apart from handwritten running text, status, picture class, code language; spans'
   languages and directions), edits (`corrected`, `expanded`, `regularized`; ALTO's divided words apart),
   descriptions, links, ranges and paragraphs, tables and formulas, raw outputs, glyphs and formatting, annotations'
   `annotator`, `output`, `derived_from` and extension fields, annotators of kind `file` and `human`, annotators'
   `measurements` other than `datetime`, and the source.
3. **Reading** (`linecaster.formats._xml.transcription`): a reader makes one transcription of the file: its
   regions (the raw label as `Region.label`, a `role` classification of the region label they read as,
   `linecaster.data.policy.classify_label`, and a `heading_level` one), its lines with their readings, and one
   reading order (the regions with a rank, the lines by rank, with their rows). A language, script or direction the
   file states becomes a classification (by the annotator that made the readings) of the narrowest target it holds
   for, the page, a region, a line or a word (`<line>/<n>`), where it differs from the enclosing level's: a value an
   element inherits from one the reader does not keep (hOCR's `ocr_par`, a nested PAGE region, a synthetic block)
   is recorded on what lies in it. A language as BCP 47 with the ISO 639-1 code for a three-letter one (`eng`, `deu`
   and `ger` read as `en`, `de`; `linecaster.formats._languages.canonical`); a value that is no language, script or
   direction is not recorded. A content role comes back as the role of its region label: roles that share one
   (marginalia, credit, floating and drop capitals read as paragraphs; endnotes and continued footnotes as footnotes;
   a page number as a header or footer) come back as that label's role. The **annotators** are the steps the file
   names (provenance, below); without any, the file is the one annotator (kind `file`, step `transcription`, named
   after its format). What each annotator made: regions by
   the latest layout step (else recognition, else lines), roles and heading levels by the latest typography step
   (else layout, else recognition), lines by the line step (else recognition, else layout), readings by recognition
   (else lines), the reading order by the latest of typography, assignment, ordering, lines, layout and recognition,
   and by the first annotator where none of these ran. The **source** is `kind="converted"`, `format`, `uri` and
   the image size, with ALTO's scale factors (`scale`) and the extension fields `alto__namespace` (the file's
   namespace), `alto__measurement_unit` (when not `pixel`), `alto__other_languages` (`OTHERLANGS`),
   `page__namespace`, and PAGE's page-level extension fields (below). **`ground_truth=True`** (every
   reader) makes the source a ground truth (`kind="ground_truth"`) and the file's own annotator people (kind
   `human`); steps the file names stay what they are. Readers return regions and lines in document order, which
   may differ from the original list order; tests compare by id.

   **Provenance** round-trips: every annotator of kind `model` or `rule`, as a step record (step, name, engine,
   revision, preset, preset hash, recipe, recipe hash, backend, settings; `datetime` as ALTO `processingDateTime`
   and PAGE `MetadataItem/@date`), is written as ALTO `Processing`, PAGE `MetadataItem type="processingStep"` with
   `Labels`, and hOCR `linecaster-step-<n>` metas next to `ocr-system` and `ocr-capabilities` (computed from what
   the file contains); readers turn each back into an annotator, of kind `rule` for the rule-based steps
   (`RULE_STEPS`), else `model`. Annotators of kind `file` and `human` are the set's source, not steps, and are not
   written. Other tools' provenance is read too (ALTO `Processing` and `OCRProcessing`: the description as the step,
   the software's name and version as model and revision, other settings as `raw`; OCR-D PAGE steps: `name` as the
   step, `value` as the model, their parameters as settings; hOCR `ocr-system`: one recognition step). METS agents
   per step: `linecaster.runtime.provenance.mets_agents`.
4. **Writing order.** Regions are written by their rank in the reading order (regions it leaves out after the
   others, in list order), each region's lines by rank. A line without a region goes before
   the first region whose first line comes after it; consecutive ones share one block. Readers
   rank the lines by their position in document order and give each the row of its position in its block, and rank
   the regions by the format's reading order; the writers record the original rank or row in the extension
   whenever that differs (gaps, a running head read last, a region outside the order), so irregular orders survive
   too.
5. **Lines without a region.** ALTO and PAGE need a block around every line: they get a synthetic
   `TextBlock`/`TextRegion` (`id` `lc_block_<n>`, extension `{"synthetic": true}`) that the reader
   drops again (with `extensions=False` it comes back as a `text` region). In hOCR such lines sit
   directly in the `ocr_page`. The synthetic blocks are part of the format's reading order, so
   consumers that follow it do not lose those lines.
6. **Rounding.** ALTO coordinates are floats in the schema: `to_alto` writes them exactly (shortest
   repr) by default, `precision=0` writes integers. PAGE and hOCR hold integers only: points are
   rounded half up (`floor(v + 0.5)`, deterministic); boxes are rounded by their corners
   (`x0 = r(x)`, `x1 = r(x + w)`, `w = x1 - x0`) so edges agree with the rounded polygons; PAGE
   clamps negative values at 0 (its schema forbids them). Rounding happens once: a second round
   trip is the identity (tested).
7. **Confidences.** ALTO `WC` and PAGE `TextEquiv/@conf` / `Coords/@conf` are floats in 0..1 and
   written exactly. hOCR `x_wconf` is an integer percentage: confidences come back to 0.01. ALTO
   has no line confidence: a reader derives it as the length-weighted mean of the words' `WC`
   (as for foreign files); the writer stores the real line confidence in the extension when it
   differs from that mean.
8. **Line text vs. words.** Words are joined with one space; when a line's literal text is not that join
   (double spaces, `None` with words), the text goes into the extension. A line without words is
   written as a single ALTO `String` carrying the line text and confidence (extension
   `{"wordless": true}`), as a PAGE `TextLine` with only a line `TextEquiv`, as an hOCR line with
   the text directly in the span. `text=None` (not recognized) and `text=""` (recognized as empty)
   stay distinct in all three.
9. **Output is deterministic**: same input, same bytes (PAGE `Created`/`LastChange` default to
   `1970-01-01T00:00:00`; pass `created=` for a real timestamp).
10. **Ids are written as they are.** Schema-valid output needs ids that are XML NCNames (letters,
   digits, `_ - .`, not starting with a digit); the producers' ids (`text_2`, `orphan_0`, ...)
   are. Ids the writers make up themselves (synthetic blocks, tags, the page) avoid every existing
   id.
11. **Known limits.** Characters XML cannot carry (C0 controls other than tab/newline) make the
    writers raise lxml's `ValueError`; text is not silently altered.
12. **Tests** cover the fixture in `tests/conftest.py` (polygon regions, baselines, box-only lines,
    empty and unrecognized lines, a region-less line, hyphenation, alternatives), irregular orders,
    300 seeded random transcriptions per format (every tenth also validated against the XSD),
    and foreign files (ALTO v2 mm10, v3 without namespace, eScriptorium v4; PAGE 2010 and
    Transkribus 2013; Tesseract hOCR and tag-soup HTML); languages, scripts and directions
    (`tests/formats/test_writing_systems.py`) in round trips and foreign files of each format.

## ALTO (writes 4.4, reads v1 to v4)

| What is written | ALTO |
|---|---|
| region | `TextBlock` (`Illustration TYPE=<label>` for picture/chart regions without lines); `Shape/Polygon` only when the polygon is not the box |
| region label | `LayoutTag TYPE="label" LABEL=<region label>`, one per distinct label, in `TAGREFS` |
| raw label (`Region.label`, when set) | `LayoutTag TYPE="raw_label" LABEL=<raw>` |
| region order | `ReadingOrder/OrderedGroup/ElementRef` (regions with a rank + synthetic blocks); without `ReadingOrder` readers use document order (ALTO's implicit order) |
| line | `TextLine` with `BASELINE="x,y x,y ..."` (4.2+ points syntax), `Shape/Polygon` |
| word | `String` (`WC`, `ALTERNATIVE`), `SP` between words; a `hyphen` word that ends in `- ¬ ⸗ ‐ soft hyphen =` is split into `String` + `HYP` (reader re-joins: word text and line text unchanged) |
| region and line score (detection confidence), heading level, line confidence | extension |
| language (BCP 47) | `LANG` on `Page`, `TextBlock`, `TextLine`, `String`; an `Illustration`'s in the extension |
| direction | `BASEDIRECTION` on `TextBlock` and `TextLine`: horizontal-lr `ltr`, horizontal-rl `rtl`, vertical-rl and vertical-lr `ttb`. `Page` has none: every block carries the page's direction (or its own); a vertical block's direction, a word's and an `Illustration`'s also in the extension |
| script | extension (ALTO has none); the page's on every block |
| model and rule annotators | `Description/Processing` (category, date when recorded, the step as `processingStepDescription`, the step record as JSON in `processingStepSettings`, linecaster as `softwareCreator` with the model and its revision), all referenced from `Page/@PROCESSINGREFS` |

Reading foreign ALTO: namespaces v1–v4 or none; blocks anywhere under `Page` (margins,
`PrintSpace`, nested `ComposedBlock`s, which are transparent); raw label = the `LABEL` of the first
referenced tag (Transkribus `StructureTag`, eScriptorium `OtherTag`), the region label (and so the role) mapped
from it;
`BASELINE` as a single number (ALTO < 4.2) becomes a horizontal line across the line box;
`SUBS_TYPE`/`SUBS_CONTENT` are ignored (the word keeps its `CONTENT`); missing ids are generated
(`line_<rank>`, `<line>_w<k>`, `block_<n>`); `GraphicalElement`s are not read. **Units**: `pixel`
is read as is; with `image_width`/`image_height` and `Page/@WIDTH`/`@HEIGHT` every coordinate is
scaled to the image (also corrects pixel ALTO made on a master of another size); `mm10` and
`inch1200` without the image size need `dpi=` (`px = v * dpi / 254` resp. `/ 1200`); otherwise
`from_alto` raises `ValueError` rather than guessing. **Languages and directions**: `LANG` of the `Page` is the
page's language, of a `TextBlock` (or its deprecated `language`), `TextLine` or `String` the region's, line's or
word's; `OTHERLANGS` is kept as the source's `alto__other_languages`. `BASEDIRECTION` `ltr` reads as horizontal-lr,
`rtl` as horizontal-rl; `ttb` says the lines are vertical but not in which order the columns run, so on a line it reads
as its block's vertical direction and is otherwise not recorded: the value is kept as the region's or line's
extension field `alto__base_direction`, as is `btt`.

## PAGE (writes 2019-07-15, reads 2009–2019)

| What is written | PAGE |
|---|---|
| region | `TextRegion` with `@type` from the region label (below); `ImageRegion`, `ChartRegion`, `TableRegion`, `MathsRegion` for picture, chart, table, formula regions **without lines** (PAGE does not allow lines in them) |
| raw label (`Region.label`, when set) | `@custom="structure {type:<raw>;}"` (Transkribus convention; `; { } \` escaped as `\uXXXX`) |
| region and line score (detection confidence) | `Coords/@conf` |
| region order | `ReadingOrder/OrderedGroup/RegionRefIndexed` (nested groups read recursively, `index` sorted) |
| line | `TextLine`: `Coords` = polygon (the box when there is none, extension `{"polygon": null}`), `Baseline`, `TextEquiv/@conf`; alternatives as `TextEquiv/@index` 2.. (primary 1) |
| word | `Word`: `Coords` = box, `TextEquiv` |
| box | not in PAGE: readers take the bounds of `Coords`; the writer stores the box when it differs |
| heading level | extension |
| language | `primaryLanguage` of `Page`, `TextRegion` and `TextLine`, `language` of `Word`: PAGE's English name of the tag's language (`German` for `de` and `de-1901`; `linecaster.formats._languages`); a tag PAGE names otherwise (`de-1901`) or not at all (`grc`) in the extension (not written without it) |
| script | `primaryScript` of `Page`, `TextRegion`, `TextLine` and `Word` (`Latn - Latin`); a code PAGE's list lacks in the extension |
| direction | `Page` and `TextRegion`: `readingDirection` and `textLineOrder`, horizontal-lr `left-to-right` and `top-to-bottom`, horizontal-rl `right-to-left` and `top-to-bottom`, vertical-rl `top-to-bottom` and `right-to-left`, vertical-lr `top-to-bottom` and `left-to-right`; `TextLine` and `Word`: `readingDirection` (`left-to-right`, `right-to-left`, `top-to-bottom` for both vertical ones; within a level that is not vertical, a vertical one also in the extension); another region's (`ImageRegion`, ...) language, script and direction in the extension |
| model and rule annotators | `Metadata/MetadataItem type="processingStep"` (as OCR-D records its processors): `name` the step, `value` the preset or the model, `date` when recorded, `Labels externalModel="linecaster"` with `externalId="model"` (name, engine, revision, preset, preset hash, recipe, recipe hash, backend, software) and `externalId="settings"` (one label per setting); a summary in `Comments` |

Label mapping, region label → `TextRegion/@type`: text, paragraph, list_item, handwritten_text,
reference → `paragraph`; title, section_header → `heading`; page_header → `header`; page_footer →
`footer`; caption → `caption`; footnote → `footnote`; document_index → `TOC-entry`; others →
`other` (or `paragraph`). Reading: `structure {type:...}` wins when it is a known name, then
`@type`: paragraph → text, heading → section_header, header → page_header, footer, page-number,
signature-mark, catch-word → page_footer, footnote(-continued)/endnote → footnote, TOC-entry →
document_index, list-label → list_item, everything else → text; the raw label is the structure
type, else `@type`, else the element name (`TableRegion`). The writer adds the region label to the
extension when the reverse mapping would not return it (e.g. `title` → `heading` →
`section_header`). The same name table (`_xml.RAW_TO_LABEL`) also maps eScriptorium/SegmOnto
zones and PP-DocLayout names. Old PAGE `Coords/Point` children are read; text on glyphs only is
joined into the word.

Languages, scripts and directions are read from the same attributes. A language name maps to its tag by
`linecaster.formats._languages` (generated from the 2019 schema's names and the ISO 639-3 code table: the ISO 639-1
code where there is one, else the ISO 639-3 code; Cambodian and Khmer both read as `km`, Panjabi and Punjabi as `pa`),
a script value to its four-letter code. A nested `TextRegion` takes what it does not say from the region it lies in;
a region's `readingDirection` or `textLineOrder` alone is completed by the page's, and a horizontal
`readingDirection` without any line order reads with lines top to bottom. A line's or word's `top-to-bottom` reads as
the enclosing vertical direction. What has no value of linecaster's is kept as an extension field of the page (the
source), region, line or word: `page__language` (`other`, a name the table lacks), `page__script`,
`page__secondary_language` and `page__secondary_script` (PAGE's secondary values, read only), and
`page__reading_direction` with `page__text_line_order` for a combination that is no direction (`top-to-bottom`
lines stacked `top-to-bottom`).

## hOCR 1.2

| What is written | hOCR |
|---|---|
| region | `div` of class `ocr_carea` (page_header → `ocr_header`, page_footer → `ocr_footer`, picture/chart → `ocr_photo`, table → `ocr_table`, formula → `ocr_math`) with one `p.ocr_par`; `bbox`, `poly` when not the box |
| line | `span.ocr_line`: `bbox`, `baseline slope offset` (hOCR's straight line from the box's bottom-left), `poly`, `x_wconf` |
| baseline that `baseline` cannot express (polyline, vertical) | also `x_bline x1 y1 x2 y2 ...` (custom property) |
| word | `span.ocrx_word`: `bbox`, `x_wconf` |
| raw label, region and line score, heading level, hyphen, alternatives | extension |
| model and rule annotators | `meta name="linecaster-step-<n>"`, the step record as JSON; `ocr-system` is linecaster with its release, `ocr-capabilities` what the file contains |
| the page's language | `html/@lang` and `xml:lang`; `ocr-langs` for an ISO 639-1 code |
| a region's, line's or word's language | `lang` and `xml:lang` of its `ocr_carea` (or its class's `div`), `ocr_line` or `ocrx_word` |
| direction | on the `ocr_page` and a region's, line's or word's element: `dir="ltr"` (horizontal-lr), `dir="rtl"` (horizontal-rl), `style="writing-mode: vertical-rl"` (or `vertical-lr`); a horizontal one within a vertical level also `writing-mode: horizontal-tb` |
| script | extension (hOCR has none), the page's on the `ocr_page` |

Reading foreign hOCR: XHTML or tag-soup HTML (lxml.html fallback); regions are the top-level
float/area classes, lines are `ocr_line`, `ocr_textfloat`, `ocr_caption` and `ocr_header`/
`ocr_footer` spans inside a region (Tesseract's line classes); word text includes nested
`<strong>`/`<em>`; `image "..."` may contain `;`. A language, script and direction hold as in HTML, from the element or
the nearest element it lies in that states one (`hocr.writing_at`): `lang` (`xml:lang`), `dir` (`ltr`, `rtl`;
`auto` states none) and CSS's `writing-mode` in `style` (`vertical-rl`, `vertical-lr`; `horizontal-tb` without a
`dir` reads as horizontal-lr). The page's are those of its `ocr_page`; a paragraph's (Tesseract writes `lang` on
`ocr_par`) count for its lines.

## IIIF annotation page (`linecaster.formats.iiif`)

`to_annotation_page(t, canvas, id, policy=DEFAULT_POLICY)` writes an annotation set as one IIIF Presentation 3
`AnnotationPage` (W3C Web Annotations on the page's canvas `canvas`), its annotations numbered `<id>/<n>`, with the
IIIF Presentation and text granularity contexts:

| Annotation set | Annotation |
|---|---|
| region, in reading order | motivation `classifying`, the content role as a `TextualBody` (purpose `classifying`) |
| line with a reading, in reading order | `supplementing` (IIIF's motivation for a transcription), `textGranularity` `line`, the text as written, the line's language as the body's `language` |
| word | `supplementing`, `textGranularity` `word`, the word's language as the body's `language` |
| edit of a line's reading (or of a word or span of it) | `editing`, the edited text with its kind as the purpose and its target's language as its `language`, targeting the line's annotation (a span's: those characters of its text, a `SpecificResource` with a `TextPositionSelector`; a word's: the word's annotation) |
| description of a region | `describing`, its text with its kind as the purpose |

Targets are the canvas with a media fragment (`#xywh=`, rounded) where the annotation has a box (a line without
one: its region's), the canvas itself where it has none. Each annotation names its annotator as `generator`
(`Software`), or as `creator` (`Person`) for people, with the annotator's name. Regions the policy puts in layer
`none` are left out with their lines and descriptions, and so are lines whose own `status` puts them nowhere. The
output is validated against the IIIF Presentation 3 JSON Schema in the tests.

A body's language is the one its target records ([data model](data-model.md#classifications): `Transcription.language`,
its own `language` classification, else its line's, its region's or the page's), never an inferred one; a body
without one has no `language`, and a region's body never has one.

`from_annotation_page(data, uri=None, ground_truth=False, image_width=None, image_height=None)` reads an annotation
page back (`import.iiif.v1`, preset `iiif-import`; `auto-import` tells a JSON annotation page apart): linecaster's
own and other software's that follow the same conventions.

| Annotation | Transcription |
|---|---|
| `classifying` with a box | a region, the body's value its role |
| `supplementing` (also `transcribing`, `commenting` and `painting` with `textGranularity` `line`), `line` or no granularity | a line, the body's value its text |
| `textGranularity` `word` | a word of the line whose box holds most of it (none: the word is left out) |
| `editing` whose body's purpose is an edit kind (`corrected`, `expanded`, `regularized`, `joined`), targeting a line's annotation, characters of it (`TextPositionSelector`) or a word's annotation | an edit of that line, span or word |
| `describing` with a region's box | a description of that region, the purpose its kind |

A target is a media fragment (`#xywh=`, in pixels, or `percent:` of the canvas's size where `image_width` and
`image_height` give it), a `SpecificResource` with a `FragmentSelector` or an `SvgSelector` with a polygon, or the
canvas itself (a line without a box). A line belongs to the region whose box holds more than half of its own. The
bodies' languages are recorded on the page where every line states the same one, else on each line, and on a word
that states another. Annotators are the annotations' `creator` (people, kind `human`) and `generator` (software,
kind `model`; with `ground_truth`, people too); without either, the file. A comment without a granularity is no line, and an annotation of another
motivation is left out.

## HTML import (`linecaster.formats.html`)

`HtmlConverter` reads an HTML tree into a transcription by HTML's own semantics (blocks, headings, lists, tables,
pictures, MathML formulas, DPUB-ARIA furniture and notes, the CSS that decides what is printed) and, where a run
names them, a source's [conventions](catalog.md). What the page says of its writing is recorded as `language` and
`direction` classifications, each on the narrowest thing it differs on, by whoever the text is by:

| HTML | Recorded as |
|---|---|
| `lang` (`xml:lang` before it) of the root (`html`, its `body`) | the page's (`""`) `language` |
| `dir` and CSS `writing-mode` of the root | the page's `direction`: `rtl` `horizontal-rl`, `ltr` `horizontal-lr`, `vertical-rl` and `vertical-lr` as they are |
| `lang`, `dir`, `writing-mode` of a block (a paragraph, heading, list item, page header or footer, note, table) that differ from the page's | its region's |
| `lang`, `dir` of inline elements (`span`, `bdo`, `bdi`, ...) that differ from their line's | a span of the line (`<line>[a:e]`), consecutive runs of one value one span, without its spaces at either end |

A value is inherited as in HTML: a note or a table cell has the language of the element it stands in. `dir="auto"`,
and a `bdi` without `dir`, leave the direction to the text: nothing is recorded. A `writing-mode` on an inline element
does not apply. A `lang` that is no well-formed BCP 47 tag is skipped and counted (`HtmlReading.ill_formed_languages`).

## TEI import (`linecaster.formats.tei`)

`from_tei(data, page=1, uri=None, ground_truth=False)` reads one page of a TEI P5 document (namespace
`http://www.tei-c.org/ns/1.0`, or none; of a `teiCorpus`, its first `TEI`) into a transcription; the importer
`import.tei.v1` (preset `tei-import`) runs it, and `import.auto.v1` picks it for a file whose root is `TEI` or
`teiCorpus` in TEI's namespace. The document's first form decides how it is read:

| Form | Pages | Regions | Lines |
|---|---|---|---|
| diplomatic: `sourceDoc` | its `surface`s (also in `surfaceGrp`) | each `zone` with lines or text of its own (a `zone` of `zone`s alone is none), its geometry `@points`, else `@ulx @uly @lrx @lry` | `line` and `zone[@type='line']`, with their geometry and a `path` as the baseline; a `zone` without lines: its text broken at `lb`, without geometry; a line on the surface: a line without a region, or a region of its own where all its text is one `fw`, `note` or `head` |
| facsimile and text: `facsimile` with `text` | as in a text; `pb[@facs]` names the page's surface | as in a text, with the geometry of the `zone` a block's `@facs` points to (else the bounds of its lines) | as in a text, with the geometry of the `zone` an `lb` or `l` points to |
| text: `text` (`front`, `body`, `back`) | `pb` begins one; text before the first `pb` is a page of its own | `p`, `ab`, `lg`, `byline`, `dateline`, `signed`, `trailer`, ... paragraphs; `head` a heading (its level the number of `div` around it); `titlePart` the title; `item` a list item; `fw`, `note`, `figure` (its `head` and `p` captions linked to it, its `figDesc` its description), `table` (a line per `row`) | `lb` and `l` begin one; `cb` ends a block; no geometry |

`page` is the page's number (1-based) or the `xml:id` of its `surface` or `pb`; a page the document does not have is a
`ValueError`. The page's surface gives the image size (its `graphic`'s `@width` and `@height` in pixels, else its own
extent) and the source's `uri` (the graphic's `@url`, unless `uri` is given); coordinates are converted from the
surface's grid (its origin `@ulx @uly`, scaled to the graphic's size) to pixels of that image.

Roles: a `zone`'s `@subtype`, else its `@type` (`paragraph`, `column`, `head`, `running-title`, `header`, `footer`,
`pageNum`, `catch`, `sig`, `marginalia`, `note`, `figure`, `table`, `caption`, ...; other names as PAGE-XML's and
SegmOnto's region names read), else the element that holds all its text, else a paragraph. `fw` is the page's
furniture by its `@type`: `header` (and `running-title`) a header, `pageNum` a page number, `catch` a catchword, `sig` a
signature mark, `footer` a footer; another type a header above the page's first text and a footer below it. `note` is
a footnote, a marginal note (`@place` `margin`, `left`, `right`, ...) marginalia, `@place="end"` an endnote. In a text,
a note inside a block is a region after it, linked to it (`note_of`), and furniture comes first or last by where it
stands, as in the HTML import.

| Inline markup | Recorded as |
|---|---|
| `choice`: `sic`/`corr`, `abbr`/`expan`, `orig`/`reg` | the source's reading (`sic`, `abbr`, `orig`) in the line's text, the other as a `corrected`, `expanded` or `regularized` edit of its span; another `choice` its first child, `app` its `lem` (else its first `rdg`) |
| `unclear` | its text, its span with `status` `illegible` (U+FFFD where it is scored) |
| `gap` | no text; `status` `gap` on the empty span where it stands (`<line>[a:a]`) |
| `@rend` (on `hi` and any element): `italic`, `bold`, `underline`, `strikethrough`, `sup`, `sub` and their usual spellings | the reading's formatting |
| `lb[@break='no']` | the last word of one line and the first of the next, each with a `joined` edit holding the whole word (the first half without its division mark) |
| `xml:lang` | a `language` classification (`language_tag`; an ill-formed value skipped) where it differs from what encloses it: the page (`TEI`, `text` and `body`, or `TEI`, `sourceDoc` and the surface), a region, a line (`line`, `l`), else the span of a line it covers |
| `space` | a space |

Anything else keeps its text and is otherwise ignored (`teiHeader`, `figDesc`, `desc` and the like hold no text of the
page); an unknown element never fails the import. One annotator made all of it: people (kind `human`) with
`ground_truth`, which also makes the source a ground truth, else the file (kind `file`), named `tei`, step
`transcription`. The source has `format` `tei` and, for a namespaced file, `tei__namespace`.

## The document (`linecaster.document`)

A page's or an item's document is a rendering ([data model](data-model.md#the-document-linecasterdocument)):
`build_document(t, ..., policy)` makes one page's, `DocumentBuilder` an item's, and `export` writes it. The
`Composer` puts it into `doc.metadata["document"]` for the writers; it is not stored. Each serialization writes the
body, the furniture (page headers and footers) only with `furniture`:

| Format | Writes |
|---|---|
| HTML (`to_html`) | an HTML5 document: a title `h1`, a heading of level n `h(n+1)` (at most `h6`), a paragraph `p`, list items `li` in a `ul`, a note `aside role="doc-footnote"`, a caption `p class="caption"`, code `pre`, a page header and footer `header role="doc-pageheader"` / `footer role="doc-pagefooter"`, a formula block its LaTeX between `\[` and `\]`, a table with its cells' spans and header cells (`table_html`), a picture a `figure` with its image and the text read inside it; formatting as `i`, `b`, `u`, `s`, `sup`, `sub`, languages as `lang`, line breaks as `br`; the document's language as `<html lang>`, its direction as `<html dir="rtl">` or a `writing-mode` style; a block's language and direction where they are not the document's as its element's `lang`, `dir="rtl"` (`dir="ltr"` in a right-to-left document) and `style="writing-mode: vertical-rl"` (or `vertical-lr`) |
| Markdown (`to_markdown`) | by the policy's Markdown rules (`MarkdownRules`): headings `#`, list items `-`, formula blocks `$$…$$`, tables as HTML or as pipe tables (HTML where a cell spans), a picture the rules' placeholder, italic `*`, bold `**`, strikethrough `~~`, scripts and underline as HTML with `html_scripts`, characters Markdown would read escaped with `escape`; `dividers` puts `---` between the blocks of one layout region and the next; no language or direction (Markdown has none, and neither has text) |
| text (`to_text`) | each block's text, blocks separated by a blank line; a table one row per line, cells separated by tabs |
| JSON (`to_json`) | the complete document, every layer and origin (`linecaster.document/2`), a language or direction only where one is recorded; `from_json` reads it back |

## Docling (`linecaster.formats.docling`, the `docling` extra)

`from_docling(source, page_no=None, ground_truth=False, name="docling", dataset=None, record=None)` reads a
DoclingDocument (a document, its dict or its JSON) into a transcription:

- one region per item of the body, furniture and notes layers (on page `page_no`, or on every page), in the
  document's order, which is also the transcription's one reading order: id `<label>_<k>`, the Docling label as
  the region's `label` and, read as a content role, its `role` classification; the box of the item's first
  provenance entry (in top-left coordinates; `None` without one); a section header's level as a `heading_level`
  classification;
- a text item's text as one line per text line (`<region>_l<j>`, without geometry), each read with its text;
- a table as a `Table` of its region, with one line holding its cells' text, so it renders; a picture as a region
  without lines.

One annotator made all of it: people (kind `human`) with `ground_truth`, which also makes the source a ground truth,
else the file (kind `file`), named `name`, step `transcription`. The source has `format` `docling`, `dataset` and
`record` as given, and the image size of the page.

## Working images (`linecaster.images.convert`)

The working format for converted images is lossless WebP at full resolution (the block `ImageConverter`, preset
`working-image`): what the models read is never lossy. Delivered images used as they are (an access derivative) stay
as delivered. Pages larger than the size limit go to `rejects/`. Other formats for other uses are the next section's.

- **Size limit** (`check_size`): width ≤ 16,383 and height ≤ 16,383 (WebP) and
  width × height ≤ 2 × `PIL.Image.MAX_IMAGE_PIXELS`, read at call time, never changed. 2× is
  exactly where Pillow's `Image.open` raises `DecompressionBombError`; that error is turned into
  `ImageTooLarge` with the same kind of reason. Checked from the header (`Image.open` without
  `load`), so oversized pages are never decoded; between 1× and 2× Pillow's warning is silenced
  and the page converted.
- **Color**: embedded ICC → sRGB (LittleCMS, perceptual); a profile that cannot be applied is
  reported (`icc_error`) and the plain conversion used. 16-bit grayscale → 8 bit as
  `round(v·255/65535)`; Pillow reads 16-bit RGB as 8-bit itself. Grayscale/bilevel/palette → RGB.
  Alpha is composited onto white (`alpha_flattened`); fully opaque alpha is just dropped. CMYK
  without a profile: Pillow's conversion. EXIF orientation is not applied (coordinates refer to
  the stored pixels) but reported as `exif_orientation`.
- **Encoding**: always lossless WebP (`VP8L`), full resolution, `method=0`, `exact=True`;
  `effort` (Pillow's `quality` for lossless) defaults to Pillow's 80.
- **info**: `format`, `width`, `height`, `source_format`, `source_mode`, `pixels_sha256` (sha256 of
  the decoded 8-bit RGB bytes, row-major, what the WebP decodes to), `sha256` (of the WebP),
  `decoder` (`Pillow x / <source library> y / libwebp z`), `webp_settings`, `icc_applied`,
  `alpha_flattened`, and `warnings` when the image has image warnings ([glossary](glossary.md)); the keys match
  `PageImage` where they overlap.
- **Image warnings**: a fault the image is read around is reported, not fatal: a PNG's optional chunk with a wrong
  checksum is left out when read (as libpng does; Pillow alone refuses the file), and what Pillow warns about while
  reading, EXIF that cannot be read and an ICC profile that cannot be applied are listed in `warnings` (also in the
  page image's `extra`, and logged). A fault that keeps the pixels from being read rejects the page.

## Image conversion (`linecaster.images.transcode`, `linecaster.images.accel`)

Page images for other uses (publishing, downloads) are converted by the same block with an `image.convert.v1` preset
(`webp-lossy-q80`, `jpeg-q90`, `jp2-lossless`, `png`; `pipelines/convert.py`): JPEG, JPEG 2000, PNG or WebP at full
resolution, 8-bit sRGB, with the working image's size limit, colour handling and image warnings.

- **Decoding**: JPEG (nvJPEG), JPEG 2000 (nvJPEG2000) and TIFF (nvTIFF) in 8-bit gray or RGB on an NVIDIA GPU where
  the machine has one and nvImageCodec is installed (`linecaster[nvimgcodec]`, CUDA 13 wheels for aarch64 and
  x86_64); every other image, and every image on a machine without them, with Pillow. Only nvImageCodec's GPU
  decoders are allowed, so an image it cannot do on the GPU is decoded by Pillow, never by another CPU library. A
  GPU decode hands the pixels on in the source's own mode with the ICC profile from the header, and the colour
  handling above runs after either decoder.
- **Encoding**: JPEG (nvJPEG) and JPEG 2000 (nvJPEG2000) on the GPU where it can, else with Pillow (libjpeg-turbo,
  OpenJPEG); PNG and WebP always with Pillow (zlib, libwebp): no GPU library writes them (nvImageCodec only through
  its CPU OpenCV extension).
- **Fallback**: whatever keeps the GPU from an image, the CPU does it: a file its decoder or encoder rejects (nvJPEG2000,
  for one, rejects code streams with the vertically causal context, code-block style 0x08), or a failing GPU (an
  error, too little memory). The image's record says so (`gpu_fallback`), the block counts it, and a failure of the GPU
  is logged as a WARNING; `accel` `gpu` makes either an error.
- **Choice**: found out per machine, never configured (`cuda_devices` asks the CUDA driver; nvImageCodec is used
  when installed). `accel` `auto` takes the GPU where it can, `cpu` never, `gpu` is an error where it cannot. Each
  image records its `decoder` and `encoder`: a GPU and a CPU decoder can round lossy JPEG and JPEG 2000 differently,
  and a GPU and a CPU encoder write different bytes at the same quality. `linecaster images compare FILES` decodes
  images both ways and says how far the pixels differ.
- **Throughput**: decoding and encoding are stages with windows of their own, adapted by saturate's controller to
  the pixels per second and cut when memory or open files run short; a GPU decodes what arrives together in one
  batch. One worker process per GPU (round robin by worker index); the windows' bound divides the CPUs among the
  workers.
- **Files**: `<output_folder>/<item>/<page>.<ext>` under a temporary name (`.part`), renamed when complete; a file
  that is there already is not converted again (`skip_existing`).
- **record** (`page.image`, its `extra`): `format`, `width`, `height`, `sha256`, `pixels_sha256`, `decoder`;
  `encoder`, `bytes`, `icc_applied`, `alpha_flattened`, and when present `exif_orientation`, `icc_error`,
  `warnings`; the delivered image under `original`, the step under `step`.
