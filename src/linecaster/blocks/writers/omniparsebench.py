"""``OmniParseBenchPredictionWriter``: each page of a run as the file Omni Parse Bench grades
(``linecaster.formats.omniparsebench``): ``<folder>/predictions/<page_id>.json``, or, for a page an earlier block failed
on, ``<folder>/records/<page_id>.json`` with the failure (``{"error": {"type", "message"}}``), which Omni Parse Bench
counts as the system's failure (all the page's tests failed, cause ``system``). The folder is then a folder of
predictions ``opb grade`` grades as it is. A rerun of a task writes its pages' files again."""
from __future__ import annotations

import json

from datatrove.io import DataFolderLike, get_datafolder
from datatrove.pipeline.base import PipelineStep

from ..base.contract import Contract, Contracted, parts
from ..base.page import ERRORS_KEY


class OmniParseBenchPredictionWriter(Contracted, PipelineStep):
    """Writes each page's Omni Parse Bench prediction (or its failure) and passes the page on.

    Args:
        output_folder: the predictions folder (local path or fsspec URI): ``predictions/`` and ``records/`` in it.
        transcription: the transcription written.
    """

    type = "💽 - WRITER"
    name = "🧪 Omni Parse Bench predictions"
    role = "writer"
    docs_args = {"output_folder": "out/omniparsebench"}

    def __init__(self, output_folder: DataFolderLike, transcription: str = "ocr_new"):
        super().__init__()
        self.output_folder, self.transcription = output_folder, transcription

    def contract(self) -> Contract:
        return Contract(unit="page", role=self.role, reads=parts({"*"}, self.transcription))

    def run(self, data, rank: int = 0, world_size: int = 1):
        from ...data import Page
        from ...formats.omniparsebench import prediction

        folder = get_datafolder(self.output_folder)
        for doc in data:
            errors = doc.metadata.get(ERRORS_KEY)
            if errors:
                last = errors[-1]
                body, name = {"error": {"type": str(last.get("type") or "error"),
                                        "message": str(last.get("error") or "")}}, f"records/{doc.id}.json"
                self.stat_update("failed")
            else:
                t = None
                if doc.metadata.get("page"):
                    t = Page.model_validate(doc.metadata["page"]).transcriptions.get(self.transcription)
                if t is None:
                    self.stat_update("no_transcription")
                with self.track_time():
                    body, name = prediction(t), f"predictions/{doc.id}.json"
                self.stat_update("pages")
            with folder.open(name, "wt", encoding="utf-8") as fh:
                json.dump(body, fh, ensure_ascii=False)
            yield doc
