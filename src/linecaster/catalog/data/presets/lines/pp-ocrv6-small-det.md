PP-OCRv6 small text-line detection on the whole page, on ONNX Runtime.
The same settings as the squiddle combination's medium detector, with the small model.

`unclip_ratio` 1.5, PaddleOCR's own default: wider boxes shrink the glyphs in the recognizer's input (Fraktur n and
u merged on a display line), while tighter ones clip descenders, and a larger ratio that looked better on a few
pages did not hold up on more. Change it only after a run over a few hundred pages of the material at hand. `box_thresh`
0.6 and `thresh` 0.3 are PaddleOCR's defaults; detection runs on the whole page (`per_region` off), and the
lines are assigned to the layout regions afterwards (`LineAssigner`).
