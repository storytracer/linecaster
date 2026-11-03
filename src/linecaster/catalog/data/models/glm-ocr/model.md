---
schema: linecaster.model/1
id: glm-ocr
version: GLM-OCR
source:
  kind: hf
  ref: zai-org/GLM-OCR
pins:
- revision: ca5d8b3e287e52589e37c28385d9655ee4372f9d
  pinned: 2026-11-03
  files:
    model.safetensors: sha256:a16eb0de98d199293371c560f95f83130d2a2c9612449df16839f08ff9498815
  card: upstream/ca5d8b3e287e52589e37c28385d9655ee4372f9d/README.md
  card_sha256: sha256:e8e84b75857428ba5c152b561b5af0e607c991240ecf8dfa31cb616f8a1c61ff
license: MIT
languages:
- zho
- eng
- fra
- spa
- rus
- deu
- jpn
- kor
scripts:
- Hani
- Latn
- Cyrl
- Jpan
- Kore
params: 0.9B
derived_from: []
---

GLM-OCR is Z.ai's (`zai-org`) 0.9B OCR model for complex documents, on the GLM-V encoder-decoder architecture:
a CogViT vision encoder, a light connector and a GLM-0.5B language decoder (arXiv 2603.10910). It recognises
text, formulas and tables (Markdown output) and does schema-driven information extraction to JSON. Upstream
runs it in a two-stage pipeline: PP-DocLayoutV3 layout analysis, then parallel recognition of the regions. The
card names no base checkpoint. Licence: MIT for the model; PP-DocLayoutV3 in the full pipeline is Apache-2.0.
The upstream card is in `upstream/ca5d8b3e287e52589e37c28385d9655ee4372f9d/README.md`.
