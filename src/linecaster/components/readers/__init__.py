"""Readers: page images from folders and Parquet files, items' manifests (IIIF, METS), PDF files, page records of an
earlier run, and items' remote files (resources)."""
from linecaster.components.readers.images import ImageFolderReader, ImageParquetReader
from linecaster.components.readers.manifests import ManifestReader
from linecaster.components.readers.pdf import PdfReader
from linecaster.components.readers.records import PageRecordReader
from linecaster.components.readers.resources import ResourceReader

__all__ = ["ImageFolderReader", "ImageParquetReader", "ManifestReader", "PageRecordReader", "PdfReader",
           "ResourceReader"]
