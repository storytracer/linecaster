"""``ImageFilesWriter``: page images (and a library's own OCR) as files, ``<item_id>/<page_id>.<ext>``."""
from __future__ import annotations

from datatrove.io import DataFolderLike
from datatrove.pipeline.base import PipelineStep


#: file extension per image format (Pillow's names, as ``PageImage.format`` holds them)
IMAGE_FILE_EXTENSIONS = {"jpeg": "jpg", "png": "png", "webp": "webp", "tiff": "tif", "jpeg2000": "jp2",
                         "gif": "gif", "bmp": "bmp"}


class ImageFilesWriter(PipelineStep):
    """Each page's image bytes as they came, one file per page: ``<output_folder>/<item_id>/<page_id>.<ext>``
    (any fsspec folder; ``<page_id>.<ext>`` for pages without an item), the extension from the image's format.
    The page's ``image.uri`` then names the written file and ``image.extra["source_uri"]`` where it came from,
    so page records written after this block point at the copy (``PageRecordReader`` fetches it from there), and
    ``ImageFolderReader(output_folder, item_from_parent=True)`` reads the folder as it is.

    With ``ocr_folder``, a library's own OCR that came with the page (a document media, as ``ManifestReader``'s
    ``existing_ocr`` adds it) is written the same way, ``<ocr_folder>/<item_id>/<page_id>.xml`` (ALTO) or
    ``.html`` (hOCR), and its transcription's ``source.extra["file"]`` names the copy. Pages pass through."""

    type = "💽 - WRITER"
    name = "🖼️ image files"

    def __init__(self, output_folder: DataFolderLike, ocr_folder: DataFolderLike | None = None):
        super().__init__()
        self.output_folder, self.ocr_folder = output_folder, ocr_folder

    @staticmethod
    def _path(page, ext: str) -> str:
        return f"{page.item_id}/{page.page_id}.{ext}" if page.item_id else f"{page.page_id}.{ext}"

    def run(self, data, rank: int = 0, world_size: int = 1):
        from datatrove.data import MediaType
        from datatrove.io import get_datafolder

        from ..base.page import image_bytes, page_of, set_page
        from ..readers.manifests import OCR_EXTENSIONS, OCR_ORIGINAL

        out = get_datafolder(self.output_folder)
        ocr_out = get_datafolder(self.ocr_folder) if self.ocr_folder is not None else None
        for doc in data:
            page = page_of(doc)
            fmt = (page.image.format if page.image else None) or ""
            path = self._path(page, IMAGE_FILE_EXTENSIONS.get(fmt, fmt or "bin"))
            with self.track_time():
                with out.open(path, "wb") as f:
                    f.write(image_bytes(doc))
            source = page.image.uri
            extra = {**page.image.extra, "source_uri": source} if source else page.image.extra
            page = page.model_copy(update={"image": page.image.model_copy(
                update={"uri": out.resolve_paths(path), "extra": extra})})
            self.stat_update("images")
            ocr = next((m for m in doc.media if m.type == MediaType.DOCUMENT and m.media_bytes), None)
            if ocr_out is not None and ocr is not None and OCR_ORIGINAL in page.transcriptions:
                t = page.transcriptions[OCR_ORIGINAL]
                ocr_path = self._path(page, OCR_EXTENSIONS.get(t.source.format or "", "xml"))
                with ocr_out.open(ocr_path, "wb") as f:
                    f.write(ocr.media_bytes)
                t.source.extra["file"] = ocr_out.resolve_paths(ocr_path)
                self.stat_update("ocr_files")
            set_page(doc, page)
            yield doc
