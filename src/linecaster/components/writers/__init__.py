"""Writers: page records, per-page files, page images, item documents and texts, rejects, resources, scores."""
from linecaster.components.writers.files import PageFileWriter
from linecaster.components.writers.images import ImageFilesWriter
from linecaster.components.writers.items import ItemDocumentWriter, ItemTextWriter, item_texts
from linecaster.components.writers.records import PageJsonlWriter, PageParquetWriter
from linecaster.components.writers.rejects import RejectWriter
from linecaster.components.writers.resources import ResourceFilesWriter, ResourceRecordWriter
from linecaster.components.writers.scores import ScoreWriter

__all__ = ["ImageFilesWriter", "ItemDocumentWriter", "ItemTextWriter", "PageFileWriter", "PageJsonlWriter",
           "PageParquetWriter", "RejectWriter", "ResourceFilesWriter", "ResourceRecordWriter", "ScoreWriter", "item_texts"]
