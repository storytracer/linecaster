"""baidu/Unlimited-OCR (vLLM) and baidu/Unlimited-OCR-2 (SGLang): request, parse and serve flags exactly
as the BHL OCR board ran them.

**Unlimited-OCR** (``UnlimitedOCR``). Source: the board's saturate driver ``unlimited-ocr-port.py`` (in the
board's evaluation harness):

* message = the page image, then the text part ``document parsing.`` (the card's ``<image>document
  parsing.`` minus the image token: over ``/chat/completions`` the image is its own content part);
* the image at full resolution, no resize (the gundam crop grid is chosen from the input pixels): RGB
  PNG/JPEG bytes as they are, anything else converted to RGB and sent as PNG (the driver's
  ``encode_image``, the same rule as dots.mocr's);
* temperature 0.0, max_tokens 8192, ``skip_special_tokens: false`` (the grounding tags must survive
  detokenisation), and the card's no-repeat n-gram guard per request: ``vllm_xargs``
  ``{"ngram_size": 35, "window_size": 128}`` (the single-image setting);
* serve flags: ``--max-model-len 32768 --trust-remote-code --no-enable-prefix-caching
  --mm-processor-cache-gb 0 --limit-mm-per-prompt '{"image": 1}'``, and last ``--logits_processors
  vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor`` (the driver keeps it last);
* model revision pinned to the board's checkpoint; vLLM 0.26.0 (``vllm/vllm-openai:v0.26.0``; the
  card's dedicated ``vllm/vllm-openai:unlimited-ocr`` image is obsolete, the architecture is registered).

The completion is the grounded output (``<|det|>type [bbox]<|/det|>`` headers, ``<|ref|>`` spans, the
tokenizer's sentence specials on the edges), stored verbatim: the driver stores it as it comes. The
board scores it after its harness's rule for this model (``normalize_outputs``: strip, edge specials
off, the card's ``remove_det`` and a sweep for the shapes it misses), which stays in the harness.

**Unlimited-OCR-2** (``UnlimitedOCR2``). Source: the board's driver ``unlimited-ocr2-port.py``. No vLLM
support exists for it; Baidu ships a patched SGLang wheel in the model repo, built against
``lmsysorg/sglang:v0.5.20-cu130``:

* server: SGLang (``server = "sglang"``) in the image's own Python, with Baidu's wheel
  (``sglang-0.5.20.dev10+g8d62f5fb9c``, read from the model repo at the pinned revision) installed
  ``--no-deps`` and ``fastokens==0.3.2`` (``server_packages``); served as ``Unlimited-OCR-2``; the
  card's launch environment and flags (``server_env``, ``serve_args``), plus ``--enable-metrics``;
* no ``--revision``: with it, Baidu's SGLang skips its tokenizer fix-up and fastokens refuses the
  tokenizer at boot. The server loads the default branch. The board refused to start unless the
  default branch WAS the pinned commit; it has since moved on (README and a newer wheel only), so the
  serve block checks instead that every file at the default branch other than ``pin_ignore``
  (README, ``.gitattributes``, ``wheel/``, the paper PDF) equals the pinned revision's (git blob ids),
  i.e. the weights, config and tokenizer the server loads are the pinned ones;
* message = the page image, then ``<PAGE><image>Multi page parsing.`` (card-verbatim, the same prompt
  for one page as for many); full resolution, the same passthrough rule as v1;
* max_tokens 8000, temperature 0.0, ``skip_special_tokens: false``, ``images_config {"crop_mode":
  true}`` (gundam, the card's single-page default), and the card's no-repeat n-gram guard as an SGLang
  custom logit processor (``DeepseekOCRNoRepeatNGramLogitProcessor``, referenced by its dill pickle,
  so no SGLang import here) with ``ngram_size 35, window_size 128, page_token_id 128827,
  eos_token_id 1, max_page_tokens 20000``.

The completion (``<BLOCK>type[x1, y1, x2, y2]<FORK>text`` blocks, 0-1000 boxes, ``<LEVELn>``,
``<MERGE>``) is stored verbatim; the board scores it after Baidu's own Markdown converter
(``utils/process_unlimitedOCR2.py``, vendored in the harness) with figure placeholders dropped, which
stays in the harness. The board ran it on an RTX PRO 6000 (96 GB); the card's flags are Baidu's for an
80 GB A800.

Both drivers treat a response without content as an error row, not an empty page: ``content`` raises.
"""
from __future__ import annotations

import json
from typing import Any, ClassVar

from . import ChatModel
from .dots_mocr import encode_image


class UnlimitedOCR(ChatModel):
    model: ClassVar[str] = "baidu/Unlimited-OCR"
    revision: ClassVar[str | None] = "07dea832e22aefee32ad281d4b80551282e1c168"
    prompt: ClassVar[str] = "document parsing."
    page_longest: ClassVar[int | None] = None       # full resolution
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.0, "max_tokens": 8192, "skip_special_tokens": False}
    vllm_xargs: ClassVar[dict[str, int]] = {"ngram_size": 35, "window_size": 128}
    logits_processor: ClassVar[str] = "vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor"
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", "32768",
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
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
            "vllm_xargs": dict(self.vllm_xargs),
        }

    def vllm_args(self, gpu_memory_utilization: float | None = None, extra: list[str] | None = None) -> list[str]:
        """The base arguments, then ``--logits_processors`` last (as the driver orders them)."""
        return [*super().vllm_args(gpu_memory_utilization, extra), "--logits_processors", self.logits_processor]

    def content(self, body: dict) -> tuple[str, str | None]:
        choice = (body.get("choices") or [None])[0]
        if not choice or choice.get("message", {}).get("content") is None:
            raise ValueError(f"no content in response: {str(body)[:200]}")
        return choice["message"]["content"], choice.get("finish_reason")

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt, "vllm_xargs": dict(self.vllm_xargs),
                "logits_processor": self.logits_processor,
                "image": {"resize": None, "passthrough": "RGB PNG/JPEG", "else": "RGB PNG"}}


#: the card's no-repeat n-gram guard, ``DeepseekOCRNoRepeatNGramLogitProcessor.to_str()``: json of the
#: class's dill pickle, which is by reference (module + name), so a fixed string (copied from the driver)
NGRAM_PROCESSOR = json.dumps({"callable": (
    "80059559000000000000008c2a73676c616e672e7372742e73616d706c696e672e637573746f6d5f6c6f6769"
    "745f70726f636573736f72948c26446565707365656b4f43524e6f5265706561744e4772616d4c6f67697450"
    "726f636573736f729493942e")})
WHEEL = "sglang-0.5.20.dev10%2Bg8d62f5fb9c-py3-none-any.whl"


class UnlimitedOCR2(UnlimitedOCR):
    model: ClassVar[str] = "baidu/Unlimited-OCR-2"
    revision: ClassVar[str | None] = "9cf077c4b206e0e2a31879df937b0b0bcba3661c"
    prompt: ClassVar[str] = "<PAGE><image>Multi page parsing."
    server: ClassVar[str] = "sglang"
    sglang_version: ClassVar[str] = "0.5.20 (lmsysorg/sglang:v0.5.20-cu130) + Baidu's wheel 0.5.20.dev10+g8d62f5fb9c"
    vllm_version: ClassVar[str | None] = None
    revision_flag: ClassVar[bool] = False
    pin_ignore: ClassVar[tuple[str, ...]] = ("README.md", ".gitattributes", "wheel/*", "*.pdf")
    sampling: ClassVar[dict[str, Any]] = {"max_tokens": 8000, "temperature": 0.0, "skip_special_tokens": False}
    images_config: ClassVar[dict[str, Any]] = {"crop_mode": True}
    custom_params: ClassVar[dict[str, int]] = {"ngram_size": 35, "window_size": 128, "page_token_id": 128827,
                                               "eos_token_id": 1, "max_page_tokens": 20000}
    server_env: ClassVar[dict[str, str]] = {
        "SGLANG_UOCR_EANABLE_DOC_LIMIT": "1",  # (sic) upstream spelling
        "SGLANG_UOCR_DOC_GUNDAM_PAGE_WINDOW": "10",
        "SGLANG_UOCR_DOC_BASE_PAGE_WINDOW": "10",
        "SGLANG_UOCR_MAX_PAGE_TOKENS": "20000",
        "SGLANG_OPT_UOCR_SAM_REL_POS_BIAS_MB": "64",
        "SGLANG_UOCR_SHM_WRAP_MODEL_DATA": "1",
        "SGLANG_UOCR_SHM_WRAP_MIN_MB": "1",
        "SGLANG_VLM_CACHE_SIZE_MB": "0",
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
    }
    serve_args: ClassVar[list[str]] = [
        "--chat-template", "unlimited-ocr",
        "--tokenizer-backend", "fastokens", "--tokenizer-worker-num", "8",
        "--mem-fraction-static", "0.7",
        "--max-running-requests", "64",
        "--max-prefill-tokens", "2048",
        "--enable-custom-logit-processor", "--enable-streaming-session",
        "--allow-auto-truncate", "--disable-radix-cache",
        "--mm-preprocess-cache-size-mb", "0",
        "--cuda-graph-backend-decode", "full", "--cuda-graph-max-bs-decode", "64",
        "--cuda-graph-backend-prefill", "full",
        "--cuda-graph-max-bs-prefill", "16384",
        "--cuda-graph-bs-prefill", "1024", "2048",
        "--cuda-graph-config", '{"prefill": {"backend": "full", "full_prefill_max_req": 64}}',
    ]

    def __init__(self, served_name: str | None = None):
        super().__init__(served_name or "Unlimited-OCR-2")

    def server_packages(self) -> list[list[str]]:
        wheel = f"https://huggingface.co/{self.model}/resolve/{self.revision}/wheel/{WHEEL}"
        return [["--no-deps", wheel], ["fastokens==0.3.2"]]

    def request(self, image: bytes) -> dict:
        mime, b64 = encode_image(image)
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": self.prompt},
            ]}],
            **self.sampling,
            "images_config": dict(self.images_config),
            "custom_logit_processor": NGRAM_PROCESSOR,
            "custom_params": dict(self.custom_params),
        }

    def vllm_args(self, gpu_memory_utilization: float | None = None, extra: list[str] | None = None) -> list[str]:
        raise TypeError(f"{self.model} has no vLLM support; it runs on SGLang (sglang_args)")

    def settings(self) -> dict[str, Any]:
        return {"sampling": dict(self.sampling), "serve_args": list(self.serve_args), "server": self.server,
                "server_env": dict(self.server_env), "server_packages": self.server_packages(),
                "sglang_version": self.sglang_version, "prompt": self.prompt,
                "images_config": dict(self.images_config), "custom_params": dict(self.custom_params),
                "custom_logit_processor": "DeepseekOCRNoRepeatNGramLogitProcessor",
                "image": {"resize": None, "passthrough": "RGB PNG/JPEG", "else": "RGB PNG"}}
