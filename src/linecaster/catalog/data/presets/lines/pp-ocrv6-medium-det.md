PP-OCRv6 medium text-line detection on the whole page, on ONNX Runtime; the squiddle combination's line step.
PaddleX's own OCR pipeline uses it in place of PP-OCRv5 server.

`unclip_ratio` 1.5, PaddleOCR's own default: wider boxes shrink the glyphs in the recognizer's input, tighter
ones clip descenders. Change it only after a run over a few hundred pages of the material at hand. `box_thresh`
0.6 and `thresh` 0.3 are PaddleOCR's defaults; detection runs on the whole page (`per_region` off), and the
lines are assigned to the layout regions afterwards (`LineAssigner`).
