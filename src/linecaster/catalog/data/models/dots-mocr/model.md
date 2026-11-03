---
schema: linecaster.model/1
id: dots-mocr
version: dots.mocr
source:
  kind: hf
  ref: rednote-hilab/dots.mocr
pins:
- revision: e539fbb52280393adc081b289ec597430a0f9031
  pinned: 2026-11-03
  files:
    model-00001-of-00002.safetensors: sha256:d8f4bc75340279da003609fe93f2eb02cc1a77087f5dfb6ba46c0980e1b4da81
    model-00002-of-00002.safetensors: sha256:0101b36fe6620ba135d4bb8efbbf275fc27b4363b10b7f632c058c0955f3dc4d
  card: upstream/e539fbb52280393adc081b289ec597430a0f9031/README.md
  card_sha256: sha256:381645b2bd63c2adff9d0c266f79e86b25657394c48c35e68551f1da73178259
license: MIT
languages:
- eng
- zho
- mul
scripts:
- Latn
- Hani
params: 3B
derived_from: []
---

dots.mocr is rednote-hilab's multilingual document parser, the successor to dots.ocr (arXiv 2603.13032): one
3B vision-language model that returns the page layout as a single JSON object (box, category and text per
element; formulas as LaTeX, tables as HTML, other text as Markdown), and can also parse charts and other
graphics into SVG code (a separate dots.mocr-svg variant is tuned for that). It needs `trust_remote_code`
(custom code); vLLM supports it natively. The repository has moved: linecaster pins `rednote-hilab/dots.mocr`,
which now redirects to `dots-studio/dots.mocr`. The card names no base model. Licence: MIT.
The upstream card is in `upstream/e539fbb52280393adc081b289ec597430a0f9031/README.md`.
