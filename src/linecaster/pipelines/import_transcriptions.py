"""Importing transcriptions (``import_transcriptions.v1``): a source's documents read into page records by an
importer, a ground truth by default, for scoring (``linecaster score``) or as a dataset's records.

The documents come from a Parquet table (``--parquet``: a row per page, its id in ``--id-key``, its item in
``--item-key``) or a folder of files: in a column of the table (``--data-key``, the document's content, as a wiki
page's wikitext), in a file a column names (``--uri-key``), or delivered with the page (a manifest's OCR file). The
importer is a preset of step ``import`` (``auto-import``, ``alto-import``, ...) or an importer's engine id
(``import.mediawiki.v1`` from ``linecaster-mediawiki``); ``--set import.OPTION=VALUE`` sets its options (``ground_truth``,
``conventions``, an engine's own such as ``site``). ``--context-key`` columns go to the importer as the document's
context; ``record``, ``revision`` and ``dataset`` columns go to the transcription's source. The page images are named,
not read (``--image-key``, or none). Page records in OUT/pages, failed pages in OUT/rejects.

    uv run pipelines/import_transcriptions.py OUT --parquet pages.parquet --id-key page --item-key item \\
        --data-key wikitext --context-key title --context-key revision \\
        --importer import.mediawiki.v1 --set import.site=SITE --set import.conventions=example
    uv run pipelines/import_transcriptions.py OUT --parquet ocr.parquet --data-key alto --importer alto-import
"""
from ..blocks.conversion.transcriptions import TranscriptionImporter
from ..errors import PipelineConfigError
from ..runtime import run


def options(ap):
    ap.add_argument("--importer", help="the importer: a preset of step import (e.g. auto-import) or an importer's "
                                       "engine id (e.g. import.mediawiki.v1); needed")
    ap.add_argument("--set", action="append", default=[], metavar="import.OPTION=VALUE",
                    help="an importer option, e.g. import.conventions=example; repeatable")
    ap.add_argument("--data-key", help="the table's column with each document's content")
    ap.add_argument("--uri-key", help="the table's column with each document's path or URL")
    ap.add_argument("--context-key", action="append", default=[],
                    help="a column given to the importer as the document's context (record, revision and dataset go "
                         "to the transcription's source); repeatable")
    ap.add_argument("--transcription", default="ground_truth", help="the transcription it fills (default "
                                                                    "ground_truth)")


def models(a) -> list[dict]:
    return []


def importer(a):
    """The importer as a rule block takes it: a preset ref, or an engine id as an in-process engine spec."""
    from ..backends import InProcess
    from ..catalog.registry import engine_ids

    if not a.importer:
        raise PipelineConfigError("import_transcriptions: pick --importer (a preset of step import, e.g. "
                                  "auto-import, or an importer's engine id)")
    if "@" not in a.importer and a.importer in engine_ids():
        return InProcess(engine_ids()[a.importer])
    return a.importer


def pipeline(a, script: str):
    if bool(a.data_key) == bool(a.uri_key) and (a.data_key or a.uri_key):
        raise PipelineConfigError("import_transcriptions: --data-key or --uri-key, not both")
    source = "metadata" if a.data_key else "uri" if a.uri_key else "media"
    over = run.overrides(a.set, steps=["import"])
    block = TranscriptionImporter(importer(a), source=source, transcription=a.transcription, uri_key=a.uri_key,
                                  data_key=a.data_key, context_keys=tuple(a.context_key), options=over.get("import"))
    return [run.reader(a, read_images=False), block, run.pages(a)], {"engines": False}


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "import_transcriptions.v1"
SLOTS = {"import": "importer"}
