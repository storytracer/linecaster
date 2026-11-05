Unlimited-OCR ("Unlimited OCR Works", arXiv 2606.23050) is Baidu's long-horizon document parser, which the
card presents as pushing DeepSeek-OCR one step further: one pass over a single page (`document parsing.`) or a
multi-page document or PDF (`Multi page parsing.`). The output is text blocks tagged with `<|det|>type
[bbox]<|/det|>` grounding markers. It needs `trust_remote_code` (custom code); vLLM and SGLang are supported.
The card says "multilingual" without a list and names no base checkpoint. License: MIT (license file copied as
`upstream/07dea832e22aefee32ad281d4b80551282e1c168/LICENSE`).
The upstream card is in `upstream/07dea832e22aefee32ad281d4b80551282e1c168/README.md`.
