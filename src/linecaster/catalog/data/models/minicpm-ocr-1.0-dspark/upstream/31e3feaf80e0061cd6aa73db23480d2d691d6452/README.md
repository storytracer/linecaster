---
license: apache-2.0
language:
  - en
  - zh
pipeline_tag: image-text-to-text
tags:
  - minicpm-ocr
  - dspark
  - speculative-decoding
  - draft-model
  - ocr
  - multimodal
base_model: openbmb/MiniCPM-OCR-1.0
base_model_relation: finetune
---

<div align="center">

[GitHub](https://github.com/OpenBMB/MiniCPM-OCR) · [API](https://github.com/OpenBMB/MiniCPM-OCR/blob/main/docs/minicpm_ocr_api_en.md) · [Demo](https://platform.modelbest.ai/console/playground/document-parse) · [DSpark](https://huggingface.co/openbmb/MiniCPM-OCR-1.0-DSpark)

</div>

# MiniCPM-OCR 1.0 DSpark

> **This repository hosts the DSpark draft (speculative decoding) head for
> [MiniCPM-OCR 1.0](https://huggingface.co/openbmb/MiniCPM-OCR-1.0).** It is a draft model, not a standalone OCR model —
> it must be paired with the matching main checkpoint.

**DSpark** speeds up decoding with a small draft model that proposes tokens the main model then
verifies in one pass. With this head, MiniCPM-OCR 1.0 improves **end-to-end processing efficiency
by 55%**; throughput reaches about **1.49×** PaddleOCR-VL-1.6 and **3.62×** MinerU2.5 Pro.

## Specification

| Property | Value |
| :--- | :--- |
| Target model | MiniCPM-OCR 1.0 (1.3B) |
| Draft parameters | 296,837,889 |
| Draft layers | 5 |
| Draft tokens per forward pass | 15 |
| Target hidden-state layers | `[3, 7, 11, 15, 19]` |
| Checkpoint precision | BF16 |
| Input vocabulary | 248,100 |
| Draft output vocabulary | 114,688 |

The output LM head and the Markov output rows are cropped to 114,688 tokens. The checkpoint keeps
its `d2t` offset mapping and the full input vocabulary; `local-to-target.json` holds the
corresponding absolute target token IDs.

> **Note on `d2t`**: in this checkpoint the tensor is *delta*-encoded
> (`target_id - draft_id`). It must be converted to absolute IDs (`d2t[i] + i`) before use — the
> GGUF build already does this, and `local-to-target.json` is the ground truth to verify against.

## Usage with vLLM

```bash
vllm serve openbmb/MiniCPM-OCR-1.0 \
  --served-model-name MiniCPM-OCR \
  --trust-remote-code \
  --max-model-len 40960 \
  --max-num-batched-tokens 40960 \
  --max-num-seqs 1 \
  --trust-request-mm-kwargs \
  --mm-processor-kwargs '{"downsample_mode":"4x","max_slice_nums":9}' \
  --speculative-config '{"method":"dspark",
                         "model":"openbmb/MiniCPM-OCR-1.0-DSpark",
                         "num_speculative_tokens":15,
                         "enable_adaptive_verification":false}' \
  --default-chat-template-kwargs '{"enable_thinking":false}'
```

Selection and tuning: [DSpark acceleration](https://github.com/OpenBMB/MiniCPM-OCR/blob/main/docs/minicpmvocr_tutorial_en.md#3-start-the-service).

## Files

| File | Notes |
| :--- | :--- |
| `model.safetensors` | 64 tensors — 5 draft layers, `fc` projector, `lm_head`, Markov heads, confidence head, `d2t` |
| `config.json` | `architectures: ["Qwen3DSparkModel"]`, `dflash_config` with target layer ids and Markov rank |
| `local-to-target.json` | 114,688 absolute target token IDs, the reference for `d2t` |
| `export-audit.json` | export-time audit: weight/mapping hashes and vocabulary coverage |

## Related checkpoints

| Format | Hugging Face | ModelScope |
| :--- | :--- | :--- |
| BF16 (original) | [🤗](https://huggingface.co/openbmb/MiniCPM-OCR-1.0) | [ModelScope](https://modelscope.cn/models/OpenBMB/MiniCPM-OCR-1.0) |
| GGUF (llama.cpp) | [🤗](https://huggingface.co/openbmb/MiniCPM-OCR-1.0-gguf) | [ModelScope](https://modelscope.cn/models/OpenBMB/MiniCPM-OCR-1.0-gguf) |
| AWQ W4A16 | [🤗](https://huggingface.co/openbmb/MiniCPM-OCR-1.0-AWQ) | [ModelScope](https://modelscope.cn/models/OpenBMB/MiniCPM-OCR-1.0-AWQ) |
| GPTQ W4A16 | [🤗](https://huggingface.co/openbmb/MiniCPM-OCR-1.0-GPTQ) | [ModelScope](https://modelscope.cn/models/OpenBMB/MiniCPM-OCR-1.0-GPTQ) |
| DSpark draft (BF16) **(this repo)** | [🤗](https://huggingface.co/openbmb/MiniCPM-OCR-1.0-DSpark) | [ModelScope](https://modelscope.cn/models/OpenBMB/MiniCPM-OCR-1.0-DSpark) |
| DSpark draft (GGUF) | [🤗](https://huggingface.co/openbmb/MiniCPM-OCR-1.0-DSpark-gguf) | [ModelScope](https://modelscope.cn/models/OpenBMB/MiniCPM-OCR-1.0-DSpark-gguf) |

DSpark requires a **matching main and draft model from the same release**; do not pair this draft
with a different main checkpoint.

## License

[Apache License 2.0](https://github.com/OpenBMB/MiniCPM-OCR/blob/main/LICENSE).
