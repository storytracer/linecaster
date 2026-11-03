# pp-ocrv6-medium-det

*Edition 1 · lines · core*

PP-OCRv6 medium text-line detection on the whole page, on ONNX Runtime; the squiddle combination's line step.
PP-OCRv6 medium replaced PP-OCRv5 server as squiddleocr's detector on 2026-09-07 (PaddleX's own OCR pipeline moved to it); its finer boxes let the table step fill header cells that v5's whole-row boxes left empty, at the price of some Fraktur lines split at wide gaps.

`unclip_ratio` 1.5, PaddleOCR's own default: squiddleocr went back to it from 2.0 on 2026-10-20 because the 2.0
default rested on two Fraktur pages and one CER lane, and wider boxes shrink the glyphs in the recogniser's
input (Fraktur n and u merged on a display line), while tighter ones clip descenders. The rule since: no change
of this parameter without a run over a few hundred BHL pages with the frozen scorer, both CER lanes. `box_thresh`
0.6 and `thresh` 0.3 are PaddleOCR's defaults; detection runs on the whole page (`per_region` off), and the
lines are assigned to the layout regions afterwards (`AssignLinesToRegions`).

| | |
|---|---|
| Step | lines (reads pages) |
| Engine | `paddlex.lines/1` |
| Model | [PP-OCRv6_medium_det](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det_onnx/tree/61323801669c338b7891481ec7bac61ce31b576a) |
| Revision | `61323801669c338b7891481ec7bac61ce31b576a` |
| Upstream card | [upstream/61323801669c338b7891481ec7bac61ce31b576a/README.md](../../engines/paddlex/src/linecaster_paddlex/catalog/models/pp-ocrv6-medium-det-onnx/upstream/61323801669c338b7891481ec7bac61ce31b576a/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Derived from | converted of PaddlePaddle/PP-OCRv6_medium_det |
| Produces | lines |

## Provenance

- storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7)
