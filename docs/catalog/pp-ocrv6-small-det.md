# pp-ocrv6-small-det

*Edition 1 · lines · experimental*

PP-OCRv6 small text-line detection on the whole page, on ONNX Runtime.
The same settings as the squiddle combination's medium detector, with the small model; not validated against the goldens.

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
| Model | [PP-OCRv6_small_det](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_onnx/tree/28fe5895c24fd108c19eb3e8479f4ab385fbfc62) |
| Revision | `28fe5895c24fd108c19eb3e8479f4ab385fbfc62` |
| Upstream card | [upstream/28fe5895c24fd108c19eb3e8479f4ab385fbfc62/README.md](../../engines/paddlex/src/linecaster_paddlex/catalog/models/pp-ocrv6-small-det-onnx/upstream/28fe5895c24fd108c19eb3e8479f4ab385fbfc62/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Derived from | converted of PaddlePaddle/PP-OCRv6_small_det |
| Produces | lines |

## Provenance

- storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7); --det-model PP-OCRv6_small_det
