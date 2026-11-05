MiniCPM-OCR 1.0 is OpenBMB's 1.3B OCR model, the first OCR-specific model of the MiniCPM-V/o family: text,
tables, formulas, charts, seals and key information extraction, with Chinese and English as the primary
languages. Upstream's parsing pipeline pairs it with PP-DocLayoutV3 and assembles Markdown in reading order
(tables as HTML, formulas as LaTeX); field extraction returns JSON. The card says it is trained for OCR on top
of MiniCPM-V 4.6 (SigLIP vision encoder + Qwen3.5 language model). A DSpark speculative-decoding draft head is
published separately (`minicpm-ocr-1.0-dspark`). Licence: Apache-2.0.
The upstream card is in `upstream/a59a4acf215e34c6d73149e9eafdb88ed2086e39/README.md`.
