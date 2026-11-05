"""Table structure with PaddleX's table pipeline, fed with the page's own lines and recognized text.

PaddleX's ``table_recognition_v2`` pipeline is what PP-StructureV3 runs on a table: a wired/wireless
classifier, SLANeXt / SLANet structure models, RT-DETR cell detectors and a matching step that
places OCR boxes into the cells. Its ``predict`` accepts an external OCR result, so it gets the
text lines the line step detected on the page and kraken's transcriptions instead of running its own
OCR; the HTML it returns carries our text in its cells.

Defaults for historical print (2026-09-07, NOTES): ``SLANet_plus`` end to end for both table
classes, i.e. structure and cell boxes from SLANet_plus's own prediction (``e2e=True``), the cell
detectors unused. PP-StructureV3's default (SLANeXt_wired + cell detector for what the classifier
calls wired) merges rows on old ruled tables; SLANet_plus keeps them apart. The table crop is
grown by ``crop_pad`` pixels: with the layout box exactly, the models can flip to a worse cell
set, from 8 px on the result is stable.
"""
from __future__ import annotations

import html
import re
from typing import ClassVar, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from dataclasses import dataclass, field

from linecaster.data import StepInfo, Transcription
from linecaster.data.geometry import BBox, bbox_of, xywh

from .compat import create_pipeline, paddle_image
from .crops import crop_bbox
from .weights import catalog_weights, check, resolve


@dataclass
class TableCellResult:
    text: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    bbox: BBox | None = None
    header: bool = False


@dataclass
class TableResult:
    region_id: str
    cells: list[TableCellResult] = field(default_factory=list)
    num_rows: int = 0
    num_cols: int = 0
    html: str | None = None

_ATTR = re.compile(r'(colspan|rowspan)="?(\d+)"?')
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t([dh])([^>]*)>(.*?)</t[dh]>", re.S)


def table_pipeline_config(wired: str = "SLANet_plus", wireless: str = "SLANet_plus", classifier: str = "PP-LCNet_x1_0_table_cls",
                          wired_cells: str = "RT-DETR-L_wired_table_cell_det", wireless_cells: str = "RT-DETR-L_wireless_table_cell_det",
                          model_dirs: dict[str, str | None] | None = None) -> dict:
    """PaddleX's ``table_recognition_v2`` config without layout, preprocessing or its own OCR.
    PP-StructureV3's own choice would be ``wired="SLANeXt_wired"``. ``model_dirs``: model name -> local folder
    (unnamed models are downloaded by PaddleX)."""
    dirs = model_dirs or {}
    mod = lambda module, name: {"module_name": module, "model_name": name, "model_dir": dirs.get(name)}  # noqa: E731
    return {"pipeline_name": "table_recognition_v2", "use_doc_preprocessor": False, "use_layout_detection": False, "use_ocr_model": False,
            "SubModules": {"TableClassification": mod("table_classification", classifier),
                           "WiredTableStructureRecognition": mod("table_structure_recognition", wired),
                           "WirelessTableStructureRecognition": mod("table_structure_recognition", wireless),
                           "WiredTableCellsDetection": mod("table_cells_detection", wired_cells),
                           "WirelessTableCellsDetection": mod("table_cells_detection", wireless_cells),
                           "TableOrientationClassify": mod("doc_text_orientation", "PP-LCNet_x1_0_doc_ori")}}


def parse_structure(tokens: Sequence[str]) -> list[tuple[int, int, int, int]]:
    """Turn a structure model's token list into ``(row, col, row_span, col_span)`` per cell, in cell order."""
    cells = []
    i, row = 0, -1
    while i < len(tokens):
        t = tokens[i]
        if t == "<tr>":
            row += 1
            cells.append(("row", None))
        elif t.startswith("<td"):
            attrs = ""
            if t in ("<td", "<td "):  # attributes follow as separate tokens until '>'
                i += 1
                while i < len(tokens) and tokens[i] != ">":
                    attrs += tokens[i]
                    i += 1
            cells.append(("cell", attrs + t))
        i += 1
    return [c for c, _ in _place([(kind, attrs, "") for kind, attrs in cells])]


def _place(items: Sequence[tuple[str, str, str]]) -> list[tuple[tuple[int, int, int, int], str]]:
    """Grid placement: ``items`` are ("row", _, _) markers and ("cell", attrs, text); returns
    ``((row, col, row_span, col_span), text)`` per cell, spans occupying the grid like HTML does."""
    out, grid, row, col = [], set(), -1, 0
    for kind, attrs, text in items:
        if kind == "row":
            row, col = row + 1, 0
            continue
        spans = dict(_ATTR.findall(attrs))
        rs, cs = int(spans.get("rowspan", 1)), int(spans.get("colspan", 1))
        while (row, col) in grid:
            col += 1
        for r in range(row, row + rs):
            for c in range(col, col + cs):
                grid.add((r, c))
        out.append(((row, col, rs, cs), text))
        col += cs
    return out


def cells_from_html(table_html: str) -> list[TableCellResult]:
    """``TableCellResult``s (row, col, spans, text, header flag) from a ``<table>`` HTML string."""
    items: list[tuple[str, str, str]] = []
    headers: list[bool] = []
    for row in _ROW.findall(table_html):
        items.append(("row", "", ""))
        for tag, attrs, inner in _CELL.findall(row):
            text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inner)).split())
            items.append(("cell", attrs, text))
            headers.append(tag == "h")
    return [TableCellResult(text, r, c, rs, cs, None, header=h) for ((r, c, rs, cs), text), h in zip(_place(items), headers)]


class PaddleTableRecognizer:
    """PaddleX's table pipeline on ONNX Runtime, fed with the page's own lines and kraken's text."""

    def __init__(self, device: str = "auto", crop_pad: int = 8, e2e: bool = True, config: dict | None = None):
        self.crop_pad, self.e2e = crop_pad, e2e
        self.pipeline = create_pipeline(config or table_pipeline_config(), device)

    def structure(self, image: np.ndarray, region, lines: Sequence = (), texts: Sequence[str] = ()) -> TableResult:
        """``region`` and ``lines`` are linecaster Region / Line objects (boxes from their polygons)."""
        from paddlex.inference.pipelines.ocr.result import OCRResult

        h, w = image.shape[:2]
        rb = bbox_of(region.polygon)
        b = BBox(rb.x0 - self.crop_pad, rb.y0 - self.crop_pad, rb.x1 + self.crop_pad, rb.y1 + self.crop_pad).clipped(w, h)
        dx, dy = int(b.x0), int(b.y0)
        crop = paddle_image(crop_bbox(image, b))
        if crop.size == 0:
            return TableResult(region.id)
        texts = [str(t) for t in texts]
        lbs = [bbox_of(ln.polygon) for ln in lines]
        polys = np.array([(lb.polygon - (dx, dy)).astype(int) for lb in lbs]).reshape(-1, 4, 2)
        boxes = np.array([[int(lb.x0) - dx, int(lb.y0) - dy, int(lb.x1) - dx, int(lb.y1) - dy] for lb in lbs]).reshape(-1, 4)
        ocr = OCRResult({"input_path": None, "page_index": None, "input_img": crop, "doc_preprocessor_res": {"output_img": crop},
                         "dt_polys": polys, "rec_polys": polys, "rec_boxes": boxes, "rec_texts": texts,
                         "rec_scores": [1.0] * len(texts), "rec_labels": ["text"] * len(texts),
                         "model_settings": {"use_doc_preprocessor": False, "use_textline_orientation": False},
                         "text_det_params": {}, "text_type": "general", "textline_orientation_angles": [-1] * len(texts)})
        res = next(iter(self.pipeline.predict(crop, use_doc_orientation_classify=False, use_doc_unwarping=False, use_layout_detection=False,
                                              use_ocr_model=False, overall_ocr_res=ocr, use_ocr_results_with_table_cells=False,
                                              use_table_orientation_classify=False, use_e2e_wired_table_rec_model=self.e2e,
                                              use_e2e_wireless_table_rec_model=self.e2e)))
        tables = res.get("table_res_list") or []
        if not tables:
            return TableResult(region.id)
        t = tables[0]
        pred_html = str(t.get("pred_html", ""))
        cells = cells_from_html(pred_html)
        raw_boxes = t.get("cell_box_list")
        cell_boxes = [] if raw_boxes is None else [np.asarray(cb, dtype=float).reshape(-1, 2) for cb in raw_boxes]
        if len(cell_boxes) == len(cells):
            for cell, cb in zip(cells, cell_boxes):
                cell.bbox = BBox.of(cb + np.array([dx, dy]))
        num_rows = max((c.row + c.row_span for c in cells), default=0)
        num_cols = max((c.col + c.col_span for c in cells), default=0)
        return TableResult(region.id, cells, num_rows, num_cols, html=pred_html)


class PaddleTableEngine:
    """linecaster engine for the tables step: the cell structure of every ``table`` region, with the
    region's recognized lines placed into the cells (needs the recognition step first). The result goes
    into ``region.extra["table"]``: ``num_rows``, ``num_cols``, ``html`` and ``cells`` (text, row, col,
    row_span, col_span, bbox, header).

    The pipeline's models: the structure model (``STRUCTURE``, for wired and wireless tables) from ``weights``
    (a catalog pin) or the catalog's newest pin; the classifier and the two cell detectors (``SUBMODELS``) at
    ``submodel_weights`` (catalog pins by PaddleX name, from a preset's ``submodels``), else
    ``submodel_revisions`` (each a pin of its model document; edition 1 of ``slanet-plus``), else their newest
    pins."""

    engine_id: ClassVar[str] = "paddlex.tables.v1"
    step = "tables"
    capabilities: ClassVar[dict] = {"unit": "region", "produces": ["tables", "html"]}
    #: the structure model for both table classes, and the pipeline's other models (``table_pipeline_config``)
    STRUCTURE = "SLANet_plus"
    SUBMODELS = ("PP-LCNet_x1_0_table_cls", "RT-DETR-L_wired_table_cell_det", "RT-DETR-L_wireless_table_cell_det")

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        device: str = Field("auto", description="auto, cpu, cuda, tensorrt or coreml (ONNX Runtime providers)")
        crop_pad: int = Field(8, description="pixels the table region's crop is grown by (with the exact layout "
                                             "box the models can flip to a worse cell set; stable from 8 px)")
        e2e: bool = Field(True, description="structure and cell boxes from SLANet_plus's own prediction for both "
                                            "table classes (False: the cell detectors, PP-StructureV3's route)")
        name: str = Field("table_recognition_v2/SLANet_plus", description="the name recorded in StepInfo")
        submodel_revisions: dict[str, str] | None = Field(
            None, description="PaddleX model name -> Hugging Face commit of its ONNX package, for the table "
                              "classifier and the cell detectors; each must be a pin in the catalog (None: the "
                              "newest pins)")

    def __init__(self, device: str = "auto", crop_pad: int = 8, e2e: bool = True, name: str = "table_recognition_v2/SLANet_plus",
                 submodel_revisions: dict[str, str] | None = None, weights: dict | None = None,
                 submodel_weights: dict[str, dict] | None = None):
        o = self.Options(device=device, crop_pad=crop_pad, e2e=e2e, name=name, submodel_revisions=submodel_revisions)
        check(self.STRUCTURE, weights)
        unknown = (set(o.submodel_revisions or {}) | set(submodel_weights or {})) - set(self.SUBMODELS)
        if unknown:
            raise ValueError(f"submodel_revisions: {sorted(unknown)} are not models of the pipeline {self.SUBMODELS}")
        self.options, self.weights, self.submodel_weights = o, weights, submodel_weights or {}
        self.device, self.crop_pad, self.e2e, self.name = o.device, o.crop_pad, o.e2e, o.name
        self.revision: str | None = weights["revision"] if weights else None
        self.recognizer: PaddleTableRecognizer | None = None

    def load(self) -> None:
        dirs = {}
        dirs[self.STRUCTURE], self.revision = resolve(self.STRUCTURE, self.weights)
        for name in self.SUBMODELS:
            rev = (self.options.submodel_revisions or {}).get(name)
            w = self.submodel_weights.get(name) or (catalog_weights(name, revision=rev) if rev else None)
            dirs[name] = resolve(name, w)[0]
        self.recognizer = PaddleTableRecognizer(self.device, self.crop_pad, self.e2e,
                                                config=table_pipeline_config(model_dirs=dirs))

    def __call__(self, image: np.ndarray, transcription: Transcription, **params) -> Transcription:
        n = 0
        for region in transcription.regions:
            if region.label != "table":
                continue
            lines = [ln for ln in transcription.lines if ln.region_id == region.id]
            res = self.recognizer.structure(image, region, lines, [ln.text or "" for ln in lines])
            region.extra["table"] = {
                "num_rows": res.num_rows, "num_cols": res.num_cols, "html": res.html,
                "cells": [{"text": c.text, "row": c.row, "col": c.col, "row_span": c.row_span, "col_span": c.col_span,
                           "bbox": xywh(c.bbox) if c.bbox is not None else None, "header": c.header} for c in res.cells]}
            n += 1
        transcription.steps.append(StepInfo(step=self.step, name=self.name, revision=self.revision,
                                            backend="paddlex/onnxruntime",
                                            settings={"crop_pad": self.crop_pad, "e2e": self.e2e}, measurements={"tables": n}))
        return transcription
