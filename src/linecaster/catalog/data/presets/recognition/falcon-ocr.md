Falcon-OCR's whole-page product: the vendor's pipeline service (layout detection, one request per crop with a
category prompt, the vendor's Markdown assembly) in the vendor's image, one page per request to
`POST /falconocr/parse`. The engine (`falcon.recognition.v1`, package `linecaster-services`) is its client in the
pipeline's process.

- The service: `ServiceServer` starts the image's own single-GPU entrypoint (`/app/entrypoint_single.sh`: vLLM with
  the model on port 8000, the pipeline on 5002, both on GPU 0 of the container) and waits until both answer
  `/health`. The image's entrypoint binds both to every address of the container. The weights are the image's own
  (`/models/Falcon-OCR`, the model pin's files); the image digest fixes what runs.
- The request: the page as RGB, scaled down (LANCZOS) so its longest side is at most 2,048 px, JPEG quality 95, as a
  data URI (linecaster's choice of payload), with `skip_layout` false (the vendor's full-page path; the direct VLM
  path is off-label).
- Kept verbatim: `markdown_result` (`extra["raw"]`, the text) and the layout regions (`json_result`). The service
  reports no finish reason, so no loop can be counted; its output tokens are the step's `completion_tokens`. The
  Markdown can contain leaked `>>UNUSED_N<<` vocabulary tokens; removing them is left to whoever reads the output.
- The image has Python 3.10 and no uv: on HF Jobs the pipeline cannot run inside it as it is (not tried).

Apache-2.0. Run against a reference implementation's outputs on a 60-page sample of historic print (NOTES.md,
"Four more page readers"). Not run on HF Jobs.
