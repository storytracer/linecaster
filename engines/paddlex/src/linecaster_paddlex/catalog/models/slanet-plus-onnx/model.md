---
schema: linecaster.model/1
id: slanet-plus-onnx
version: SLANet_plus
source:
  kind: hf
  ref: PaddlePaddle/SLANet_plus_onnx
pins:
- revision: 7dbe640e127602bf506815e822c09758de73c482
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:7790c0c13ce064782c9d22ebeb16b4da8216f83d3ba576da962c106ef58386da
  card: upstream/7dbe640e127602bf506815e822c09758de73c482/README.md
  card_sha256: sha256:98b45ea81164d1e1a1dd82255207053b15cd6c69d922a1c5cf3387ce604d4b74
license: Apache-2.0
languages: []
scripts: []
derived_from:
- ref: PaddlePaddle/SLANet_plus
  relation: converted
---

PaddleOCR's SLANet_plus: a table structure recogniser (HTML structure tokens and cell boxes). This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/SLANet_plus_onnx`, an export of `PaddlePaddle/SLANet_plus`; the card does not say from which revision).
Licence and languages are the card's. The upstream card of the ONNX package is empty but for its licence.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
