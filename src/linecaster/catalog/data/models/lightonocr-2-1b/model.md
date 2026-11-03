---
schema: linecaster.model/1
id: lightonocr-2-1b
version: LightOnOCR-2-1B
source:
  kind: hf
  ref: lightonai/LightOnOCR-2-1B
pins:
- revision: c97bd377f04481830395218fa8951df9deaba756
  pinned: 2026-11-03
  files:
    benchmark.png: sha256:588f08c83690be0564e0275a369911b17fae02c4bfaac46a243323bd4efe23b8
    lightonocr-banner.png: sha256:e32c44dc131d4e07b344a41bb9651eb97ce4ce73d4e78463821267467810462c
    model.safetensors: sha256:cbe12d0831cca119facce91268fc7c5fb72babdf919a6e352e3131bda85c8fbb
    tokenizer.json: sha256:f54b55fa0c3aba0c91ce09ea79ae4e62da24e2a1a630f96c4bae34aba25e234a
  card: upstream/c97bd377f04481830395218fa8951df9deaba756/README.md
  card_sha256: sha256:92a1e0f0a25403e345510cd78256caa86c9c5db89625663011b7a953cef212bf
license: Apache-2.0
languages:
- eng
- fra
- deu
- spa
- ita
- nld
- por
- swe
- dan
- zho
- jpn
scripts:
- Latn
- Hani
- Jpan
params: 1B
derived_from: []
---

LightOnOCR-2-1B is LightOn's end-to-end 1B vision-language OCR model (arXiv 2601.14251): it turns a page image
into clean, naturally ordered text (with LaTeX for maths) without a separate layout pipeline. It is the
RLVR-refined variant of the LightOnOCR-2 family; LightOnOCR-2-1B-base (for fine-tuning) and bbox variants that
also predict image boxes are separate repositories. The card does not name the checkpoint it was trained from,
so `derived_from` is empty. Licence: Apache-2.0.
The upstream card is in `upstream/c97bd377f04481830395218fa8951df9deaba756/README.md`.
