The property schemes geometry decides, by rules on the page's lines and regions: `rotated` and `tiny` on lines,
`multi_column` on text regions, each with its evidence in the annotator's raw output. Nothing is recorded where the
geometry does not decide; a model tagger (`tagging.chat.v1`) can ask about the rest.

- `max_tilt` 5: the `rotated` vocabulary's "tilted by about 5 degrees or more". A line's tilt is its baseline's,
  else its polygon's when that is at least three times longer than high (`elongation` 3: a single glyph's box says
  no angle); a vertical writing direction recorded for the line is rotated too. A line with only a box is not
  decided, and neither is a half turn: an upside-down page has level baselines.
- `tiny` 0.6: a line lower than 0.6 times the median height of the page's body text lines (`body_roles`: paragraphs
  and list items) is tiny. The vocabulary's fine print is about 6 pt, and body type is set at 10 to 12 pt, so 6 pt is
  0.5 to 0.6 of it; a running header or a footnote at 8 to 9 pt, which the definition excludes, is 0.7 to 0.8. Line
  heights follow type sizes, since a line's box spans its ascenders and descenders. With fewer than five body lines
  (`min_body_lines`) the page has no measure of its body text, and nothing is decided.
- `multi_column`: a text region is in columns when another text region sits beside it, their extents across the
  lines overlapping by a quarter of the shorter (`min_overlap` 0.25) and along the lines by at most a tenth of the
  narrower (`max_overlap` 0.1); it is not when it spans at least 80 % of the page's text width (`full_width` 0.8)
  with nothing beside it. A narrow region alone is left undecided: it may end a column whose neighbor ended higher.

The thresholds follow the vocabularies' definitions; none is yet measured against reviewed tags.
