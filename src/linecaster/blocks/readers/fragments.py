"""Page images addressed by a fragment: ``file.pdf#page=<n>`` (``PdfReader``: the n-th page, rendered) and
``file.parquet#<page_id>`` (``ImageParquetReader`` with embedded bytes: that row's image). ``read_image`` gives the
image a page record's ``image.uri`` names, never the whole file the fragment is part of: a fragment it cannot
resolve is a ``PageError``. Fragments of ``http(s)://`` URLs stay with the client (a server never sees them)."""
from __future__ import annotations

import io
import re
from collections.abc import Callable, Mapping

from ...errors import PageError

#: ``#page=<n>`` of a PDF page (``PdfReader``), 1-based
PDF_PAGE = re.compile(r"page=(\d+)")
#: the resolution ``PdfReader`` renders at when a page record does not say (``metadata["pdf"]["dpi"]``)
PDF_DPI = 300
#: the columns ``ImageParquetReader`` reads by default: the page id and the image
PARQUET_ID, PARQUET_IMAGE = "id", "image"


def split_fragment(uri: str) -> tuple[str, str]:
    """``uri`` without its fragment, and the fragment (``""``: none)."""
    base, _, fragment = uri.partition("#")
    return base, fragment


def read_image(uri: str, read: Callable[[str], bytes], page_id: str = "", metadata: Mapping | None = None) -> bytes:
    """Returns the image bytes ``uri`` names, reading files with ``read`` (a path or URL without fragment -> its
    bytes).

    Without a fragment, or for an ``http(s)://`` URL, the bytes at the address. ``<file>.pdf#page=<n>``: page ``n``
    of the PDF rendered as ``PdfReader`` renders it (lossless WebP, at the page record's ``metadata["pdf"]["dpi"]``,
    else 300; needs ``linecaster[pypdfium2]``). ``<file>.parquet#<page_id>``: the image of the row whose ``id`` is
    the page id (``ImageParquetReader``'s default columns ``id`` and ``image``). Any other fragment, or one that
    names nothing in its file, is a ``PageError`` for ``page_id``.

    Args:
        uri: the page image's address (``page.image.uri``).
        read: reads the bytes of an address without fragment.
        page_id: the page, for the error.
        metadata: the page record's ``metadata`` (a PDF page's resolution).
    """
    base, fragment = split_fragment(uri)
    if not fragment or base.startswith(("http://", "https://")):
        return read(base)
    lower = base.lower()
    if lower.endswith(".pdf") and (m := PDF_PAGE.fullmatch(fragment)):
        dpi = ((metadata or {}).get("pdf") or {}).get("dpi") or PDF_DPI
        return pdf_page(read(base), int(m.group(1)), dpi, uri, page_id)
    if lower.endswith(".parquet"):
        return parquet_row(read(base), fragment, uri, page_id)
    raise PageError(page_id, message=f"cannot fetch {uri}: the fragment #{fragment} names no PDF page "
                                     "(file.pdf#page=<n>) or Parquet row (file.parquet#<page_id>)")


def pdf_page(data: bytes, number: int, dpi: float, uri: str = "", page_id: str = "") -> bytes:
    """Page ``number`` (1-based) of the PDF ``data``, rendered at ``dpi`` as lossless WebP (``PdfReader.render``)."""
    from .pdf import pdfium, render

    pdf = pdfium().PdfDocument(data)
    try:
        if not 1 <= number <= len(pdf):
            raise PageError(page_id, message=f"cannot fetch {uri}: the PDF has {len(pdf)} pages")
        page = pdf[number - 1]
        try:
            return render(page, dpi)
        finally:
            page.close()
    finally:
        pdf.close()


def parquet_row(data: bytes, page_id_value: str, uri: str = "", page_id: str = "") -> bytes:
    """The image bytes of the row of the Parquet file ``data`` whose ``id`` is ``page_id_value``."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    f = pq.ParquetFile(io.BytesIO(data))
    names = f.schema_arrow.names
    if PARQUET_ID not in names or PARQUET_IMAGE not in names:
        raise PageError(page_id, message=f"cannot fetch {uri}: the Parquet file has no {PARQUET_ID!r} and "
                                         f"{PARQUET_IMAGE!r} columns to find the row by (columns: {names})")
    for batch in f.iter_batches(columns=[PARQUET_ID, PARQUET_IMAGE]):
        hits = pc.equal(pc.cast(batch.column(PARQUET_ID), "string"), page_id_value)
        rows = batch.filter(hits).column(PARQUET_IMAGE).to_pylist()
        if rows:
            value = rows[0]
            raw = value.get("bytes") if isinstance(value, dict) else value
            if not isinstance(raw, (bytes, bytearray)):
                raise PageError(page_id, message=f"cannot fetch {uri}: the row holds no image bytes")
            return bytes(raw)
    raise PageError(page_id, message=f"cannot fetch {uri}: no row with {PARQUET_ID} {page_id_value!r}")
