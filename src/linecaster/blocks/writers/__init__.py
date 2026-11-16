"""Writers: page records, per-page files, page images, item documents and texts, rejects, resources, scores, harness
shards."""
from .files import PageFileWriter
from .harness import HarnessWriter
from .images import ImageFilesWriter
from .items import ItemDocumentWriter, ItemTextWriter, item_texts
from .records import PageJsonlWriter, PageParquetWriter
from .rejects import RejectWriter
from .resources import ResourceFilesWriter, ResourceRecordWriter
from .scores import ScoreWriter

__all__ = ["HarnessWriter", "ImageFilesWriter", "ItemDocumentWriter", "ItemTextWriter", "PageFileWriter", "PageJsonlWriter",
           "PageParquetWriter", "RejectWriter", "ResourceFilesWriter", "ResourceRecordWriter", "ScoreWriter",
           "item_texts"]
