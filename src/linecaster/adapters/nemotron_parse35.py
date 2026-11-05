"""Adapter ``nemotron-parse``: NVIDIA's Nemotron Parse generation contract (preset ``nemotron-3.5-parse``).

* message = ``settings.prompt`` (the control-token prompt) as a text part FIRST, then the page image (the
  vendor client's order);
* the image RGB-converted at its original size, PNG (the server-side processor fits it itself, so a
  client-side resize would resample twice);
* the architecture is not in vLLM's registry: NVIDIA serves it through a vLLM general plugin shipped in the
  model repo. ``serve_setup`` installs it into the vLLM image's own Python before ``vllm serve``, as the
  board's ``install-plugin.sh`` does: the files ``options.plugin_patterns`` from the model repo at the
  pinned revision, NVIDIA's inference constraints without their own ``nemotron-parse`` line, and a check
  that vLLM is still the preset's version.

The completion is stored verbatim: an interleaved block stream of coordinate tokens, ``<class_*>`` tokens and
Markdown text. ``to_markdown`` reproduces the board's rendering (the vendor's
``nemotron_parse.postprocessing.render_markdown`` from the model repo, then ``strip_underscore_emphasis``);
``parse`` does not call it, because it imports code from the model repo.
"""
from __future__ import annotations

import io
import re
from typing import Any, ClassVar

from . import ChatAdapter, data_url, png_bytes


def png_full(image: bytes) -> str:
    """RGB at the original size, base64 PNG (the driver's ``encode_png``)."""
    from PIL import Image

    with Image.open(io.BytesIO(image)) as im:
        img = im.convert("RGB")
    return png_bytes(img)


_UNDERSCORE_EMPHASIS = re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")


def strip_underscore_emphasis(text: str) -> str:
    """Unwrap Markdown ``_italic_`` spans, keeping the text (the harness's rule, verbatim): the board's
    scorer strips ``*`` emphasis but not ``_``, which this model uses for every italic species name."""
    return _UNDERSCORE_EMPHASIS.sub(r"\1", text)


_render = None


def to_markdown(raw: str, revision: str | None = None, preset: str = "nemotron-3.5-parse") -> str:
    """The board's scored text for a completion: stripped, rendered by the vendor's
    ``nemotron_parse.postprocessing.render_markdown`` (default options; downloaded from the model repo
    at ``revision``, default the preset's, and imported), stripped, ``_italic_`` delimiters unwrapped."""
    global _render
    if _render is None:
        import sys

        from huggingface_hub import snapshot_download

        from . import chat_model

        spec = chat_model(preset)
        root = snapshot_download(spec.model, revision=revision or spec.revision,
                                 allow_patterns=["nemotron_parse/*", "nemotron_parse/**"])
        sys.path.insert(0, root)
        from nemotron_parse.postprocessing import render_markdown

        _render = render_markdown
    return strip_underscore_emphasis(_render(raw.strip()).strip())


class NemotronParseAdapter(ChatAdapter):
    adapter: ClassVar[str] = "nemotron-parse"

    def request(self, image: bytes) -> dict:
        return {
            "model": self.served_name,
            "messages": [{"role": "user", "content": [{"type": "text", "text": self.prompt},
                                                      data_url("image/png", png_full(image))]}],
            **self.sampling,
        }

    def serve_setup(self) -> str:
        """The board's ``install-plugin.sh``, into the Python that runs ``$VLLM`` (read from its shebang)."""
        patterns = repr(list(self.options["plugin_patterns"]))
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
