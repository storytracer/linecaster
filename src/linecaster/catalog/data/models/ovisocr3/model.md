---
schema: linecaster.model/1
id: ovisocr3
version: OvisOCR3
source:
  kind: hf
  ref: ATH-MaaS/OvisOCR3
pins:
- revision: 5f6ce6932efee9ec10c30746db55bd780214b7fd
  pinned: 2026-11-03
  files:
    assets/crosspage_recursive.png: sha256:1a5beede5c098bfdcb091790c3d5ec36c0e2ce50827eb0ae9b92325d60db1afe
    assets/ovisocr3_performance_overview.png: sha256:dc3715147ca9591d7b235f81847a8bbe70c3947e4d0b82f75d198cc747464ecd
    model.safetensors: sha256:aa2311c6b22b07cf3afe9aac6e8bcb02a2b19dd8671b2a91d0b144071577e600
    tokenizer.json: sha256:5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42
  card: upstream/5f6ce6932efee9ec10c30746db55bd780214b7fd/README.md
  card_sha256: sha256:71668558db69ac7fcd29a30ccecb4effa9df48efd2757b750742c6e22229bfc6
  license_file: upstream/5f6ce6932efee9ec10c30746db55bd780214b7fd/LICENSE
license: Apache-2.0
languages: []
scripts: []
params: 0.8B
derived_from:
- ref: Qwen/Qwen3.5-0.8B
  relation: finetuned
---

OvisOCR3 is ATH-MaaS's unified 0.8B model for OCR and document understanding, the successor to OvisOCR2. Task
prompts select document parsing (Markdown with LaTeX formulas and HTML tables, structured JSON with box,
category and content, or layout JSON without text), general OCR, key information extraction, figure captioning
and cross-page table reconstruction. It is built on Qwen3.5-0.8B (continued pretraining, mid-training,
on-policy distillation, RL). The card claims no languages. Licence: Apache-2.0 (licence file copied as
`upstream/5f6ce6932efee9ec10c30746db55bd780214b7fd/LICENSE`).
The upstream card is in `upstream/5f6ce6932efee9ec10c30746db55bd780214b7fd/README.md`.
