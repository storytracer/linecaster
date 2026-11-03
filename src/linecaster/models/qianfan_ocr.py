"""baidu/Qianfan-OCR: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the board's saturate driver ``qianfan-ocr-port.py`` (in the board's evaluation harness), built
from the card and the checkpoint's config rather than inherited from Daniel van Strien's
``uv-scripts/ocr/qianfan-ocr.py``; where the two differ, this follows the driver:

* message = the page image, then the card's prompt ``Parse this document to Markdown.`` (image before
  text, the card's order);
* the image bytes sent as they are, no resize and no conversion, with the media type sniffed from the
  magic bytes (JPEG, PNG, TIFF, WebP; anything else is an error, as in the driver): the card documents
  no pixel bounds and the processor tiles and RGB-converts itself (max 12 tiles + thumbnail of 448 px);
* Layout-as-Thought off: ``chat_template_kwargs`` ``{"enable_thinking": false}`` per request (the
  card: disable it for homogeneous pages such as book pages);
* sampling: temperature 0.0 (the card's ``do_sample=False``), top_p 1.0, max_tokens 8192;
* serve flags: ``--max-model-len 16384 --limit-mm-per-prompt '{"image": 1}' --mm-processor-cache-gb 0
  --no-enable-prefix-caching``. Not ``--trust-remote-code`` (the repo ships no code) and not the card's
  ``--hf-overrides '{"architectures": ["InternVLChatModel"]}'`` (vLLM registers the model natively; the
  override would run the InternVL code path);
* model revision pinned to the board's checkpoint.

The completion is stored verbatim; the board's post-processing (strip, the strict ``</think>`` strip that
raises on an unterminated block, the non-empty check, a no-op since postproc 2) stays in the harness
(``normalize_outputs``, keyed on the model id). The board's vLLM is 0.26.0 (``vllm/vllm-openai:v0.26.0``)
on an A10G; ``--gpu-memory-utilization`` is the deployment's choice (board 0.85) and not part of the spec.
"""
from __future__ import annotations

import base64
from typing import Any, ClassVar

from . import ChatModel

PROMPT = "Parse this document to Markdown."
#: the driver's ``MAGIC``: magic bytes -> media type (WebP checked separately)
MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


def sniff_mime(raw: bytes) -> str:
    """The driver's ``sniff_mime``: the media type of an encoded image from its magic bytes."""
    for prefix, mime in MAGIC:
        if raw.startswith(prefix):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError(f"unrecognised image magic bytes: {raw[:8]!r}")


class QianfanOCR(ChatModel):
    model: ClassVar[str] = "baidu/Qianfan-OCR"
    revision: ClassVar[str | None] = "623bf5d20d446abdb36606aa4547cd0c18886fe5"
    page_longest: ClassVar[int | None] = None       # full resolution
    prompt: ClassVar[str] = PROMPT
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.0, "top_p": 1.0, "max_tokens": 8192}
    chat_template_kwargs: ClassVar[dict[str, Any]] = {"enable_thinking": False}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", "16384",
        "--limit-mm-per-prompt", '{"image": 1}',
        "--mm-processor-cache-gb", "0",
        "--no-enable-prefix-caching",
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        url = f"data:{sniff_mime(image)};base64," + base64.b64encode(image).decode()
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": url}},
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
            "chat_template_kwargs": dict(self.chat_template_kwargs),
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt, "chat_template_kwargs": dict(self.chat_template_kwargs),
                "image": {"resize": None, "bytes": "as received, media type sniffed"}}
