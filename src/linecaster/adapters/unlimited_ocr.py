"""Adapters ``unlimited-ocr`` (baidu/Unlimited-OCR on vLLM) and ``unlimited-ocr-2`` (baidu/Unlimited-OCR-2 on
SGLang; presets ``unlimited-ocr``, ``unlimited-ocr-2``).

**Unlimited-OCR**: the ``dots`` request (image at full resolution, passthrough, then the prompt), the card's
no-repeat n-gram guard per request (``settings.vllm_xargs``) and its logits processor at boot, last on the
command line (``settings.logits_processor``).

**Unlimited-OCR-2**: no vLLM support; the preset's ``serve`` block starts Baidu's patched SGLang (its wheel
from the model repo at the pinned revision, installed first, ``server_packages``) without ``--revision``
(``revision_flag: false``; the serve block checks the default branch against the pin instead). Request: the
image (passthrough), then the prompt; ``**sampling``; ``images_config``; the card's n-gram guard as an SGLang
custom logit processor (``settings.custom_logit_processor``: ``DeepseekOCRNoRepeatNGramLogitProcessor.to_str()``,
JSON of the class's dill pickle by reference, so no SGLang import here) with ``settings.custom_params``.

A response without content is an error, not an empty page: ``content`` raises.
"""
from __future__ import annotations

from typing import Any, ClassVar

from ..errors import ServerError
from .dots import PASSTHROUGH, DotsAdapter


class UnlimitedOCRAdapter(DotsAdapter):
    adapter: ClassVar[str] = "unlimited-ocr"

    def content(self, body: dict) -> tuple[str, str | None]:
        choice = (body.get("choices") or [None])[0]
        if not choice or choice.get("message", {}).get("content") is None:
            raise ServerError(f"no content in response: {str(body)[:200]}")
        return choice["message"]["content"], choice.get("finish_reason")

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "vllm_xargs": dict(self.config["vllm_xargs"]),
                "logits_processor": self.logits_processor}


class UnlimitedOCR2Adapter(UnlimitedOCRAdapter):
    adapter: ClassVar[str] = "unlimited-ocr-2"

    @property
    def images_config(self) -> dict[str, Any]:
        return dict(self.config["images_config"])

    @property
    def custom_params(self) -> dict[str, Any]:
        return dict(self.config["custom_params"])

    @property
    def custom_logit_processor(self) -> str:
        return self.config["custom_logit_processor"]

    def request_extra(self) -> dict[str, Any]:
        return {"images_config": self.images_config, "custom_logit_processor": self.custom_logit_processor,
                "custom_params": self.custom_params}

    def settings(self) -> dict[str, Any]:
        return {"sampling": dict(self.sampling), "serve_args": list(self.serve_args), "server": self.server,
                "server_env": dict(self.server_env), "server_packages": self.server_packages(),
                "sglang_version": f"{self.server_version} ({self.job_image})", "prompt": self.prompt,
                "images_config": self.images_config, "custom_params": self.custom_params,
                "custom_logit_processor": "DeepseekOCRNoRepeatNGramLogitProcessor", "image": dict(PASSTHROUGH)}
