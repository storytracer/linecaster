LightOnOCR-3-0.8B in its grounding mode on whole pages, following the model card's "Prompt Modes": every block of
the page comes back with a label and a box, so page furniture (running heads, page numbers) is labelled instead of
written into the text. Otherwise identical to `lightonocr-3-0.8b@3` (revision, image size, sampling, repair, serve flags).

- The page image, then the text part `grounding` (the card's vLLM call); the image as for transcription: RGB,
  `thumbnail((2048, 2048))`, PNG.
- Sampling from the card's grounding call: temperature 0.2, top_p 0.9, max_tokens 4096 (the card's, although
  grounding writes about 25 % more tokens than transcription; a different cap waits for a measurement).
- The completion: a placeholder `![label](x1,y1,x2,y2)` before each block, its box in 0-1000 page coordinates, then
  its content (Markdown; tables HTML). linecaster makes one region per block (adapter `lighton-ocr-3-grounding`,
  `linecaster.adapters.lighton_grounding`), the boxes scaled to the page image read, in the order emitted:
  `header` and `footer` are `page_header` and `page_footer`; `page_number` is `page_header` in the top 15 % of the
  page and `page_footer` below (as PP-DocLayout's page numbers); `aside_text` is body `text`; `title` is
  `section_header` at the level of its `#`. The model's label stays `raw_label`.
- The full text (`verbatim_txt`) keeps the furniture; the body texts (`readable_txt`, `readable_md`) leave it out.
- What the model writes about a figure (`image`, `header_image`, `footer_image`: a description; `chart`: data read
  off it) is no printed text: kept in the region's `extra["generated"]`, in no text of the page.
- The raw completion is stored verbatim (`extra["raw"]`). Experimental.

Editions: 1 is the first.
