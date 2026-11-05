LightOnOCR-3-0.8B is the smallest model of LightOn's LightOnOCR-3 family of end-to-end OCR models, with the
same features as the 4B: an empty prompt gives the page as Markdown, the `grounding` prompt adds a label and a
bounding box (0-1000 page coordinates) per block, image descriptions and chart data as HTML tables. It uses
the Qwen3.5 vision-language architecture (loaded with the Qwen3.5 classes, thinking disabled); the card names
no base checkpoint. Its front matter lists English only. Licence: Apache-2.0, for research and commercial use.
The upstream card is in `upstream/36d8636925327c671bd8e479c517a004f7566bd9/README.md`.
