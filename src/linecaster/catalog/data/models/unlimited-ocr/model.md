---
schema: linecaster.model/1
id: unlimited-ocr
version: Unlimited-OCR
source:
  kind: hf
  ref: baidu/Unlimited-OCR
pins:
- revision: 07dea832e22aefee32ad281d4b80551282e1c168
  pinned: 2026-11-03
  files:
    Unlimited-OCR.pdf: sha256:d4cc0b2e98f53d9165e63af925519cccbf80ecc6f047973e3f9b2bdd84474a8b
    assets/Unlimited-OCR.png: sha256:77063289aecfedea40d90c94dac3bc5d57f42f65d2a988183bb665a69e26ce95
    assets/long-horizon-ocr.gif: sha256:d4ba8964d33ffa3a3584d4a1259625ab659c02190e9655ddd51793d28307d962
    model-00001-of-000001.safetensors: sha256:2bc48a7a110061ea58fff65d3169367eebe3aee371ca6968dc2219c1b2855fc6
    wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl: sha256:2644a1f349c55f0ca822e70a70679c98475754ec4722c3be1b18a72bac477cd5
  card: upstream/07dea832e22aefee32ad281d4b80551282e1c168/README.md
  card_sha256: sha256:4f573db255db5262bfe2ea92e459bfc11635a456f210e3a96289bb9605077a55
  license_file: upstream/07dea832e22aefee32ad281d4b80551282e1c168/LICENSE
license: MIT
languages:
- mul
scripts: []
derived_from: []
---

Unlimited-OCR ("Unlimited OCR Works", arXiv 2606.23050) is Baidu's long-horizon document parser, which the
card presents as pushing DeepSeek-OCR one step further: one pass over a single page (`document parsing.`) or a
multi-page document or PDF (`Multi page parsing.`). The output is text blocks tagged with `<|det|>type
[bbox]<|/det|>` grounding markers. It needs `trust_remote_code` (custom code); vLLM and SGLang are supported.
The card says "multilingual" without a list and names no base checkpoint. Licence: MIT (licence file copied as
`upstream/07dea832e22aefee32ad281d4b80551282e1c168/LICENSE`).
The upstream card is in `upstream/07dea832e22aefee32ad281d4b80551282e1c168/README.md`.
