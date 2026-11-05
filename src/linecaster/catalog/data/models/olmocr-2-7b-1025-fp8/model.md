olmOCR-2-7B-1025-FP8 is Ai2's FP8 quantisation (made with llmcompressor) of olmOCR-2-7B-1025, which is
fine-tuned from Qwen2.5-VL-7B-Instruct on olmOCR-mix-1025 and further trained with GRPO RL. It reads a
rendered page and returns natural text as Markdown, preceded by a YAML front matter block (primary language,
rotation, table and diagram flags). Upstream recommends the olmOCR toolkit on vLLM, which renders, rotates and
retries pages. Licence: Apache-2.0, intended for research and educational use under Ai2's Responsible Use
Guidelines.
The upstream card is in `upstream/40bd7202494b8264ee17ada08b401b5aab7a9ce1/README.md`.
