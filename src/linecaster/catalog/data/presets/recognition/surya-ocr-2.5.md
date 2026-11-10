Surya OCR 2.5 as its package runs it: the `surya-ocr` package (0.23.0, the release that shipped with the checkpoint)
and its full-page path, the call its `surya_ocr` command makes (`RecognitionPredictor(manager)([page],
full_page=True)`), with the package's parser, blank-region filter and block-mode fallback. The engine
(`surya.recognition.v1`, package `linecaster-surya`) reimplements none of it.

- The server: the package would start `vllm/vllm-openai:v0.25.1` with `docker run`. `ServiceServer` starts `vllm
  serve` on the pinned checkpoint instead (fetched, every pinned file checked, and served under the package's model
  name `datalab-to/surya-ocr-2.5`), with the flags the package's launcher passes for `VLLM_GPU_TYPE=a100-80` (an
  A100 80 GB): `--max-num-seqs 104 --max-num-batched-tokens 16384`, the package's dtype, model length, memory share,
  prefix caching and image limits; no MTP flag (the checkpoint has no MTP head). The engine attaches through
  `SURYA_INFERENCE_URL`, the package's own attach path. The image is the package's pin, by digest.
- Every package setting is its default: full-page mode, 12,288 full-page tokens, guided layout JSON,
  `SURYA_FULLPAGE_REGEN` off (Datalab's own benchmark harness turns it on; the preset keeps the shipped default).
  The page goes in as an RGB image at its own size; the package scales it to fit 3072 x 2048 px.
- The package and vLLM need separate environments (surya-ocr pins OpenCV 4.11, vLLM needs 4.13 or later): vLLM is
  the image's, surya-ocr the pipeline script's. surya-ocr declares `pillow<11`; the pipeline script overrides it with
  linecaster's Pillow pin (12.3.0).
- Kept verbatim: the page's blocks as JSON (`extra["raw"]`: label, raw label, reading order, HTML, skipped, error,
  confidence, box). Rendering them to Markdown (with chandra's HTML converter, page headers and footers kept) is
  left to whoever reads the output. `finish_reason` is `length` when the page keeps a capped block's partial HTML; a
  failed block request is the page's error.

Weights: modified OpenRAIL-M (see the model's page). Run against a reference implementation's outputs on a 60-page
sample of historic print (NOTES.md, "Four more page readers"). Not run on HF Jobs.
