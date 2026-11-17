"""Readers: page images from folders and Parquet files, items' manifests (IIIF, METS), PDF files, page records of an
earlier run, and items' remote files (resources)."""
from linecaster.blocks.readers.images import ImageFolderReader, ImageParquetReader
from linecaster.blocks.readers.manifests import ManifestReader
from linecaster.blocks.readers.pdf import PdfReader
from linecaster.blocks.readers.records import PageRecordReader
from linecaster.blocks.readers.resources import ResourceReader

__all__ = ["ImageFolderReader", "ImageParquetReader", "ManifestReader", "PageRecordReader", "PdfReader",
           "ResourceReader"]
