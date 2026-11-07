"""Readers: page images from folders and Parquet files, items' manifests (IIIF, METS), PDF files, page records of an
earlier run, and items' remote files (resources)."""
from .images import ImageFolderReader, ImageParquetReader
from .manifests import ManifestReader
from .pdf import PdfReader
from .records import PageRecordReader
from .resources import ResourceReader

__all__ = ["ImageFolderReader", "ImageParquetReader", "ManifestReader", "PageRecordReader", "PdfReader",
           "ResourceReader"]
