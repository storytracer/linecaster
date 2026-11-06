"""``PdfReader``: PDF files as items, one page per PDF page rendered to an image (``linecaster[pypdfium2]``).

A skeleton: the pages are rendered with pypdfium2 (PDFium) at ``dpi`` and stored as lossless WebP (the working
format: 8-bit RGB, method 0, exact); the PDF's own text layer (as the transcription ``ocr_original``) is not read
yet.
"""
from __future__ import annotations

import io
import posixpath

from datatrove.io import DataFileLike, DataFolderLike
from datatrove.pipeline.readers.base import BaseDiskReader
from loguru import logger

from ...errors import PipelineConfigError
from ..base.contract import Contracted
from ..base.page import new_page_document
from .manifests import safe_id

#: points per inch: a PDF page's size is given in points
POINTS = 72


def pdfium():
    try:
        import pypdfium2
    except ImportError:
        raise PipelineConfigError("PdfReader renders pages with pypdfium2: install linecaster[pypdfium2]") from None
    return pypdfium2


def render(page, dpi: float) -> bytes:
    """A PDF page (pypdfium2's ``PdfPage``) at ``dpi``, as lossless WebP."""
    image = page.render(scale=dpi / POINTS).to_pil().convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="WEBP", lossless=True, method=0, exact=True, quality=80)
    return buf.getvalue()


class PdfReader(Contracted, BaseDiskReader):
    """Reads one item per PDF file, one page per PDF page in order, each rendered to a lossless WebP image.

    ``item_id`` is the file name without ``.pdf``; ``sequence`` counts from 1, ``page_id`` is
    ``<item_id>_<sequence:04d>``. Each page adds ``image`` (rendered at ``dpi``) and ``metadata``: ``image.uri`` is
    the PDF's path with ``#page=<n>``, ``metadata["pdf"]`` the page's number, its size in points and the resolution.
    Files as datatrove reads them: under ``data_folder`` matching ``glob_pattern``, or listed in ``paths_file``,
    distributed over tasks in turn, so an item stays in one task (``whole_items``); ``limit`` and ``skip`` count
    pages. A page too large to render (over WebP's or Pillow's size limit at ``dpi``) is logged and counted
    (``pages_too_large``), and the item goes on. Needs the extra ``[pypdfium2]``.

    Args:
        data_folder: the folder (local path, fsspec URI or ``DataFolder``) of the PDF files.
        glob_pattern: the files to read; default every ``.pdf`` at any depth.
        dpi: the resolution pages are rendered at; positive.
        text_layer: read the PDF's own text as ``ocr_original``; not implemented (``True`` raises
            ``NotImplementedError``).
        default_metadata: goes into every page's metadata.
        paths_file, recursive, limit, skip, file_progress, doc_progress, shuffle_files: datatrove's
            ``BaseDiskReader`` arguments.
    """

    name = "📕 pdf"
    role = "reader"
    whole_items = True          # a PDF is one entry, so an item's pages stay in one task
    parts_added = ("image", "metadata")
    docs_args = {"data_folder": "pdfs/"}

    def __init__(self, data_folder: DataFolderLike, paths_file: DataFileLike | None = None,
                 glob_pattern: str = "**/*.pdf", dpi: float = 300, text_layer: bool = False, recursive: bool = True,
                 limit: int = -1, skip: int = 0, file_progress: bool = False, doc_progress: bool = False,
                 default_metadata: dict | None = None, shuffle_files: bool = False):
        super().__init__(data_folder, paths_file, limit, skip, file_progress, doc_progress, None, "text", "id",
                         default_metadata, recursive, glob_pattern, shuffle_files, add_file_path=False)
        if dpi <= 0:
            raise PipelineConfigError(f"PdfReader: dpi must be positive, not {dpi!r}")
        if text_layer:
            raise NotImplementedError("PdfReader(text_layer=True): reading a PDF's own text layer as ocr_original "
                                      "is not implemented yet")
        self.dpi, self.text_layer = dpi, text_layer

    def read_file(self, filepath: str):
        from ...images.convert import check_size

        pdf_module = pdfium()
        with self.data_folder.open(filepath, "rb") as f:
            data = f.read()
        item_id = safe_id(posixpath.basename(filepath).rsplit(".", 1)[0])
        uri = self.data_folder.resolve_paths(filepath)
        pdf = pdf_module.PdfDocument(data)
        try:
            self.stat_update("pdfs")
            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    width, height = page.get_size()
                    too_large = check_size(round(width * self.dpi / POINTS), round(height * self.dpi / POINTS))
                    if too_large:
                        logger.warning("pdf {uri} page {n}: {reason}", uri=uri, n=index + 1, reason=too_large)
                        self.stat_update("pages_too_large")
                        continue
                    with self.track_time():
                        image = render(page, self.dpi)
                finally:
                    page.close()
                sequence = index + 1
                metadata = {**(self.default_metadata or {}),
                            "pdf": {"page": sequence, "width_pt": width, "height_pt": height, "dpi": self.dpi}}
                doc = new_page_document(f"{item_id}_{sequence:04d}", image, uri=f"{uri}#page={sequence}",
                                        item_id=item_id, sequence=sequence, metadata=metadata)
                self.stat_update("pages")
                self.update_media_stats(doc.media[0])
                yield doc
        finally:
            pdf.close()
