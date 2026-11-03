---
schema: linecaster.model/1
id: paddleocr-vl-1.6
version: PaddleOCR-VL-1.6
source:
  kind: hf
  ref: PaddlePaddle/PaddleOCR-VL-1.6
pins:
- revision: 66317acc4c9fc17bd154591ce650735cd2855f3e
  pinned: 2026-11-03
  files:
    model.safetensors: sha256:85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db
    tokenizer.json: sha256:c8a215a59183d0d0781adc33bacd3ce6162716f7fd568fb30234a74d69803a7d
    tokenizer.model: sha256:34ef7db83df785924fb83d7b887b6e822a031c56e15cff40aaf9b982988180df
  card: upstream/66317acc4c9fc17bd154591ce650735cd2855f3e/README.md
  card_sha256: sha256:72a5e7993e08bd616e9b3aa91b196fdb92952117aabada77788286b33bb3f11c
  license_file: upstream/66317acc4c9fc17bd154591ce650735cd2855f3e/LICENSE
license: Apache-2.0
languages:
- eng
- zho
- mul
scripts:
- Latn
- Hani
params: 0.9B
derived_from:
- ref: PaddlePaddle/PaddleOCR-VL-1.5
  relation: finetuned
---

PaddleOCR-VL-1.6 is PaddlePaddle's (Baidu) compact document parsing VLM (PaddleOCR-VL-1.6-0.9B, arXiv
2606.03264), built on PaddleOCR-VL-1.5 with the same architecture (ERNIE-4.5-based). The model recognises
text, tables, formulas, charts and seals and does text spotting; the PaddleOCR pipeline adds layout detection
and writes Markdown and JSON per page. It is a drop-in replacement for PaddleOCR-VL-1.5. The card front matter
lists English, Chinese and "multilingual". Licence: Apache-2.0 (licence file copied as
`upstream/66317acc4c9fc17bd154591ce650735cd2855f3e/LICENSE`).
The upstream card is in `upstream/66317acc4c9fc17bd154591ce650735cd2855f3e/README.md`.
