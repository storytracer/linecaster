"""Adapter ``dots``: dots.ocr and dots.mocr in plain OCR mode (presets ``dots-ocr``, ``dots-mocr``).

* message = the image, then a text part: ``settings.image_placeholder`` (dots.mocr: vLLM's dots
  placeholder ``<|img|><|imgpad|><|endofimg|>``, with ``--chat-template-content-format string`` so vLLM adds
  none of its own; dots.ocr: none) followed by ``settings.prompt``;
* the image at full resolution, no resize: RGB PNG/JPEG bytes as they are, anything else converted to RGB
  and sent as PNG (``encode_image``, the board drivers' rule, shared with DeepSeek-OCR and Unlimited-OCR);
* the output is plain text, not layout JSON (the layout modes are not used), so there is nothing to convert.
"""
from __future__ import annotations

import base64
import io
from typing import Any, ClassVar

from . import ChatModel, data_url

#: formats sent byte-for-byte when the image is already RGB (the drivers' ``PASSTHROUGH_FORMATS``)
PASSTHROUGH_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}
PASSTHROUGH = {"resize": None, "passthrough": "RGB PNG/JPEG", "else": "RGB PNG"}


def encode_image(data: bytes) -> tuple[str, str]:
    """``(mime, base64)`` of a page image at full resolution, as the board drivers' ``encode_image``."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        mime = PASSTHROUGH_FORMATS.get(img.format)
        if mime and img.mode == "RGB":
            return mime, base64.b64encode(data).decode()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
    return "image/png", base64.b64encode(buf.getvalue()).decode()


class Dots(ChatModel):
    """Image (full resolution, passthrough), then placeholder + prompt; ``**sampling``; then the fields of
    ``request_extra``. With ``settings.vllm_xargs`` (a per-request n-gram guard) those go with every request,
    and ``settings.logits_processor`` is registered at boot (``--logits_processors``, last on the command
    line: the flag takes a list, so nothing may follow it); DeepSeek-OCR and Unlimited-OCR build on this."""

    adapter: ClassVar[str] = "dots"

    def text(self) -> str:
        return f"{self.config.get('image_placeholder') or ''}{self.prompt}"

    @property
    def vllm_xargs(self) -> dict[str, Any] | None:
        x = self.config.get("vllm_xargs")
        return None if x is None else {k: (list(v) if isinstance(v, list) else v) for k, v in x.items()}

    @property
    def logits_processor(self) -> str | None:
        return self.config.get("logits_processor")

    def request_extra(self) -> dict[str, Any]:
        return {} if self.vllm_xargs is None else {"vllm_xargs": self.vllm_xargs}

    def vllm_args(self, gpu_memory_utilization: float | None = None, extra: list[str] | None = None) -> list[str]:
        """The preset's flags and overrides, then ``--logits_processors`` last when the preset has one."""
        args = super().vllm_args(gpu_memory_utilization, extra)
        return args + ["--logits_processors", self.logits_processor] if self.logits_processor else args

    def request(self, image: bytes) -> dict:
        mime, b64 = encode_image(image)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [data_url(mime, b64), {"type": "text", "text": self.text()}]}],
            **self.sampling,
            **self.request_extra(),
        }

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt, "image": dict(PASSTHROUGH)}
