# kraken-ppocrv6-small

*Edition 1 · recognition · experimental*

kraken's PP-OCRv6 small recogniser through kraken's own code (`RecognitionTaskModel`), on every line of the
page in the line step's order.

- `batch_size` 8: the batch size squiddleocr's goldens were recorded with. kraken pads a batch to its widest
  line, so the batch size can move numerics; one page per request, batching only within the page.
- `precision` auto: bf16-mixed on CUDA (the model was trained in bf16-mixed; recognition about 1.6x faster on the
  GB10; 79 of 3,673 lines on 100 BHL pages read differently from 32-true), 32-true on the CPU. Needs the kraken fork with the
  inference autocast fix (storytracer/kraken 3d235ee8); on upstream kraken 7.1 the setting is inert.
  T4-class GPUs have no bf16 tensor cores: use 16-mixed or 32-true there (a new preset).
- `text_direction` horizontal-lr; right-to-left material wants horizontal-rl.
- Not validated against the goldens (which use medium); the card says tiny and small trade accuracy for speed and memory.

| | |
|---|---|
| Step | recognition (reads lines) |
| Engine | `kraken.recognition/1` |
| Model | [PP-OCRv6 (small)](https://huggingface.co/small-models-for-glam/kraken-ppocrv6-small/tree/49c249bf81d95ab2c5f699638d066f7935da6f16) |
| Revision | `49c249bf81d95ab2c5f699638d066f7935da6f16` |
| Upstream card | [upstream/49c249bf81d95ab2c5f699638d066f7935da6f16/README.md](../../engines/kraken/src/linecaster_kraken/catalog/models/kraken-ppocrv6-small/upstream/49c249bf81d95ab2c5f699638d066f7935da6f16/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Languages | ara, cat, ces, chu, cos, dan, deu, dum, eng, fas, fin, fra, frm, gez, gle, grc, heb, hun, ita, kat, lat, lav, lit, mal, mul, nld, nor, oci, ota, pcd, pol, por, ron, rus, slk, slv, spa, srp, swe, syr, ukr, urd, xcl, yid |
| Scripts | Arab, Armn, Cyrl, Ethi, Geor, Grek, Hebr, Latn, Mlym, Syrc |
| Derived from | mirror of 10.5281/zenodo.21788405 |
| Produces | text, words, word_confidences, line_confidences |

## Provenance

- storytracer/squiddleocr@7c8a052 (the settings its goldens were recorded with: sample-60, tables-7); -m small
