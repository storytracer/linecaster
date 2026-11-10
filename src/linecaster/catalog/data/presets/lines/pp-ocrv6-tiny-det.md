PP-OCRv6 tiny text-line detection on the whole page, on ONNX Runtime.
The same settings as the squiddle combination's medium detector, with the tiny model.

`unclip_ratio` 1.5, PaddleOCR's own default: wider boxes shrink the glyphs in the recognizer's input, tighter
ones clip descenders. Change it only after a run over a few hundred pages of the material at hand. `box_thresh`
0.6 and `thresh` 0.3 are PaddleOCR's defaults; detection runs on the whole page (`per_region` off), and the
lines are assigned to the layout regions afterwards (`LineAssigner`).
