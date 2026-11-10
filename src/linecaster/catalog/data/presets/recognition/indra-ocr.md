Indra OCR as its package runs it: `indra-ocr` (1.1.2) on the CPU, in the pipeline's process, each page through the
package's own image path (`Converter.convert(path)`, the call the `indra-ocr` command makes), so decoding to
grayscale, orientation, deskew, detection, recognition, layout and reading order are the package's. The engine is
`indra.recognition.v1` (package `linecaster-indra`).

- Settings: `indra_ocr.load()`'s defaults, written out: mode `auto` (an image is OCR'd), `furniture` false (page
  headers and footers dropped from the Markdown), `math` false, `dpi` 200 (PDFs only), one ONNX Runtime thread per
  task (the package's own workers are single-threaded, one per core: run as many tasks as cores).
- The models: the pin of `datalab-to/indra-ocr` at the tag `v1.1.0`, the model set `indra-ocr` 1.1.2 is built
  against (`indra_ocr/models.py: HF_REVISION`), every pinned file checked.
- The page goes to the package as its file's bytes, as the reader brought them (the engine's `image_input` is
  `bytes`), as the `indra-ocr` command reads a file; the package decodes it in grayscale with OpenCV. The pipeline
  script resolves OpenCV 4.11 (surya-ocr's pin, in the same environment).
- Kept verbatim: the package's Markdown (`extra["raw"]`, the text), with its layout blocks, rotation and skew. A page
  the package reports as failed is the page's error; an empty Markdown (a blank leaf) is a transcription without
  text.

Weights: modified OpenRAIL-M (see the model's page). Run against a reference implementation's outputs on a 60-page
sample of historic print (NOTES.md, "Four more page readers").
