"""MiniCPM-OCR 1.0 spec: per-label request, region selection, crop rule, SDK assembly."""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linecaster.adapters import chat_model
from linecaster.adapters.minicpm_ocr import region_blocks, sdk_label
from linecaster.data.transcription import Annotator, Transcription


def add(t, rid, label, raw, poly=None):
    """Adds a region to ``t``: its own label ``raw``, its content role from the Docling label ``label``."""
    poly = poly or [[10, 10], [110, 10], [110, 60], [10, 60]]
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return t.add_region(0, rid, [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)], poly, label=raw, role=label)


def reg(rid, label, raw, poly=None):
    """A region of a transcription of its own, and that transcription."""
    t = Transcription(annotators=[Annotator(step="layout", name="test")])
    return add(t, rid, label, raw, poly), t


def png(w=50, h=20):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("label, raw, prompt, cap", [
    ("text", "text", "Text Recognition:", 4096),
    ("table", "table", "Table Recognition:", 8192),
    ("formula", "display_formula", "Formula Recognition:", 2048),
    ("text", "inline_formula", "Text Recognition:", 1024),
    ("title", "doc_title", "Text Recognition:", 512),
    ("page_footer", "number", "Text Recognition:", 256),
    ("picture", "chart", "Chart to Table:", 4096),
    ("seal", "seal", "Seal Recognition:", 256),
    ("section_header", "", "Text Recognition:", 512),      # no raw label: mapped from Docling's (paragraph_title)
    ("text", "something_new", "Text Recognition:", 4096),   # unknown raw label (another layout model): by the Docling label
    ("reference", "something_new", "Text Recognition:", 2048),
    ("weird", "", "Text Recognition:", 8192),             # unknown altogether: the SDK default
])
def test_request_per_region_type(label, raw, prompt, cap):
    body = chat_model("minicpm-ocr-1.0").request_region(png(), *reg("r", label, raw))
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "image_url" and content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1] == {"type": "text", "text": prompt}          # image first, then the prompt
    assert body["max_tokens"] == cap and body["model"] == "minicpm-ocr"
    assert body["mm_processor_kwargs"] == {"downsample_mode": "4x", "max_slice_nums": 9}
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert (body["temperature"], body["top_p"], body["top_k"], body["repetition_penalty"], body["no_repeat_ngram_size"]) \
        == (0.01, 0.001, 1, 1.0, 100)


def test_regions_read_and_skipped():
    spec = chat_model("openbmb/MiniCPM-OCR-1.0")
    def reads(adapter, rid, label, raw, labels):
        r, t = reg(rid, label, raw)
        return adapter.reads_region(r, labels, t)

    assert reads(spec, "a", "page_footer", "number", frozenset())
    assert reads(spec, "b", "formula", "display_formula", frozenset())
    assert reads(spec, "c", "picture", "chart", frozenset())
    for raw in ("image", "header_image", "footer_image"):
        assert not reads(spec, "d", "picture", raw, frozenset())
    # LightOn keeps the label rule: the region's Docling label
    assert reads(chat_model("lightonocr-2-1b"), "e", "text", "text", frozenset({"text"}))
    assert not reads(chat_model("lightonocr-2-1b"), "f", "picture", "image", frozenset({"text"}))


def test_crop_is_full_resolution_int_box_with_polygon_mask():
    img = Image.new("RGB", (200, 100), (0, 0, 0))
    tri = [[10.7, 10.2], [110.9, 10.2], [10.7, 60.8]]           # a triangle: the corner opposite is masked white
    crop = chat_model("minicpm-ocr-1.0").crop_region(img, reg("r", "text", "text", tri)[0])
    assert crop.size == (100, 50)                                # int() truncation of 10.7..110.9 x 10.2..60.8
    assert crop.getpixel((1, 1)) == (0, 0, 0) and crop.getpixel((98, 48)) == (255, 255, 255)
    assert chat_model("minicpm-ocr-1.0").page_longest is None and chat_model("minicpm-ocr-1.0").region_pad == 0


def test_serve_args_follow_the_sdk_tutorial():
    args = chat_model("minicpm-ocr-1.0").vllm_args(0.85)
    for flag, value in (("--max-model-len", "40960"), ("--max-num-seqs", "32"),
                        ("--mm-processor-kwargs", '{"downsample_mode":"4x"}'),
                        ("--default-chat-template-kwargs", '{"enable_thinking":false}')):
        assert args[args.index(flag) + 1] == value
    assert "--trust-request-mm-kwargs" in args and "--served-model-name" in args
    spec = chat_model("minicpm-ocr-1.0").speculative_args("/draft")
    assert spec[0] == "--speculative-config" and '"method": "dspark"' in spec[1]


def page(texts: dict[str, str]):
    t = Transcription(annotators=[Annotator(step="layout", name="test"),
                                  Annotator(step="recognition", name="minicpm")])
    for rid, label, raw in [("doc_title_0", "title", "doc_title"), ("text_1", "text", "text"),
                            ("number_2", "page_footer", "number"), ("image_3", "picture", "image"),
                            ("footnote_4", "footnote", "footnote"), ("text_5", "text", "text")]:
        add(t, rid, label, raw)
    t.add_order(0, [r.id for r in t.regions])
    for rid, text in texts.items():
        t.add_line(1, f"{rid}_l0", region=rid, text=text)
    return t


def test_region_blocks_keep_order_images_and_skip_unread():
    t = page({"doc_title_0": "THE BIRDS", "text_1": "Body.", "number_2": "12", "footnote_4": "* note"})
    blocks = region_blocks(t)
    assert [(b["label"], b["order"]) for b in blocks] == [("doc_title", 0), ("text", 1), ("number", 2), ("image", 3),
                                                           ("footnote", 4)]   # text_5 was not read: left out


def test_assemble_markdown_with_the_sdk():
    pytest.importorskip("minicpmvocr")
    from linecaster.adapters.minicpm_ocr import assemble_markdown

    t = page({"doc_title_0": "THE BIRDS", "text_1": "First line\nsecond line", "number_2": "12", "footnote_4": "* note",
              "text_5": "Last."})
    md = assemble_markdown(t)
    assert md == "# THE BIRDS\n\nFirst line\n\nsecond line\n\n![image]()\n\nLast."
    assert "* note" in assemble_markdown(t, keep_labels=("footnote", "aside_text"))
    assert "12" not in assemble_markdown(t, keep_labels=("footnote", "aside_text"))


def test_sdk_label_mapping():
    assert sdk_label(*reg("a", "page_header", "header")) == "header"
    assert sdk_label(*reg("b", "page_header", "")) == "header"
    assert sdk_label(*reg("c", "caption", "")) == "figure_title"
