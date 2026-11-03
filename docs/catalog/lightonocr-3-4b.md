# lightonocr-3-4b

*Edition 1 · page · experimental*

LightOnOCR-3-4B on whole pages, as the BHL OCR board ran it (one driver for both LightOnOCR-3 rows,
following the model card; the two presets differ only in the checkpoint).

- The page image only, no text part (the card's transcription call; grounding is another output, not run).
- RGB, `thumbnail((2048, 2048))`, PNG: the card's target longest dimension. `thumbnail` only downscales, so a
  smaller page is sent as it is (unlike LightOnOCR-2's forced 1540 px).
- Sampling from the card: temperature 0.2, top_p 0.9, max_tokens 4096; thinking off per request and
  server-side (`--default-chat-template-kwargs`).
- Serve flags: `--max-model-len 16384` (the board's; a 2048-px page is at most 4096 image tokens), one image
  and no video per prompt, no multimodal processor cache, no prefix caching; no `--trust-remote-code`.
- vLLM 0.30.0, not the board-wide 0.26.0: LightOn's repository says 0.27.1 makes these models loop. The HF
  Jobs image is therefore `vllm/vllm-openai:v0.30.0` (the recipe ran these on 0.26.0 before the presets).
- The completion is stored verbatim; `--gpu-memory-utilization` is the deployment's choice (board 0.8 on an
  A10G). Not yet run by linecaster: experimental.

| | |
|---|---|
| Step | page (reads pages) |
| Engine | `chat/1` |
| Model | [LightOnOCR-3-4B](https://huggingface.co/lightonai/LightOnOCR-3-4B/tree/b71010f095dc3735de7ee6b9969bff8f8f50b39a) |
| Revision | `b71010f095dc3735de7ee6b9969bff8f8f50b39a` |
| Upstream card | [upstream/b71010f095dc3735de7ee6b9969bff8f8f50b39a/README.md](../../src/linecaster/catalog/data/models/lightonocr-3-4b/upstream/b71010f095dc3735de7ee6b9969bff8f8f50b39a/README.md) (verbatim, at that revision) |
| Licence | Apache-2.0 |
| Server | vllm 0.30.0 |
| Image | `vllm/vllm-openai:v0.30.0` |
| Produces | markdown |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/lighton-ocr3-port.py
- lightonai/LightOnOCR-3-4B@b71010f095dc3735de7ee6b9969bff8f8f50b39a:README.md
