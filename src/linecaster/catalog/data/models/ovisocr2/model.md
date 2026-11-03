---
schema: linecaster.model/1
id: ovisocr2
version: OvisOCR2
source:
  kind: hf
  ref: ATH-MaaS/OvisOCR2
pins:
- revision: 65c619d374b55d4152e85150fc1b003700bc1f0c
  pinned: 2026-11-03
  files:
    model.safetensors: sha256:9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009
    performance.png: sha256:771a452b0072234bd09984f9702f751ddfbf3a58e5aca6286ce493d1d1d0dfdc
    performance_omnidocbench_v16.png: sha256:f67200bf177cc8fc14774f1895386aab06ca544bf0a672d0789778a5fb15f087
    performance_puredocbench.png: sha256:65c8a4ce9391f29ab35d2c4e379d0aeac38a315409c0ff4dd210f3627a3cc1a7
    tokenizer.json: sha256:5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42
  card: upstream/65c619d374b55d4152e85150fc1b003700bc1f0c/README.md
  card_sha256: sha256:03c876522bb7be5e8410eed758854dbb933204935afa898758d929c10725945d
  license_file: upstream/65c619d374b55d4152e85150fc1b003700bc1f0c/LICENSE
license: Apache-2.0
languages: []
scripts: []
params: 0.8B
derived_from:
- ref: Qwen/Qwen3.5-0.8B
  relation: finetuned
---

OvisOCR2 is a compact 0.8B end-to-end page parser published by ATH-MaaS (arXiv 2607.13639): given a page image
it writes one Markdown document in natural reading order, covering text, formulas, tables and visual regions
(as `<img>` tags carrying the region's box). It is post-trained from Qwen3.5-0.8B (SFT, RL and on-policy
distillation). The card claims no languages. Licence: Apache-2.0 (licence file copied as
`upstream/65c619d374b55d4152e85150fc1b003700bc1f0c/LICENSE`).
The upstream card is in `upstream/65c619d374b55d4152e85150fc1b003700bc1f0c/README.md`.
