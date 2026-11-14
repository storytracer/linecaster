"""Plain text in (``from_text``), and telling transcription files apart by their content (``sniff``)."""
from __future__ import annotations

import re

from ..data.transcription import Annotator, Source, Transcription

_ROOT = re.compile(rb"<(?:[\w.-]+:)?(alto|pcgts)\b", re.IGNORECASE)
_HOCR = re.compile(rb"""class\s*=\s*["'][^"']*\bocr_page\b""", re.IGNORECASE)


def sniff(data: bytes) -> str:
    """The format of a transcription file from its content: ``alto``, ``page``, ``hocr``, else ``text``."""
    m = _ROOT.search(data[:65536])
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
