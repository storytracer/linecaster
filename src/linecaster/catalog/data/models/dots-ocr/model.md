dots.ocr is rednote-hilab's multilingual document layout parser: a single vision-language model on a 1.7B LLM
that returns the page layout as one JSON object (box, category and text per element, in reading order;
formulas as LaTeX, tables as HTML, other text as Markdown). Other prompts give layout only or plain OCR. It
needs `trust_remote_code` (custom code). The card gives the LLM size but no total parameter count and does not
name the base LLM (it thanks Qwen2.5-VL and aimv2). The repository has moved: linecaster pins
`rednote-hilab/dots.ocr`, which now redirects to `dots-studio/dots.ocr`. Licence: MIT.
The upstream card is in `upstream/c0111ce6bc07803dbc267932ffef0ae3a51dc951/README.md`.
