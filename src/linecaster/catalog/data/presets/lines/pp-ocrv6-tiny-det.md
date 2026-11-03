---
schema: linecaster.preset/1
id: pp-ocrv6-tiny-det
edition: 1
step: lines
model:
  id: pp-ocrv6-tiny-det-onnx
  revision: 2ba1506c0380b8f0b03dd142459aac66d4421f6c
engine: paddlex.lines.v1
options:
  model_name: PP-OCRv6_tiny_det
  per_region: false
  unclip_ratio: 1.5
  box_thresh: 0.6
  thresh: 0.3
  pad: 0
  mask: false
capabilities:
  unit: page
  produces:
  - lines
provenance:
  derived_from:
  - 'storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7);
    --det-model PP-OCRv6_tiny_det'
  created: 2026-11-03
support: experimental
---

PP-OCRv6 tiny text-line detection on the whole page, on ONNX Runtime.
The same settings as the squiddle combination's medium detector, with the tiny model; not validated against the goldens.

`unclip_ratio` 1.5, PaddleOCR's own default: squiddleocr went back to it from 2.0 on 2026-10-20 because the 2.0
default rested on two Fraktur pages and one CER lane, and wider boxes shrink the glyphs in the recogniser's
input (Fraktur n and u merged on a display line), while tighter ones clip descenders. The rule since: no change
of this parameter without a run over a few hundred BHL pages with the frozen scorer, both CER lanes. `box_thresh`
0.6 and `thresh` 0.3 are PaddleOCR's defaults; detection runs on the whole page (`per_region` off), and the
lines are assigned to the layout regions afterwards (`AssignLinesToRegions`).
