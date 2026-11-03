---
schema: linecaster.model/1
id: minicpm-ocr-1.0
version: MiniCPM-OCR 1.0
source:
  kind: hf
  ref: openbmb/MiniCPM-OCR-1.0
pins:
- revision: a59a4acf215e34c6d73149e9eafdb88ed2086e39
  pinned: 2026-11-03
  files:
    model.safetensors: sha256:83f4e433b044fd23f9ea7eb3acbc7d59e4fe11a1fdf3c3129b7021d0ab4f8fd4
    tokenizer.json: sha256:6269eb38f25c20c0f2ba676577f2e5603f79eab3be573dfdaa727ca6eeb5522d
  card: upstream/a59a4acf215e34c6d73149e9eafdb88ed2086e39/README.md
  card_sha256: sha256:b6f5a430815f5331459866889865f1670d5680960a544d90d106b661524f3802
license: Apache-2.0
languages:
- eng
- zho
scripts:
- Latn
- Hani
params: 1.3B
derived_from:
- ref: openbmb/MiniCPM-V-4.6
  relation: finetuned
---

MiniCPM-OCR 1.0 is OpenBMB's 1.3B OCR model, the first OCR-specific model of the MiniCPM-V/o family: text,
tables, formulas, charts, seals and key information extraction, with Chinese and English as the primary
languages. Upstream's parsing pipeline pairs it with PP-DocLayoutV3 and assembles Markdown in reading order
(tables as HTML, formulas as LaTeX); field extraction returns JSON. The card says it is trained for OCR on top
of MiniCPM-V 4.6 (SigLIP vision encoder + Qwen3.5 language model). A DSpark speculative-decoding draft head is
published separately (`minicpm-ocr-1.0-dspark`). Licence: Apache-2.0.
The upstream card is in `upstream/a59a4acf215e34c6d73149e9eafdb88ed2086e39/README.md`.
