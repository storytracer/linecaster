"""Plain text in (``from_text``), and telling transcription files apart by their content (``sniff``)."""
from __future__ import annotations

import re

from linecaster.data.transcription import Annotator, Source, Transcription

_ROOT = re.compile(rb"<(?:[\w.-]+:)?(alto|pcgts)\b", re.IGNORECASE)
_HOCR = re.compile(rb"""class\s*=\s*["'][^"']*\bocr_page\b""", re.IGNORECASE)
# the first element's start tag (after the prolog), and TEI's root elements
_FIRST = re.compile(rb"<(?![?!])")
_TEI_ROOT = re.compile(rb"<(?:([\w.-]+):)?(?:TEI|teiCorpus)\b([^>]*)>")
_TEI_NS = b"http://www.tei-c.org/ns/1.0"
_ANNOTATION_PAGE = re.compile(rb'"type"\s*:\s*"AnnotationPage"')


def sniff(data: bytes) -> str:
    """The format of a transcription file from its content: ``alto``, ``page``, ``hocr``, ``tei`` (its root ``TEI``
    or ``teiCorpus`` in the TEI namespace), ``iiif`` (a JSON IIIF annotation page), else ``text``."""
    head = data[:65536]
    first = _FIRST.search(head)
    root = _TEI_ROOT.match(head, first.start()) if first else None
    if root is not None:
        xmlns = b"xmlns" + (b":" + root.group(1) if root.group(1) else b"")
        if re.search(rb"(?:^|\s)" + re.escape(xmlns) + rb"\s*=\s*[\"']" + re.escape(_TEI_NS) + rb"[\"']",
                     root.group(2)):
            return "tei"
    if head.lstrip()[:1] == b"{" and _ANNOTATION_PAGE.search(head):
        return "iiif"
    m = _ROOT.search(head)
    if m:
        return "alto" if m.group(1).lower() == b"alto" else "page"
    if _HOCR.search(data):
        return "hocr"
    return "text"


def from_text(data: bytes | str, uri: str | None = None, ground_truth: bool = False, line_image: bool = False,
              image_width: int | None = None, image_height: int | None = None) -> Transcription:
    """Plain text (UTF-8): one line per text line, no geometry, read by the file (one annotator, kind ``file``;
    ``ground_truth``: by people, kind ``human``, the source a ground truth), in the file's order.

    ``line_image``: the text of an image of one line (a line-level dataset's row): one line, its box the whole image
    where ``image_width`` and ``image_height`` give its size; a line break at its end is dropped, one inside it is a
    ``ValueError`` (no text of one line)."""
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    t = Transcription(source=Source(kind="ground_truth" if ground_truth else "converted", format="text", uri=uri,
                                    image_width=image_width if line_image else None,
                                    image_height=image_height if line_image else None))
    a = t.add_annotator(Annotator(kind="human" if ground_truth else "file", step="transcription", name="text"))
    if line_image:
        line = text.rstrip("\r\n")
        if "\n" in line or "\r" in line:
            raise ValueError("a line image's text has a line break inside it")
        box = [0.0, 0.0, float(image_width), float(image_height)] if image_width and image_height else None
        t.add_line(a, "l0", box, text=line)
    for i, line in enumerate(text.splitlines() if not line_image else ()):
        t.add_line(a, f"l{i}", text=line)
    t.add_order(a, lines=[ln.id for ln in t.lines])
    return t
