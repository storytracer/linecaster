OXR-1.0's whole-page product: the vendor's all-in-one service (D-FINE layout, the OXR VLM per region and its
reading order, the vendor's `oxr` API assembling the page), one page per request to `POST /v1/parse/sync`. The
engine (`oxr.recognition.v1`, package `linecaster-services`) is its client in the pipeline's process.

- The service: an image built unmodified from the vendor's `docker/Dockerfile.allinone` at
  github.com/SoMarkAI/OXR@c1a1dcb3 (on the vendor's pinned `vllm/vllm-openai:v0.25.1`; the vendor's plugin and
  entrypoint require vLLM 0.25.1 and Transformers 5.13.1), by digest. `ServiceServer` downloads the model pin to
  `/models/oxr-model` (every pinned file checked, rather than mounting the weights) and starts the image's
  entrypoint, which serves vLLM on 8080 and the layout model on 8081 (loopback) and the API on 8000
  (`OXR_API_HOST` 127.0.0.1); the API answers `/docs` once both model services are ready.
- The request: the page as RGB, lossless PNG at its own size, as the multipart file, with `api_key` and one
  `output_formats` field each for markdown and json (httpx's encoding of a list). No `feature_config` or
  `element_formats`: the vendor's defaults (page headers and footers dropped, the overlap clean-up
  `full_overlap_dedupe` off).
- Kept verbatim: the API's Markdown (`extra["raw"]`, the text), its blocks (JSON) and warnings. An answer with a
  non-zero `code` is the page's error. The service reports no finish reason or token counts (its per-region cap is
  8,192 tokens in the vendor's configuration). The Markdown links the figure crops as images; removing the links is
  left to whoever reads the output.

License: the OXR License (Apache-2.0 with additional terms; see the model's page). Run on a 60-page sample of
historic print (NOTES.md, "Four more page readers"). Not run on HF Jobs.
