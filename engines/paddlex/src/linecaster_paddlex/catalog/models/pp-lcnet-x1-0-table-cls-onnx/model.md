---
schema: linecaster.model/1
id: pp-lcnet-x1-0-table-cls-onnx
version: PP-LCNet_x1_0_table_cls
source:
  kind: hf
  ref: PaddlePaddle/PP-LCNet_x1_0_table_cls_onnx
pins:
- revision: 605f623b09f67a562bae77e781d5d5266f14905a
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:f8e4cb1b58a29bebd36852edcb238b53e0acefa75116a8a4db443f13dbc72b0b
  card: upstream/605f623b09f67a562bae77e781d5d5266f14905a/README.md
  card_sha256: sha256:84e4d0a0c7486a28794e27b1a4bf81fa05ada120df2423e3f6c5f687eae5f1ad
license: Apache-2.0
languages:
- eng
- zho
scripts: []
derived_from:
- ref: PaddlePaddle/PP-LCNet_x1_0_table_cls
  relation: converted
---

PaddleOCR's PP-LCNet_x1_0_table_cls: the wired/wireless table classifier of PaddleX's table pipeline. This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/PP-LCNet_x1_0_table_cls_onnx`, an export of `PaddlePaddle/PP-LCNet_x1_0_table_cls`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
