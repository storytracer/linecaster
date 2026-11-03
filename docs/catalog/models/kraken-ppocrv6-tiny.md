# kraken-ppocrv6-tiny

*Model · PP-OCRv6 (tiny) · Apache-2.0*

Benjamin Kiessling's PP-OCRv6 (tiny) line recogniser for kraken (ALMAnaCH, Inria Paris), as mirrored byte for
byte on the Hugging Face Hub by Small Models for GLAM; the canonical release is the Zenodo record
[10.5281/zenodo.21788403](https://doi.org/10.5281/zenodo.21788403), which is provenance only: linecaster always downloads from the mirror (Zenodo
throttles). Licence, languages (44 plus `mul`) and scripts are the card's.

The card describes the model as trained from scratch by kraken's author on line images of historical,
contemporary and born-digital documents, handwritten and printed, on an architecture adapted from PaddlePaddle's
PP-OCRv6 (128 px line height, uncapped line width, Adam+Muon); it is not a conversion of PaddleOCR's
`PP-OCRv6_tiny_rec` weights, so `derived_from` names only the mirror relation. kraken's own code runs it
(`kraken.recognition.v1`), on torch; the model was trained in bf16-mixed, which is why linecaster's presets run it
in bf16-mixed on CUDA.

|  |  |
|---|---|
| Source | [small-models-for-glam/kraken-ppocrv6-tiny](https://huggingface.co/small-models-for-glam/kraken-ppocrv6-tiny) |
| Licence | Apache-2.0 |
| Languages | ara, cat, ces, chu, cos, dan, deu, dum, eng, fas, fin, fra, frm, gez, gle, grc, heb, hun, ita, kat, lat, lav, lit, mal, mul, nld, nor, oci, ota, pcd, pol, por, ron, rus, slk, slv, spa, srp, swe, syr, ukr, urd, xcl, yid |
| Scripts | Arab, Armn, Cyrl, Ethi, Geor, Grek, Hebr, Latn, Mlym, Syrc |
| Parameters | 0.69M |
| Derived from | mirror of 10.5281/zenodo.21788403 |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `045d350d5a7664054370539b87bab0e790724ee2` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/kraken-ppocrv6-tiny/upstream/045d350d5a7664054370539b87bab0e790724ee2/README.md) |

## Presets

- [`kraken-ppocrv6-tiny`](../presets/recognition/kraken-ppocrv6-tiny.md)
