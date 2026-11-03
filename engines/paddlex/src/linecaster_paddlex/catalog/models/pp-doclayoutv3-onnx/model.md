---
schema: linecaster.model/1
id: pp-doclayoutv3-onnx
version: PP-DocLayoutV3
source:
  kind: hf
  ref: PaddlePaddle/PP-DocLayoutV3_onnx
pins:
- revision: 46bbdf188bb0a772c08aed74882ce7e51a8f1ea6
  pinned: 2026-11-03
  files:
    inference.onnx: sha256:45bf71750b00739a41fc209f132eb104a4d6b5bb29483c9078164d8b87cf28ba
  card: upstream/46bbdf188bb0a772c08aed74882ce7e51a8f1ea6/README.md
  card_sha256: sha256:23d6d398442ed0d175dbd9b23ef3607d47ae20fa90cd0274b6719540250fb78b
license: Apache-2.0
languages:
- eng
- zho
- mul
scripts: []
derived_from:
- ref: PaddlePaddle/PP-DocLayoutV3
  relation: converted
---

PaddleOCR's PP-DocLayoutV3, the layout model of PaddleOCR-VL-1.5, in the ONNX package PaddleX downloads for its
ONNX Runtime engine (`PaddlePaddle/PP-DocLayoutV3_onnx`, an export of `PaddlePaddle/PP-DocLayoutV3`; the card
does not say from which revision). 25 classes (`inference.yml`), region polygons and a learned reading order:
PaddleX returns the boxes sorted by the model's order. Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
