---
schema: linecaster.model/1
id: qwen3.5-9b
version: Qwen3.5-9B
source:
  kind: hf
  ref: Qwen/Qwen3.5-9B
pins:
- revision: c202236235762e1c871ad0ccb60c8ee5ba337b9a
  pinned: 2026-11-03
  files:
    model.safetensors-00001-of-00004.safetensors: sha256:db6f444b43d318c92f360a13a25561a6a65b10c0631b8ed305a426dbaa6c380e
    model.safetensors-00002-of-00004.safetensors: sha256:31c7d7e2dd5d207840b31cc59083c8f4c4718959149e0358c0364052bb9a0330
    model.safetensors-00003-of-00004.safetensors: sha256:7ec36ba3a4176a44c3c0876ad80c56a2f70c84bf008d82e9501df642f17dadec
    model.safetensors-00004-of-00004.safetensors: sha256:b62b0c4cd7e44edee103ee8f4fe225f246d5e768e07bfd5f25b63a8aa1fdd0c6
    tokenizer.json: sha256:5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42
  card: upstream/c202236235762e1c871ad0ccb60c8ee5ba337b9a/README.md
  card_sha256: sha256:c5f5a8c2dddab69cfbf05279235aa5fddb137939a06539c4c7637aa900fef6d0
  license_file: upstream/c202236235762e1c871ad0ccb60c8ee5ba337b9a/LICENSE
license: Apache-2.0
languages:
- mul
scripts: []
params: 9B
derived_from:
- ref: Qwen/Qwen3.5-9B-Base
  relation: finetuned
---

Qwen3.5-9B is the Qwen team's (Alibaba) post-trained 9B general vision-language model, not an OCR-specific
one, used for OCR by prompting. The card claims support for 201 languages and dialects without a list. It runs
in thinking mode by default. The card front matter gives `Qwen/Qwen3.5-9B-Base` as base model. Licence:
Apache-2.0 (licence file copied as `upstream/c202236235762e1c871ad0ccb60c8ee5ba337b9a/LICENSE`).
The upstream card is in `upstream/c202236235762e1c871ad0ccb60c8ee5ba337b9a/README.md`.
