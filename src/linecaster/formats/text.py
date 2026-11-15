"""Plain text in (``from_text``), and telling transcription files apart by their content (``sniff``)."""
from __future__ import annotations

import re

from ..data.transcription import Annotator, Source, Transcription

_ROOT = re.compile(rb"<(?:[\w.-]+:)?(alto|pcgts)\b", re.IGNORECASE)
_HOCR = re.compile(rb"""class\s*=\s*["'][^"']*\bocr_page\b""", re.IGNORECASE)
# the first element's start tag (after the prolog), and TEI's root elements
_FIRST = re.compile(rb"<(?![?!])")
_TEI_ROOT = re.compile(rb"<(?:([\w.-]+):)?(?:TEI|teiCorpus)\b([^>]*)>")
_TEI_NS = b"http://www.tei-c.org/ns/1.0"


def sniff(data: bytes) -> str:
    """The format of a transcription file from its content: ``alto``, ``page``, ``hocr``, ``tei`` (its root ``TEI``
    or ``teiCorpus`` in the TEI namespace), else ``text``."""
    head = data[:65536]
    first = _FIRST.search(head)
    root = _TEI_ROOT.match(head, first.start()) if first else None
    if root is not None:
        xmlns = b"xmlns" + (b":" + root.group(1) if root.group(1) else b"")
        if re.search(rb"(?:^|\s)" + re.escape(xmlns) + rb"\s*=\s*[\"']" + re.escape(_TEI_NS) + rb"[\"']",
                     root.group(2)):
            return "tei"
    m = _ROOT.search(head)
    if m:
        return "alto" if m.group(1).lower() == b"alto" else "page"
    if _HOCR.search(data):
        return "hocr"
    return "text"


def from_text(data: bytes | str, uri: str | None = None, ground_truth: bool = False) -> Transcription:
    """Plain text (UTF-8): one line per text line, no geometry, read by the file (one annotator, kind ``file``;
    ``ground_truth``: by people, kind ``human``, the source a ground truth), in the file's order."""
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    t = Transcription(source=Source(kind="ground_truth" if ground_truth else "converted", format="text", uri=uri))
    a = t.add_annotator(Annotator(kind="human" if ground_truth else "file", step="transcription", name="text"))
    for i, line in enumerate(text.splitlines()):
        t.add_line(a, f"l{i}", text=line)
    t.add_order(a, lines=[ln.id for ln in t.lines])
    return t
