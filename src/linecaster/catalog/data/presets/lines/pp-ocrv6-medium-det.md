PP-OCRv6 medium text-line detection on the whole page, on ONNX Runtime; the squiddle combination's line step.
PaddleX's own OCR pipeline uses it in place of PP-OCRv5 server; its finer boxes let the table step fill header cells that v5's whole-row boxes left empty, at the price of some Fraktur lines split at wide gaps.

`unclip_ratio` 1.5, PaddleOCR's own default: wider boxes shrink the glyphs in the recognizer's input (Fraktur n and
u merged on a display line), while tighter ones clip descenders, and a larger ratio that looked better on a few
pages did not hold up on more. Change it only after a run over a few hundred pages of the material at hand. `box_thresh`
0.6 and `thresh` 0.3 are PaddleOCR's defaults; detection runs on the whole page (`per_region` off), and the
lines are assigned to the layout regions afterwards (`LineAssigner`).
