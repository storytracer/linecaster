"""rednote-hilab/dots.ocr: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the board's saturate driver ``dots-ocr-port.py`` (in the board's evaluation harness), a port of
Daniel van Strien's ``uv-scripts/ocr/dots-ocr.py``; where the two differ, this follows the driver:

* plain OCR mode (``--prompt-mode ocr``): prompt ``Extract the text content from this image.``; the
  output is plain text, not layout JSON, so there is nothing to convert;
* message = the image, then the prompt as a text part, with NO image placeholder in the text (unlike the
  board's dots.mocr row, ``linecaster.models.dots_mocr``) and no ``--chat-template-content-format``;
* the image at full resolution, no resize: RGB PNG/JPEG bytes as they are, anything else converted to
  RGB and sent as PNG (the driver's ``encode_image``, the same rule as dots.mocr's);
* sampling: temperature 0.0, max_tokens 8192 (no top_p);
* serve flags: ``--max-model-len 32768 --trust-remote-code --no-enable-prefix-caching
  --mm-processor-cache-gb 0 --limit-mm-per-prompt '{"image": 1}'``;
* model revision pinned to the board's checkpoint.

The completion is stored verbatim; the board's post-processing (a strip) stays in the harness
(``normalize_outputs``, keyed on the model id). The board's vLLM is 0.26.0 (``vllm/vllm-openai:v0.26.0``).
The deployment is not part of the spec: the scored row ran with ``--gpu-memory-utilization 0.6``, at most
4 pages in flight and ``PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`` on an A10G (0.8 and 12 in
flight ran out of memory in the vision encoder).
"""
from __future__ import annotations

from typing import Any, ClassVar

from . import ChatModel
from .dots_mocr import encode_image

PROMPT = "Extract the text content from this image."
MAX_MODEL_LEN, MAX_TOKENS = 32768, 8192


class DotsOCR(ChatModel):
    model: ClassVar[str] = "rednote-hilab/dots.ocr"
    revision: ClassVar[str | None] = "c0111ce6bc07803dbc267932ffef0ae3a51dc951"
    page_longest: ClassVar[int | None] = None       # full resolution
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.0, "max_tokens": MAX_TOKENS}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", str(MAX_MODEL_LEN),
        "--trust-remote-code",
        "--no-enable-prefix-caching",
        "--mm-processor-cache-gb", "0",
        "--limit-mm-per-prompt", '{"image": 1}',
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        mime, b64 = encode_image(image)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": PROMPT},
            ]}],
            **self.sampling,
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": PROMPT,
                "image": {"resize": None, "passthrough": "RGB PNG/JPEG", "else": "RGB PNG"}}
