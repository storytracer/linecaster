"""nvidia/Nemotron-3.5-Parse: request, parse and serve flags exactly as the BHL OCR board ran it.

Source: the board's saturate driver ``nemotron-parse-35-port.py`` and its plugin install script
``docker/nemotron-parse-35/install-plugin.sh`` (in the board's evaluation harness), both following the
model card (``docs/serving.md``, "Generation contract" and the H100 ``vllm serve`` block):

* message = the control-token prompt as a text part FIRST, then the page image (the vendor client);
  prompt ``</s><s><predict_bbox><predict_classes><output_markdown><predict_text_in_pic>``;
* the image RGB-converted at its original size, PNG (the vendor client sends the file as it is; the
  server-side processor fits it to 2048 x 1664, so a client-side resize would resample twice);
* sampling: temperature 0.0, top_k 1, repetition_penalty 1.1, max_tokens 8744,
  ``skip_special_tokens: false`` (the reply's coordinate and class tokens are kept);
* serve flags, the card's H100 block: ``--max-model-len 16384 --trust-remote-code --dtype bfloat16
  --distributed-executor-backend uni --max-num-seqs 192 --max-num-batched-tokens 16384
  --no-enable-prefix-caching --limit-mm-per-prompt '{"image": 1}' --attention-config
  '{"flash_attn_version": 3}'``. FlashAttention 3 is a Hopper kernel: the board ran on an H200, and an
  Ada/Ampere GPU (L4, A10G) cannot run these flags as they are;
* the architecture (RadioMBartPrefixForCausalLM) is not in vLLM 0.26.0's registry. NVIDIA serves it
  through a vLLM general plugin (``nemotron-parse`` 3.5.0.post7) shipped in the model repo; ``serve_setup``
  installs it into the vLLM image's own Python before ``vllm serve``, exactly as the board's install
  script does (the package source and NVIDIA's ``reference/parse_3_5/inference.constraints.txt`` from the
  model repo at the pinned revision, the lock's own ``nemotron-parse`` line dropped; the install fails if
  vLLM moved off 0.26.0). The plugin's one-token MTP speculative decoding stays on, as on the board;
* model revision pinned to the board's checkpoint (weights and plugin from the same revision).

The completion is stored verbatim (``extra["raw"]``, the lines): an interleaved block stream of
coordinate tokens, ``<class_*>`` tokens and Markdown text. The board's post-processing stays in the
harness (``runners/normalize_outputs.py``: strip, the vendor's ``nemotron_parse.postprocessing.render_markdown``
loaded from the model repo at the served revision, then ``strip_underscore_emphasis``); ``to_markdown``
reproduces it for other consumers but is not called by ``parse``, because it imports code from the
model repo. The board's vLLM is ``vllm/vllm-openai:v0.26.0`` (by its amd64 digest);
``--gpu-memory-utilization`` is the deployment's choice (board 0.8) and not part of the spec.
"""
from __future__ import annotations

import base64
import io
import re
from typing import Any, ClassVar

from . import ChatModel

PROMPT = "</s><s><predict_bbox><predict_classes><output_markdown><predict_text_in_pic>"
MAX_MODEL_LEN, MAX_TOKENS = 16384, 8744
#: the board's image: vllm/vllm-openai:v0.26.0 by its amd64 digest (the plugin is installed at boot)
IMAGE = "vllm/vllm-openai:v0.26.0@sha256:770fe65b2c73ee74a5c42165cf3433de4048cc2cd9c57a937ca4e35aba5aa87b"
#: what the board's install script downloads from the model repo
PLUGIN_PATTERNS = ["pyproject.toml", "LICENSE", "THIRD_PARTY_NOTICES.md", "TOKENIZER_ATTRIBUTION.md",
                   "postprocessing.py", "latex2html.py", "nemotron_parse/*", "nemotron_parse/**",
                   "vllm_tied_patch/*", "reference/parse_3_5/inference.constraints.txt"]


def png_full(image: bytes) -> str:
    """RGB at the original size, base64 PNG (the driver's ``encode_png``)."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


_UNDERSCORE_EMPHASIS = re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")


def strip_underscore_emphasis(text: str) -> str:
    """Unwrap Markdown ``_italic_`` spans, keeping the text (the harness's rule, verbatim): the board's
    scorer strips ``*`` emphasis but not ``_``, which this model uses for every italic species name."""
    return _UNDERSCORE_EMPHASIS.sub(r"\1", text)


_render = None


def to_markdown(raw: str, revision: str | None = None) -> str:
    """The board's scored text for a completion: stripped, rendered by the vendor's
    ``nemotron_parse.postprocessing.render_markdown`` (default options; downloaded from the model repo
    at ``revision``, default the spec's, and imported), stripped, ``_italic_`` delimiters unwrapped."""
    global _render
    if _render is None:
        import sys

        from huggingface_hub import snapshot_download

        root = snapshot_download(NemotronParse35.model, revision=revision or NemotronParse35.revision,
                                 allow_patterns=["nemotron_parse/*", "nemotron_parse/**"])
        sys.path.insert(0, root)
        from nemotron_parse.postprocessing import render_markdown

        _render = render_markdown
    return strip_underscore_emphasis(_render(raw.strip()).strip())


class NemotronParse35(ChatModel):
    model: ClassVar[str] = "nvidia/Nemotron-3.5-Parse"
    revision: ClassVar[str | None] = "62cb1e4ba153d113ff64aaf2be6e068c377cf53c"
    prompt: ClassVar[str] = PROMPT
    sampling: ClassVar[dict[str, Any]] = {"temperature": 0.0, "max_tokens": MAX_TOKENS, "top_k": 1,
                                          "repetition_penalty": 1.1, "skip_special_tokens": False}
    serve_args: ClassVar[list[str]] = [
        "--max-model-len", str(MAX_MODEL_LEN),
        "--trust-remote-code",
        "--dtype", "bfloat16",
        "--distributed-executor-backend", "uni",
        "--max-num-seqs", "192",
        "--max-num-batched-tokens", "16384",
        "--no-enable-prefix-caching",
        "--limit-mm-per-prompt", '{"image": 1}',
        "--attention-config", '{"flash_attn_version": 3}',
    ]
    vllm_version: ClassVar[str | None] = "0.26.0"

    def request(self, image: bytes) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": self.prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_full(image)}"}},
            ]}],
            **self.sampling,
        }

    def serve_setup(self) -> str:
        """The board's ``install-plugin.sh``, into the Python that runs ``$VLLM`` (read from its shebang)."""
        patterns = repr(PLUGIN_PATTERNS)
        return "\n".join([
            'PY=$(head -n1 "$(command -v "$VLLM")" | sed "s/^#! *//")',
            'case "$PY" in *" "*) PY=$(command -v "${PY##* }");; esac',
            f'"$PY" -c "from huggingface_hub import snapshot_download; snapshot_download('
            f"'{self.model}', revision='{self.revision}', local_dir='/tmp/np', allow_patterns={patterns})\"",
            "grep -v '^nemotron-parse==' /tmp/np/reference/parse_3_5/inference.constraints.txt > /tmp/np-constraints.txt",
            'uv pip install --system --python "$PY" --constraint /tmp/np-constraints.txt /tmp/np',
            f'"$PY" -c "import vllm; assert vllm.__version__ == \'{self.vllm_version}\', vllm.__version__"',
        ])

    def settings(self) -> dict[str, Any]:
        return {**super().settings(), "prompt": self.prompt, "order": "text, then image",
                "image": {"format": "png", "resize": None},
                "plugin": f"nemotron-parse from {self.model}@{self.revision}, NVIDIA's inference constraints"}
