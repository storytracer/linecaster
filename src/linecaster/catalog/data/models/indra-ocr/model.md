Indra OCR is Datalab's CPU OCR pipeline: small ONNX models (detector, orientation, script classifier, four line
recognizers, layout and reading order; 7.3M parameters in all, about 1.25M in the Latin recognizer `rec.onnx`) run
by ONNX Runtime through the `indra-ocr` package, which writes Markdown, text or JSON with boxes. The pin is the
model set `v1.1.0`, the tag `indra-ocr` 1.1.2 is built against (`indra_ocr/models.py: HF_REVISION`). The card
reports 95 measured languages; `languages` says `mul` because the card's front matter mixes ISO 639-1 and 639-3
codes. License: the card front matter says `openrail`; the weights are under a modified OpenRAIL-M license (the "AI
Pubs Open RAIL-M License (Modified)", copied as `upstream/bd02167fdf2005a19962cc15188f8496a2c87d3b/LICENSE`): free
for research and personal use, and for organizations below USD 20,000,000 of revenue and of funding; not for use by
anyone offering a product or service that competes with Datalab's; other commercial use needs a separate license.
The code (the `indra-ocr` package) is Apache-2.0.
The upstream card is in `upstream/bd02167fdf2005a19962cc15188f8496a2c87d3b/README.md`.
