"""Writers: page records, per-page files, page images, item documents and texts, rejects, resources, scores, OmniDocBench
samples."""
from .files import PageFileWriter
from .images import ImageFilesWriter
from .items import ItemDocumentWriter, ItemTextWriter, item_texts
from .omnidocbench import OmniDocBenchWriter
from .records import PageJsonlWriter, PageParquetWriter
from .rejects import RejectWriter
from .resources import ResourceFilesWriter, ResourceRecordWriter
from .scores import ScoreWriter

__all__ = ["ImageFilesWriter", "ItemDocumentWriter", "ItemTextWriter", "OmniDocBenchWriter", "PageFileWriter", "PageJsonlWriter",
           "PageParquetWriter", "RejectWriter", "ResourceFilesWriter", "ResourceRecordWriter", "ScoreWriter",
           "item_texts"]
