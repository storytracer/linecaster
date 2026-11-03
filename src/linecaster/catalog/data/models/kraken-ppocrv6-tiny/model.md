---
schema: linecaster.model/1
id: kraken-ppocrv6-tiny
version: PP-OCRv6 (tiny)
source:
  kind: hf
  ref: small-models-for-glam/kraken-ppocrv6-tiny
pins:
- revision: 045d350d5a7664054370539b87bab0e790724ee2
  pinned: 2026-11-03
  files:
    tiny.safetensors: sha256:972700b1c72de14bdde028f9b06d77f13c88ec60da5e942bb9e57aca421fa361
  card: upstream/045d350d5a7664054370539b87bab0e790724ee2/README.md
  card_sha256: sha256:8f42e09524bb04980ae5d6c7fcc39986def1406352ca225ee4f75734a58d5050
  doi: 10.5281/zenodo.21788403
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
params: 0.69M
derived_from:
- ref: 10.5281/zenodo.21788403
  relation: mirror
---

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
