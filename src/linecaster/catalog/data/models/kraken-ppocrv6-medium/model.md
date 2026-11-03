---
schema: linecaster.model/1
id: kraken-ppocrv6-medium
version: PP-OCRv6 (medium)
source:
  kind: hf
  ref: small-models-for-glam/kraken-ppocrv6-medium
pins:
- revision: f7fd70f3fd22b615f41bada4674ac2462f938339
  pinned: 2026-11-03
  files:
    medium.safetensors: sha256:15313b51ace64cbfa81f8f6ef25ad64f04e5a6fb7f7823e67b107527bc081ac9
  card: upstream/f7fd70f3fd22b615f41bada4674ac2462f938339/README.md
  card_sha256: sha256:50316120f86965ed02aad7bae0e2d74fa87753d2e3824c8fa402a247e2fc9172
  doi: 10.5281/zenodo.21788410
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
params: 15.92M
derived_from:
- ref: 10.5281/zenodo.21788410
  relation: mirror
---

Benjamin Kiessling's PP-OCRv6 (medium) line recogniser for kraken (ALMAnaCH, Inria Paris), as mirrored byte for
byte on the Hugging Face Hub by Small Models for GLAM; the canonical release is the Zenodo record
[10.5281/zenodo.21788410](https://doi.org/10.5281/zenodo.21788410), which is provenance only: linecaster always downloads from the mirror (Zenodo
throttles). Licence, languages (44 plus `mul`) and scripts are the card's.

The card describes the model as trained from scratch by kraken's author on line images of historical,
contemporary and born-digital documents, handwritten and printed, on an architecture adapted from PaddlePaddle's
PP-OCRv6 (128 px line height, uncapped line width, Adam+Muon); it is not a conversion of PaddleOCR's
`PP-OCRv6_medium_rec` weights, so `derived_from` names only the mirror relation. kraken's own code runs it
(`kraken.recognition.v1`), on torch; the model was trained in bf16-mixed, which is why linecaster's presets run it
in bf16-mixed on CUDA.
