---
schema: linecaster.model/1
id: qianfan-ocr
version: Qianfan-OCR
source:
  kind: hf
  ref: baidu/Qianfan-OCR
pins:
- revision: 623bf5d20d446abdb36606aa4547cd0c18886fe5
  pinned: 2026-11-03
  files:
    examples/complex_document.jpg: sha256:1fa4abb1ce00765aa78c4714c71c65c57e46706564aa8f908e78d7c6fa51d07e
    examples/document.png: sha256:9ce20192fbe0d521d100521f1e0836c415debacb615b89f7658178420822e710
    examples/invoice.jpg: sha256:39ab057316af49c3d81c67b80a98d72727ce686ac68ae72ce71a05fc5297b856
    model-00001-of-00002.safetensors: sha256:e2a59915dd6a1c51ccb11be3addf4585fcf0840ac4f63f8e9fb629db58f8db6e
    model-00002-of-00002.safetensors: sha256:96805d61fbb9523fd27a09ab40451d04da09e9ba4b102341eac0184d8f82a0b1
    tokenizer.json: sha256:29d2b7ab0e0ecc235df0d7d87fc3ac9b90826605e42117898c653e436c97fd03
  card: upstream/623bf5d20d446abdb36606aa4547cd0c18886fe5/README.md
  card_sha256: sha256:807038e8b28d1662c5a9173ab392759d107b61f4cc02d35d3377e5e9682f1875
  license_file: upstream/623bf5d20d446abdb36606aa4547cd0c18886fe5/LICENSE
license: Apache-2.0
languages:
- mul
scripts: []
params: 4B
derived_from: []
---

Qianfan-OCR is the Baidu Qianfan team's 4B end-to-end document model (arXiv 2603.13398): direct
image-to-Markdown parsing plus prompt-driven tasks (layout analysis, table extraction, key information
extraction to JSON, document questions), with an optional "Layout-as-Thought" thinking phase that first emits
boxes, element types and reading order. It uses the Qianfan-VL architecture: a Qianfan-ViT encoder, a Qwen3-4B
language model and an MLP adapter; the card names no base checkpoint. It claims 192 languages without a list.
Licence: Apache-2.0 (some bundled third-party source files MIT; licence file copied as
`upstream/623bf5d20d446abdb36606aa4547cd0c18886fe5/LICENSE`).
The upstream card is in `upstream/623bf5d20d446abdb36606aa4547cd0c18886fe5/README.md`.
