The rows of each text region joined into paragraphs, from
geometry and Unicode's character properties, never from a language name; the squiddle combination's recomposition.

- Paragraph breaks: a row indented by `indent` (0.8 em) from the start margin, a gap above it of about a blank
  line (more than `gap_leading` 0.6 of the leading and `gap_height` 0.5 of the taller row), or, in justified text
  (at least `justified_rows` 3 rows, `justified_share` 0.6 of them ending within `end_margin` 0.6 em of the end
  margin), a row before it that stopped `short_row` 1.5 em and `short_row_width` a quarter of the width short.
- Division marks (Unicode's hyphens by Line_Break, and `convention_marks`, the not sign some transcription
  conventions write) after a letter at a row end are removed unless the next row starts with a capital or a digit,
  a Hebrew letter is not followed by Hebrew, or the document attests the hyphenated form and not the joined one.
  The lexicon is the item's own words, growing page by page.
- Rows join without a space where UAX #14 allows a break without one (ideographs, Thai), else with one.
- A paragraph without sentence-final punctuation that ends with a division mark or reaches the end margin
  continues in the next text region whose first row is not indented and starts with a letter, and, recomposing an
  item, on the next page; a region of digits only between them (a page number) does not close it.
- Without geometry (a text-only transcription) a region is one paragraph.
