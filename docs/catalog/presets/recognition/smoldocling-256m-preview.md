# smoldocling-256m-preview

*Preset · edition 1 · recognition · core*

SmolDocling-256M-preview, as the BHL OCR board's driver ran it (a port of Daniel van Strien's
`smoldocling-ocr.py`; where the two differ, the driver wins). The repository is now
`docling-project/SmolDocling-256M-preview`; linecaster pins the id the board used.

- The page image FIRST, then `Convert this page to docling.` (the card's chat example). The order matters: the
  repo's chat template branches on `content[0]['type'] == 'image'`.
- RGB, downscaled (never upscaled) so its longest side is at most 2048 px (LANCZOS; the processor's own
  `size.longest_edge`, so only the payload shrinks), JPEG quality 95.
- Sampling: temperature 0.0, max_tokens 6144 (the driver's choice, not the card's 8192: the native context is
  8192 and an image takes up to about 1600 tokens), `skip_special_tokens` false (DocTags' `<doctag>` and
  `<loc_*>` are added special tokens; vLLM's default strips them).
- Serve flags: `--max-model-len 8192` (`max_position_embeddings`, not raisable), no prefix caching, no
  multimodal processor cache, one image per prompt; no `--trust-remote-code` (Idefics3 is registered in vLLM).
- The model answers in DocTags. The completion is stored verbatim; `parse` also converts it the board's way
  (docling-core, body + furniture, no image placeholder) into `extra["markdown"]`. The board converted with
  docling-core 2.89; linecaster's lock has a newer one.

Validated on the 60-page sample (NOTES.md, "Board models as chat specs"): CER reading 0.0643 for linecaster's run on an L4 against 0.0556 for the board's own outputs on the same pages. The largest gap of the table (3 against 5
truncated pages); the board copy compared against may not be the scored run. Worth a second look.

```bash
uv run launch.py smoldocling-256m-preview IMAGES OUT
```

|  |  |
|---|---|
| Step | recognition (reads pages) |
| Engine | [`chat.v1`](../../engines/chat.v1.md) |
| Model | [SmolDocling-256M-preview](../../models/smoldocling-256m-preview.md) |
| Revision | [`ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8`](https://huggingface.co/ds4sd/SmolDocling-256M-preview/tree/ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8) |
| License | CDLA-Permissive-2.0 |
| Server | vllm 0.26.0 |
| Image | `vllm/vllm-openai:v0.26.0` |
| Produces | doctags, markdown |

## Options

| Option | Value |
|---|---|
| adapter | `smoldocling` |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0643 |
| 2026-11-03 | BHL board | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | cer_reading 0.0556 |

## Provenance

- finebooks/bhl-ocr-eval@76bc19d40c8fcaed7e3d99dd50fdb93603dfac6c:drivers/smoldocling-port.py
- uv-scripts/ocr@4ae561fcfef053f60c310cd04f7a7fa0e2fadce2:smoldocling-ocr.py
- ds4sd/SmolDocling-256M-preview@ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8:README.md
