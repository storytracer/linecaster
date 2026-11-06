Falcon-OCR's whole-page product, as the BHL OCR board's driver runs it: the vendor's pipeline service (layout
detection, one request per crop with a category prompt, the vendor's Markdown assembly) in the vendor's image, one
page per request to `POST /falconocr/parse`. The engine (`falcon.recognition.v1`, package `linecaster-services`) is
its client in the pipeline's process.

- The service: `ServiceServer` starts the image's own single-GPU entrypoint (`/app/entrypoint_single.sh`: vLLM with
  the model on port 8000, the pipeline on 5002, both on GPU 0 of the container) and waits until both answer
  `/health`. The image's entrypoint binds both to every address of the container. The weights are the image's own
  (`/models/Falcon-OCR`, the model pin's files); the image digest fixes what runs.
- The request: the page as RGB, scaled down (LANCZOS) so its longest side is at most 2,048 px, JPEG quality 95, as a
  data URI, with `skip_layout` false (the vendor's full-page path; the direct VLM path is off-label).
- Kept verbatim: `markdown_result` (`extra["raw"]`, the text) and the layout regions (`json_result`). The service
  reports no finish reason, so no loop can be counted; its output tokens are the step's `completion_tokens`. The
  board strips leaked `>>UNUSED_N<<` vocabulary tokens in its harness (`falcon_strip_unused_tokens`).
- The image has Python 3.10 and no uv: on HF Jobs the pipeline cannot run inside it as it is (not tried).

Apache-2.0. Run on the 60-page sample (NOTES.md, "The four board models the catalog lacked"): CER reading 0.0775 for linecaster's run on an RTX A6000 against
0.1301 for the board's own outputs on the same pages (the Markdown identical on 47 of 60 pages; one page the board's
run looped on carries the gap). Not run on HF Jobs.
