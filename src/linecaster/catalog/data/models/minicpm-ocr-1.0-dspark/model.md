MiniCPM-OCR 1.0 DSpark is OpenBMB's DSpark speculative-decoding draft head for MiniCPM-OCR 1.0: a small
5-layer draft model (296,837,889 parameters, BF16) that proposes tokens the main model verifies. It is not an
OCR model on its own and must be paired with the matching `minicpm-ocr-1.0` checkpoint (vLLM usage in the
card). Its `d2t` tensor is delta-encoded and must be converted to absolute ids before use. The card front
matter gives `openbmb/MiniCPM-OCR-1.0` as base model (relation `finetune`). License: Apache-2.0.
The upstream card is in `upstream/31e3feaf80e0061cd6aa73db23480d2d691d6452/README.md`.
