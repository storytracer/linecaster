---
schema: linecaster.model/1
id: lightonocr-3-4b
version: LightOnOCR-3-4B
source:
  kind: hf
  ref: lightonai/LightOnOCR-3-4B
pins:
- revision: b71010f095dc3735de7ee6b9969bff8f8f50b39a
  pinned: 2026-11-03
  files:
    lightonocr3_logo.png: sha256:768eee79d378518cfea9ed8d81ba3a53a0cff17ccf4b12c22a9e5ebedde32bcf
    model.safetensors: sha256:6b0dab74a2dab02d5b10ca56322255024ed8dca35c02746b42e9f296aaeb4e67
    tokenizer.json: sha256:87a7830d63fcf43bf241c3c5242e96e62dd3fdc29224ca26fed8ea333db72de4
  card: upstream/b71010f095dc3735de7ee6b9969bff8f8f50b39a/README.md
  card_sha256: sha256:4c56af1be12a620d0cadbb09976c0cd02fac5557f0f780be747d35bd6689fc54
license: Apache-2.0
languages: []
scripts: []
params: 4B
derived_from: []
---

LightOnOCR-3-4B is the largest model of LightOn's LightOnOCR-3 family of end-to-end OCR models. With an empty
prompt it transcribes the page as Markdown (as LightOnOCR-2 did); with the `grounding` prompt each block comes
with a label and a bounding box (0-1000 page coordinates), images get a short description and charts an HTML
table of their data. It uses the Qwen3.5 vision-language architecture (loaded with the Qwen3.5 classes,
thinking disabled); the card names no base checkpoint and its front matter lists no languages. Licence:
Apache-2.0, for research and commercial use.
The upstream card is in `upstream/b71010f095dc3735de7ee6b9969bff8f8f50b39a/README.md`.
