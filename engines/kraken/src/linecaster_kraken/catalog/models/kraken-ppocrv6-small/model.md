---
schema: linecaster.model/1
id: kraken-ppocrv6-small
version: PP-OCRv6 (small)
source:
  kind: hf
  ref: small-models-for-glam/kraken-ppocrv6-small
pins:
- revision: 49c249bf81d95ab2c5f699638d066f7935da6f16
  pinned: 2026-11-03
  files:
    small.safetensors: sha256:3108259779f5abfed3908a1c9eafba64d17e4a2a169368c539ecfeff04c018f3
  card: upstream/49c249bf81d95ab2c5f699638d066f7935da6f16/README.md
  card_sha256: sha256:b70b866b2f8e165f5dad31d5b5d617bad4b88eb0774a3bd1524f5b73882f0cf0
  doi: 10.5281/zenodo.21788405
license: Apache-2.0
languages:
- ara
- cat
- ces
- chu
- cos
- dan
- deu
- dum
- eng
- fas
- fin
- fra
- frm
- gez
- gle
- grc
- heb
- hun
- ita
- kat
- lat
- lav
- lit
- mal
- mul
- nld
- nor
- oci
- ota
- pcd
- pol
- por
- ron
- rus
- slk
- slv
- spa
- srp
- swe
- syr
- ukr
- urd
- xcl
- yid
scripts:
- Arab
- Armn
- Cyrl
- Ethi
- Geor
- Grek
- Hebr
- Latn
- Mlym
- Syrc
params: 3.24M
derived_from:
- ref: 10.5281/zenodo.21788405
  relation: mirror
---

Benjamin Kiessling's PP-OCRv6 (small) line recogniser for kraken (ALMAnaCH, Inria Paris), as mirrored byte for
byte on the Hugging Face Hub by Small Models for GLAM; the canonical release is the Zenodo record
[10.5281/zenodo.21788405](https://doi.org/10.5281/zenodo.21788405), which is provenance only: linecaster always downloads from the mirror (Zenodo
throttles). Licence, languages (44 plus `mul`) and scripts are the card's.

The card describes the model as trained from scratch by kraken's author on line images of historical,
contemporary and born-digital documents, handwritten and printed, on an architecture adapted from PaddlePaddle's
PP-OCRv6 (128 px line height, uncapped line width, Adam+Muon); it is not a conversion of PaddleOCR's
`PP-OCRv6_small_rec` weights, so `derived_from` names only the mirror relation. kraken's own code runs it
(`kraken.recognition/1`), on torch; the model was trained in bf16-mixed, which is why linecaster's presets run it
in bf16-mixed on CUDA.
