"""Writers: page records, per-page files, page images, item documents and texts, rejects, resources, scores."""
from linecaster.blocks.writers.files import PageFileWriter
from linecaster.blocks.writers.images import ImageFilesWriter
from linecaster.blocks.writers.items import ItemDocumentWriter, ItemTextWriter, item_texts
from linecaster.blocks.writers.records import PageJsonlWriter, PageParquetWriter
from linecaster.blocks.writers.rejects import RejectWriter
from linecaster.blocks.writers.resources import ResourceFilesWriter, ResourceRecordWriter
from linecaster.blocks.writers.scores import ScoreWriter

__all__ = ["ImageFilesWriter", "ItemDocumentWriter", "ItemTextWriter", "PageFileWriter", "PageJsonlWriter",
           "PageParquetWriter", "RejectWriter", "ResourceFilesWriter", "ResourceRecordWriter", "ScoreWriter", "item_texts"]
