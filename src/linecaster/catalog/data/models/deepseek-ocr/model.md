---
schema: linecaster.model/1
id: deepseek-ocr
version: DeepSeek-OCR
source:
  kind: hf
  ref: deepseek-ai/DeepSeek-OCR
pins:
- revision: 9f30c71f441d010e5429c532364a86705536c53a
  pinned: 2026-11-03
  files:
    assets/fig1.png: sha256:3a709eb3fdb51cf6d8a546ffb8efe3c80bef61ae0183c2c8476a4c4a41efa3f1
    assets/show1.jpg: sha256:887e88e60e5833bc10a2cd7edb89ea7e6992abaae5e1550b027c611b8b8456f2
    assets/show2.jpg: sha256:81d08f7f33d9d39b95dd9b8162506659e6822d621b9829a208f3830c34c2b4d0
    assets/show3.jpg: sha256:cd24b0cfc7b6c0b1b34bd1aa55bc385e746298fdd82410db6c0d4e0bf69085c0
    assets/show4.jpg: sha256:2fe88eacc470c34d00225151372d3770948864f3d9cfaae16afa15b2432d7793
    model-00001-of-000001.safetensors: sha256:1169e7cdc28ff2fb6186556acb2175db148ad26a62097df4c45a17e523180d3f
  card: upstream/9f30c71f441d010e5429c532364a86705536c53a/README.md
  card_sha256: sha256:4f5e1d9e3b0c65c442f9c57c708e15d06ba9e277bb58db49bc9ba833f62f8f76
  license_file: upstream/9f30c71f441d010e5429c532364a86705536c53a/LICENSE
license: MIT
languages:
- mul
scripts: []
derived_from: []
---

DeepSeek-OCR ("Contexts Optical Compression", arXiv 2510.18234) is DeepSeek AI's document OCR model built
around visual-token compression. With the `<|grounding|>Convert the document to markdown.` prompt it returns
Markdown with grounding (layout type and box) markers; `Free OCR.` gives plain text. It needs
`trust_remote_code` (custom code) and is supported in upstream vLLM. The card says "multilingual" without a
list and names no base model. Licence: MIT (licence file copied as
`upstream/9f30c71f441d010e5429c532364a86705536c53a/LICENSE`).
The upstream card is in `upstream/9f30c71f441d010e5429c532364a86705536c53a/README.md`.
