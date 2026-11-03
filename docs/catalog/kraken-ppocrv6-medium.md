# kraken-ppocrv6-medium

*Edition 1 · recognition · core*

kraken's PP-OCRv6 medium recogniser through kraken's own code (`RecognitionTaskModel`), on every line of the
page in the line step's order; the squiddle combination's recogniser, which reproduces squiddleocr's goldens line for line (1,560/1,560 lines on sample-60, spark and forge).

- `batch_size` 8: the batch size squiddleocr's goldens were recorded with. kraken pads a batch to its widest
  line, so the batch size can move numerics; one page per request, batching only within the page.
- `precision` auto: bf16-mixed on CUDA (the model was trained in bf16-mixed; recognition about 1.6x faster on the
  GB10; 79 of 3,673 lines on 100 BHL pages read differently from 32-true), 32-true on the CPU. Needs the kraken fork with the
  inference autocast fix (storytracer/kraken 3d235ee8); on upstream kraken 7.1 the setting is inert.
  T4-class GPUs have no bf16 tensor cores: use 16-mixed or 32-true there (a new preset).
- `text_direction` horizontal-lr; right-to-left material wants horizontal-rl.

| | |
|---|---|
| Step | recognition (reads lines) |
| Engine | `kraken.recognition/1` |
| Model | [PP-OCRv6 (medium)](https://huggingface.co/small-models-for-glam/kraken-ppocrv6-medium/tree/f7fd70f3fd22b615f41bada4674ac2462f938339) |
| Revision | `f7fd70f3fd22b615f41bada4674ac2462f938339` |
| Upstream card | [upstream/f7fd70f3fd22b615f41bada4674ac2462f938339/README.md](../../engines/kraken/src/linecaster_kraken/catalog/models/kraken-ppocrv6-medium/upstream/f7fd70f3fd22b615f41bada4674ac2462f938339/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Languages | ara, cat, ces, chu, cos, dan, deu, dum, eng, fas, fin, fra, frm, gez, gle, grc, heb, hun, ita, kat, lat, lav, lit, mal, mul, nld, nor, oci, ota, pcd, pol, por, ron, rus, slk, slv, spa, srp, swe, syr, ukr, urd, xcl, yid |
| Scripts | Arab, Armn, Cyrl, Ethi, Geor, Grek, Hebr, Latn, Mlym, Syrc |
| Derived from | mirror of 10.5281/zenodo.21788410 |
| Produces | text, words, word_confidences, line_confidences |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_diplomatic 0.0341, cer_reading 0.027, recall 0.9508, wall_seconds 72 |

## Provenance

- storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7)
