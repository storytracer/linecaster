"""Serializations of a ``Transcription``: ALTO, PAGE-XML and hOCR, out and in, and TEI in (lxml; a page's or an
item's document is ``linecaster.document``). Import-light: no datatrove, saturate or engines."""
from .alto import from_alto, to_alto
from .hocr import from_hocr, to_hocr
from .pagexml import from_page, to_page
from .tei import from_tei

__all__ = ["from_alto", "from_hocr", "from_page", "from_tei", "to_alto", "to_hocr", "to_page"]
