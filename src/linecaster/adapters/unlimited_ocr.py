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

Unlimited-OCR-2 answers with layout blocks, ``<BLOCK>label[x1, y1, x2, y2]<FORK>content`` after a ``<PAGE>`` marker,
stored verbatim as the raw output and read into the transcription by linecaster's HTML importer (``read_blocks``):
each block as an HTML block of its label (``title`` a heading, ``sub_title`` a lower one, a ``table`` whose content is
HTML as written, anything else a paragraph with its lines), the running head and foot and footnotes by their labels
(``header``, ``footer``, ``footnote`` as DPUB-ARIA roles; ``page_number`` as the head or the foot by where its box
is), a block without text (an ``image``, a ``seal``) as nothing. The text is the model's, read literally; the boxes
(0 to 1000 on the page) are not placed.

A response without content is an error, not an empty page: ``content`` raises.
"""
from __future__ import annotations

import html
import re
from typing import Any, ClassVar

from ..data import Transcription
from ..errors import ServerError
from . import text_lines
from .dots import PASSTHROUGH, DotsAdapter

#: one layout block: its label, its box (0 to 1000), its content up to the next block or page marker
BLOCK = re.compile(r"<BLOCK>(\w+)\[([^\]]*)\]<FORK>(.*?)(?=<BLOCK>|</?PAGE>|\Z)", re.S)
#: labels whose role HTML cannot tell, as the DPUB-ARIA roles the HTML importer reads
ROLES = {"header": "doc-pageheader", "footer": "doc-pagefooter", "footnote": "doc-footnote"}
#: labels read as headings
HEADINGS = {"title": "h1", "sub_title": "h2"}


def block_html(label: str, box: str, content: str) -> str:
    """One layout block as an HTML block (empty for a block without text)."""
    text = content.strip("\n")
    if not text.strip():
        return ""
    role = ROLES.get(label)
    if label == "page_number":                   # the running head's or foot's, by where the model put it
        ys = [int(v) for v in re.findall(r"\d+", box)[1::2]]
        role = "doc-pagefooter" if ys and sum(ys) / len(ys) > 500 else "doc-pageheader"
    attrs = f' data-label="{html.escape(label)}"' + (f' role="{role}"' if role else "")
    if label == "table" and text.lstrip().startswith("<"):
        inner = text
    else:
        lines = "<br/>".join(html.escape(x) for x in text.split("\n"))
        tag = HEADINGS.get(label, "p")
        inner = f"<{tag}>{lines}</{tag}>"
    return f"<div{attrs}>{inner}</div>"


def read_blocks(raw: str, t: Transcription, annotator: int) -> bool:
    """``raw`` (Unlimited-OCR-2's layout blocks) read into ``t`` by ``annotator``: True, or False when it holds no
    layout block (``t`` untouched)."""
    blocks = [block_html(*m.groups()) for m in BLOCK.finditer(raw)]
    if not blocks:
        return False
    from lxml import html as H

    from ..formats.html import HtmlConverter

    root = H.fromstring(f"<html><body>{''.join(blocks)}</body></html>")
    HtmlConverter().read(root, t, annotator, annotator)
    return True


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

    def parse(self, body: dict, backend: str | None = None) -> Transcription:
        """The completion's layout blocks read by linecaster's HTML importer (``read_blocks``); a completion without
        any one line per text line, as the other adapters read theirs."""
        t = self.begin(body, backend)
        if not read_blocks(t.outputs[0].content, t, 0):
            text_lines(t, 0, 0)
        return t

    def settings(self) -> dict[str, Any]:
        return {"sampling": dict(self.sampling), "serve_args": list(self.serve_args), "server": self.server,
                "server_env": dict(self.server_env), "server_packages": self.server_packages(),
                "sglang_version": f"{self.server_version} ({self.job_image})", "prompt": self.prompt,
                "images_config": self.images_config, "custom_params": self.custom_params,
                "custom_logit_processor": "DeepseekOCRNoRepeatNGramLogitProcessor", "image": dict(PASSTHROUGH)}
