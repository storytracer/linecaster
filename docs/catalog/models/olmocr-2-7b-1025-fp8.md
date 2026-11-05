# olmocr-2-7b-1025-fp8

*Model · olmOCR-2-7B-1025-FP8 · Apache-2.0*

olmOCR-2-7B-1025-FP8 is Ai2's FP8 quantization (made with llmcompressor) of olmOCR-2-7B-1025, which is
fine-tuned from Qwen2.5-VL-7B-Instruct on olmOCR-mix-1025 and further trained with GRPO RL. It reads a
rendered page and returns natural text as Markdown, preceded by a YAML front matter block (primary language,
rotation, table and diagram flags). Upstream recommends the olmOCR toolkit on vLLM, which renders, rotates and
retries pages. License: Apache-2.0, intended for research and educational use under Ai2's Responsible Use
Guidelines.
The upstream card is in `upstream/40bd7202494b8264ee17ada08b401b5aab7a9ce1/README.md`.

|  |  |
|---|---|
| Source | [allenai/olmOCR-2-7B-1025-FP8](https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8) |
| License | Apache-2.0 |
| Languages | eng |
| Scripts | Latn |
| Parameters | 7B (FP8) |
| Derived from | quantized of allenai/olmOCR-2-7B-1025; finetuned of Qwen/Qwen2.5-VL-7B-Instruct |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `40bd7202494b8264ee17ada08b401b5aab7a9ce1` | 2026-11-03 |  | 4 | [README.md](../../../src/linecaster/catalog/data/models/olmocr-2-7b-1025-fp8/upstream/40bd7202494b8264ee17ada08b401b5aab7a9ce1/README.md) |

## Presets

- [`olmocr-2-7b-1025-fp8`](../presets/recognition/olmocr-2-7b-1025-fp8.md)
