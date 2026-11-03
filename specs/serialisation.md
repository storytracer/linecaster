# Serialisation and working images (decisions of 2026-11-03, for review)

`linecaster.transcription.{alto,pagexml,hocr}` write and read the three XML formats on lxml;
`linecaster.images` turns any page image into the working image. Neither imports datatrove,
saturate or an engine.

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
2. **Semantic round trip** (`from_x(to_x(t))`): regions, lines and words with their ids, text,
   geometry, confidences, alternatives, the `hyphen` flag, region label, raw label, score and
   heading level, line score, `reading_order` and `row`. Not serialised: `docling` (export only),
   `extra` dicts, `model`'s `measurements` other than `datetime`, `source` (readers set
   `kind="converted"`, `format`, `uri`, image size). Readers return regions and lines in document
   order, which may differ from the original list order; tests compare by id.
   **Provenance** round-trips: every `ModelInfo` (step, name, revision, preset, preset hash, backend,
   settings; `datetime` as ALTO `processingDateTime` and PAGE `MetadataItem/@date`) is written as ALTO
   `Processing`, PAGE `MetadataItem type="processingStep"` with `Labels`, and hOCR `linecaster-step-<n>`
   metas next to `ocr-system` and `ocr-capabilities` (computed from what the file contains). Other tools'
   provenance is read too (ALTO `OCRProcessing`, OCR-D PAGE steps, hOCR `ocr-system`). METS agents per
   step: `linecaster.provenance.mets_agents`.
3. **Writing order.** Regions are written by `reading_order` (regions without one after the others,
   in list order), each region's lines by `reading_order`. A line without a region goes before
   the first region whose first line comes after it; consecutive ones share one block. Readers
   assign line `reading_order` = position in document order and `row` = position in its block, and
   region `reading_order` = rank in the format's reading order; the writers record the original
   value in the extension whenever that differs (gaps, a running head read last, a region without
   an order), so irregular orders survive too.
4. **Lines without a region.** ALTO and PAGE need a block around every line: they get a synthetic
   `TextBlock`/`TextRegion` (`id` `lc_block_<n>`, extension `{"synthetic": true}`) that the reader
   drops again (with `extensions=False` it comes back as a `text` region). In hOCR such lines sit
   directly in the `ocr_page`. The synthetic blocks are part of the format's reading order, so
   consumers that follow it do not lose those lines.
5. **Rounding.** ALTO coordinates are floats in the schema: `to_alto` writes them exactly (shortest
   repr) by default, `precision=0` writes integers. PAGE and hOCR hold integers only: points are
   rounded half up (`floor(v + 0.5)`, deterministic); boxes are rounded by their corners
   (`x0 = r(x)`, `x1 = r(x + w)`, `w = x1 - x0`) so edges agree with the rounded polygons; PAGE
   clamps negative values at 0 (its schema forbids them). Rounding happens once: a second round
   trip is the identity (tested).
6. **Confidences.** ALTO `WC` and PAGE `TextEquiv/@conf` / `Coords/@conf` are floats in 0..1 and
   written exactly. hOCR `x_wconf` is an integer percentage: confidences come back to 0.01. ALTO
   has no line confidence: a reader derives it as the length-weighted mean of the words' `WC`
   (as for foreign files); the writer stores the real line confidence in the extension when it
   differs from that mean.
7. **Line text vs. words.** Words are joined with one space; when a line's `text` is not that join
   (double spaces, `None` with words), the text goes into the extension. A line without words is
   written as a single ALTO `String` carrying the line text and confidence (extension
   `{"wordless": true}`), as a PAGE `TextLine` with only a line `TextEquiv`, as an hOCR line with
   the text directly in the span. `text=None` (not recognised) and `text=""` (recognised as empty)
   stay distinct in all three.
8. **Output is deterministic**: same input, same bytes (PAGE `Created`/`LastChange` default to
   `1970-01-01T00:00:00`; pass `created=` for a real timestamp).
9. **Ids are written as they are.** Schema-valid output needs ids that are XML NCNames (letters,
   digits, `_ - .`, not starting with a digit); the producers' ids (`text_2`, `orphan_0`, ...)
   are. Ids the writers make up themselves (synthetic blocks, tags, the page) avoid every existing
   id.
10. **Known limits.** Characters XML cannot carry (C0 controls other than tab/newline) make the
    writers raise lxml's `ValueError`; text is not silently altered. Language is written to hOCR
    `lang` only.
11. **Tests**: the fixture in `tests/conftest.py` (polygon regions, baselines, box-only lines,
    empty and unrecognised lines, a region-less line, hyphenation, alternatives), irregular orders,
    300 seeded random transcriptions per format (every tenth also validated against the XSD),
    and foreign files (ALTO v2 mm10, v3 without namespace, eScriptorium v4; PAGE 2010 and
    Transkribus 2013; Tesseract hOCR and tag-soup HTML).

## ALTO (writes 4.4, reads v1 to v4)

| Transcription | ALTO |
|---|---|
| region | `TextBlock` (`Illustration TYPE=<label>` for picture/chart regions without lines); `Shape/Polygon` only when the polygon is not the box |
| region label | `LayoutTag TYPE="label" LABEL=<docling label>`, one per distinct label, in `TAGREFS` |
| raw label | `LayoutTag TYPE="raw_label" LABEL=<raw>` |
| region order | `ReadingOrder/OrderedGroup/ElementRef` (regions with an order + synthetic blocks); without `ReadingOrder` readers use document order (ALTO's implicit order) |
| line | `TextLine` with `BASELINE="x,y x,y ..."` (4.2+ points syntax), `Shape/Polygon` |
| word | `String` (`WC`, `ALTERNATIVE`), `SP` between words; a `hyphen` word that ends in `- ¬ ⸗ ‐ soft hyphen =` is split into `String` + `HYP` (reader re-joins: word text and line text unchanged) |
| score, heading level, line confidence | extension |

Reading foreign ALTO: namespaces v1–v4 or none; blocks anywhere under `Page` (margins,
`PrintSpace`, nested `ComposedBlock`s, which are transparent); raw label = the `LABEL` of the first
referenced tag (Transkribus `StructureTag`, eScriptorium `OtherTag`), Docling label mapped from it;
`BASELINE` as a single number (ALTO < 4.2) becomes a horizontal line across the line box;
`SUBS_TYPE`/`SUBS_CONTENT` are ignored (the word keeps its `CONTENT`); missing ids are generated
(`line_<rank>`, `<line>_w<k>`, `block_<n>`); `GraphicalElement`s are not read. **Units**: `pixel`
is read as is; with `image_width`/`image_height` and `Page/@WIDTH`/`@HEIGHT` every coordinate is
scaled to the image (also corrects pixel ALTO made on a master of another size); `mm10` and
`inch1200` without the image size need `dpi=` (`px = v * dpi / 254` resp. `/ 1200`); otherwise
`from_alto` raises `ValueError` rather than guessing.

## PAGE (writes 2019-07-15, reads 2009–2019)

| Transcription | PAGE |
|---|---|
| region | `TextRegion` with `@type` from the label (below); `ImageRegion`, `ChartRegion`, `TableRegion`, `MathsRegion` for picture, chart, table, formula regions **without lines** (PAGE does not allow lines in them) |
| raw label | `@custom="structure {type:<raw>;}"` (Transkribus convention; `; { } \` escaped as `\uXXXX`) |
| region score / line score | `Coords/@conf` |
| region order | `ReadingOrder/OrderedGroup/RegionRefIndexed` (nested groups read recursively, `index` sorted) |
| line | `TextLine`: `Coords` = polygon (the box when there is none, extension `{"polygon": null}`), `Baseline`, `TextEquiv/@conf`; alternatives as `TextEquiv/@index` 2.. (primary 1) |
| word | `Word`: `Coords` = box, `TextEquiv` |
| bbox | not in PAGE: readers take the bounds of `Coords`; the writer stores the box when it differs |

Label mapping, Docling → `TextRegion/@type`: text, paragraph, list_item, handwritten_text,
reference → `paragraph`; title, section_header → `heading`; page_header → `header`; page_footer →
`footer`; caption → `caption`; footnote → `footnote`; document_index → `TOC-entry`; others →
`other` (or `paragraph`). Reading: `structure {type:...}` wins when it is a known name, then
`@type`: paragraph → text, heading → section_header, header → page_header, footer, page-number,
signature-mark, catch-word → page_footer, footnote(-continued)/endnote → footnote, TOC-entry →
document_index, list-label → list_item, everything else → text; the raw label is the structure
type, else `@type`, else the element name (`TableRegion`). The writer adds the Docling label to the
extension when the reverse mapping would not return it (e.g. `title` → `heading` →
`section_header`). The same name table (`_xml.RAW_TO_DOCLING`) also maps eScriptorium/SegmOnto
zones and PP-DocLayout names. Old PAGE `Coords/Point` children are read; text on glyphs only is
joined into the word.

## hOCR 1.2

| Transcription | hOCR |
|---|---|
| region | `div` of class `ocr_carea` (page_header → `ocr_header`, page_footer → `ocr_footer`, picture/chart → `ocr_photo`, table → `ocr_table`, formula → `ocr_math`) with one `p.ocr_par`; `bbox`, `poly` when not the box |
| line | `span.ocr_line`: `bbox`, `baseline slope offset` (hOCR's straight line from the box's bottom-left), `poly`, `x_wconf` |
| baseline that `baseline` cannot express (polyline, vertical) | also `x_bline x1 y1 x2 y2 ...` (custom property) |
| word | `span.ocrx_word`: `bbox`, `x_wconf` |
| raw label, region score, heading level, hyphen, alternatives | extension |

Reading foreign hOCR: XHTML or tag-soup HTML (lxml.html fallback); regions are the top-level
float/area classes, lines are `ocr_line`, `ocr_textfloat`, `ocr_caption` and `ocr_header`/
`ocr_footer` spans inside a region (Tesseract's line classes); word text includes nested
`<strong>`/`<em>`; `image "..."` may contain `;`.

## Working images (`linecaster.images`)

- **Size limit** (`check_size`): width ≤ 16,383 and height ≤ 16,383 (WebP) and
  width × height ≤ 2 × `PIL.Image.MAX_IMAGE_PIXELS`, read at call time, never changed. 2× is
  exactly where Pillow's `Image.open` raises `DecompressionBombError`; that error is turned into
  `ImageTooLarge` with the same kind of reason. Checked from the header (`Image.open` without
  `load`), so oversized pages are never decoded; between 1× and 2× Pillow's warning is silenced
  and the page converted.
- **Colour**: embedded ICC → sRGB (LittleCMS, perceptual); a profile that cannot be applied is
  reported (`icc_error`) and the plain conversion used. 16-bit greyscale → 8 bit as
  `round(v·255/65535)`; Pillow reads 16-bit RGB as 8-bit itself. Greyscale/bilevel/palette → RGB.
  Alpha is composited onto white (`alpha_flattened`); fully opaque alpha is just dropped. CMYK
  without a profile: Pillow's conversion. EXIF orientation is not applied (coordinates refer to
  the stored pixels) but reported as `exif_orientation`.
- **Encoding**: always lossless WebP (`VP8L`), full resolution, `method=0`, `exact=True`;
  `effort` (Pillow's `quality` for lossless) defaults to Pillow's 80. One measurement on spark, a
  3996 × 5964 newspaper JPEG: decode 0.09 s; encode effort 0: 1.67 s / 17.2 MB, 25: 1.99 s /
  17.1 MB, 80: 7.0 s / 16.6 MB, 100: 9.6 s / 16.4 MB. Effort 0 is 4× faster for 4 % more bytes;
  left at the default until measured on a broader sample.
- **info**: `format`, `width`, `height`, `source_format`, `source_mode`, `pixels_sha256` (sha256 of
  the decoded 8-bit RGB bytes, row-major, what the WebP decodes to), `sha256` (of the WebP),
  `decoder` (`Pillow x / <source library> y / libwebp z`), `webp_settings`, `icc_applied`,
  `alpha_flattened`; the keys match `PageImage` where they overlap.
