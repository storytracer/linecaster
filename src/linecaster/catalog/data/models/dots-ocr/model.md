---
schema: linecaster.model/1
id: dots-ocr
version: dots.ocr
source:
  kind: hf
  ref: rednote-hilab/dots.ocr
pins:
- revision: c0111ce6bc07803dbc267932ffef0ae3a51dc951
  pinned: 2026-11-03
  files:
    model-00001-of-00002.safetensors: sha256:ea1d532184f3adf5cbcfcc00b2cf5b2abfa6fe182768a3ae63d441a9b5fc99ac
    model-00002-of-00002.safetensors: sha256:26ab1ec6c8b4e4116befbd59af42159f1dbcb0ad0c045a15e890bb2f6e8b0dae
  card: upstream/c0111ce6bc07803dbc267932ffef0ae3a51dc951/README.md
  card_sha256: sha256:e59f00e56945936a65c74cf53333a9051715ba45e91da0b7d86cd05f5964c2eb
license: MIT
languages:
- eng
- zho
- mul
scripts:
- Latn
- Hani
derived_from: []
---

dots.ocr is rednote-hilab's multilingual document layout parser: a single vision-language model on a 1.7B LLM
that returns the page layout as one JSON object (box, category and text per element, in reading order;
formulas as LaTeX, tables as HTML, other text as Markdown). Other prompts give layout only or plain OCR. It
needs `trust_remote_code` (custom code). The card gives the LLM size but no total parameter count and does not
name the base LLM (it thanks Qwen2.5-VL and aimv2). The repository has moved: linecaster pins
`rednote-hilab/dots.ocr`, which now redirects to `dots-studio/dots.ocr`. Licence: MIT.
The upstream card is in `upstream/c0111ce6bc07803dbc267932ffef0ae3a51dc951/README.md`.
