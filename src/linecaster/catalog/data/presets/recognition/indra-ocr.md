Indra OCR, as the BHL OCR board's driver runs it: the `indra-ocr` package (1.1.2) on the CPU, in the pipeline's
process, each page through the package's own image path (`Converter.convert(path)`, the call the `indra-ocr` command
makes), so decoding to grayscale, orientation, deskew, detection, recognition, layout and reading order are the
package's. The engine is `indra.recognition.v1` (package `linecaster-indra`).

- Settings: `indra_ocr.load()`'s defaults, written out: mode `auto` (an image is OCR'd), `furniture` false (page
  headers and footers dropped from the Markdown), `math` false, `dpi` 200 (PDFs only), one ONNX Runtime thread per
  task (the package's own workers are single-threaded, one per core: run as many tasks as cores).
- The models: the pin of `datalab-to/indra-ocr` at the tag `v1.1.0`, the model set `indra-ocr` 1.1.2 is built
  against (`indra_ocr/models.py: HF_REVISION`), every pinned file checked.
- The page goes to the package as a lossless RGB PNG (the board's driver wrote the dataset's own bytes); the package
  reads it in grayscale with OpenCV. The pipeline script resolves OpenCV 4.11 (surya-ocr's pin, in the same
  environment); the board's run resolved the newest release of its day.
- Kept verbatim: the package's Markdown (`extra["raw"]`, the text), with its layout blocks, rotation and skew. A page
  the package reports as failed is the page's error; an empty Markdown (a blank leaf) is a transcription without
  text. The board strips the outer whitespace only.

Weights: modified OpenRAIL-M (see the model's page). Not yet run in linecaster (NOTES.md).
