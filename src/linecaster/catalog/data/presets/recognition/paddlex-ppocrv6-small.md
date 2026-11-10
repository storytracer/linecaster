PaddleOCR's own PP-OCRv6 small recognizer on PaddleX's ONNX Runtime engine. Lines are cut as PaddleX's OCR
pipeline cuts them (minimum-area rectangle of the polygon, warped upright), sorted by aspect ratio and read
`batch_size` 8 at a time, as PaddleX's pipeline does. Words: the text split at whitespace, placed along the line by
the CTC columns of their characters (PaddleX's `return_word_box`); PaddleX gives no per-word confidence.

Compared with kraken's port of the model family in the same modular pipeline, it read worse on most volumes of a
sample of historic print (NOTES.md, "More line recognizers: PaddleX PP-OCRv6 and Tesseract"); the likely difference
is the line image (kraken's polygon-based extraction against PaddleX's rectangle warp). Not investigated further.
