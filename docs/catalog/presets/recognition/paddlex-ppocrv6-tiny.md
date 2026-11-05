# paddlex-ppocrv6-tiny

*Preset · edition 1 · recognition · experimental*

PaddleOCR's own PP-OCRv6 tiny recogniser on PaddleX's ONNX Runtime engine. Lines are cut as PaddleX's OCR
pipeline cuts them (minimum-area rectangle of the polygon, warped upright), sorted by aspect ratio and read
`batch_size` 8 at a time, as PaddleX's pipeline does. Words: the text split at whitespace, placed along the line by
the CTC columns of their characters (PaddleX's `return_word_box`); PaddleX gives no per-word confidence.

On the 60-page BHL sample (2026-11-03, `evidence/`) the same modular pipeline with kraken's port of the model family read
better on every volume but one; the likely difference is the line image (kraken's polygon-based extraction
against PaddleX's rectangle warp). Not investigated further.

|  |  |
|---|---|
| Step | recognition (reads lines) |
| Engine | [`paddlex.recognition.v1`](../../engines/paddlex.recognition.v1.md) |
| Model | [PP-OCRv6_tiny_rec](../../models/pp-ocrv6-tiny-rec-onnx.md) |
| Revision | [`2612ab37152ae0a677521bae4e1e3d4fb4cf7c30`](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_rec_onnx/tree/2612ab37152ae0a677521bae4e1e3d4fb4cf7c30) |
| Licence | Apache-2.0 |
| Produces | text, words, line_confidences |

## Options

| Option | Value |
|---|---|
| model_name | `PP-OCRv6_tiny_rec` |
| batch_size | `8` |
| words | `True` |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 (transcribe_modular.v1 with pp-doclayoutv3@1, pp-ocrv6-medium-det@1, slanet-plus@1, no formulas, text lines; only the recogniser varied) | cer_diplomatic 0.0446, cer_reading 0.0376, recall 0.9123, wall_seconds 33 |

## Provenance

- storytracer/linecaster@7beadcc (NOTES: More line recognisers, the comparison on sample-60)
