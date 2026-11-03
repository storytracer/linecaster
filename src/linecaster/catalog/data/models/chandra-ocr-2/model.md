---
schema: linecaster.model/1
id: chandra-ocr-2
version: Chandra 2
source:
  kind: hf
  ref: datalab-to/chandra-ocr-2
pins:
- revision: af93b47dba1b47b6640c86ccf487ed2260ab9a09
  pinned: 2026-11-03
  files:
    handwritten_form.png: sha256:5915e7608cf8a857b5b846d56673e62164ba17c106917480e09703a0b5a189ce
    model.safetensors: sha256:0804568be9f099d6479fad9ed77a4da4611f3c1e7bc6e009af7dce45e8aa3847
    tokenizer.json: sha256:87a7830d63fcf43bf241c3c5242e96e62dd3fdc29224ca26fed8ea333db72de4
  card: upstream/af93b47dba1b47b6640c86ccf487ed2260ab9a09/README.md
  card_sha256: sha256:5eedfd77eb548b023400175628f98146414d2551aedfe3060c09d3e499f7368f
  license_file: upstream/af93b47dba1b47b6640c86ccf487ed2260ab9a09/LICENSE
license: AI Pubs Open RAIL-M License (Modified)
languages:
- mul
scripts: []
derived_from: []
---

Chandra 2 is Datalab's page OCR model: it turns page images and PDFs into Markdown, HTML or JSON with layout
information (tables, formulas, forms with checkboxes, handwriting, images with captions). The card claims
support for 90+ languages but gives no list, and names no base model. Licence: the card front matter says
`openrail`; the weights are under a modified OpenRAIL-M licence (the "AI Pubs Open RAIL-M License (Modified)",
copied as `upstream/af93b47dba1b47b6640c86ccf487ed2260ab9a09/LICENSE`): free for research, personal use and
small start-ups below a funding/revenue threshold, not for use in competition with Datalab's API; other
commercial use needs a separate licence. The code (the `chandra-ocr` package) is Apache-2.0.
The upstream card is in `upstream/af93b47dba1b47b6640c86ccf487ed2260ab9a09/README.md`.
