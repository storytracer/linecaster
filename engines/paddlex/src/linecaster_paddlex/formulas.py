"""Formula recognition with PaddleX's PP-FormulaNet.

PP-FormulaNet_plus-L and PP-FormulaNet-L ship as safetensors for PaddleX's ``transformers`` engine
(Hugging Face ``transformers`` on torch), so they run on the same torch and GPU as kraken's
recognizer; the official model source has no ONNX package for any formula model, and Paddle
Inference is not used. A formula region's crop goes in, LaTeX comes out. Ported from squiddleocr.
"""
from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from linecaster.data import ModelInfo, Transcription
from linecaster.data.geometry import bbox_of

from .compat import create_transformers_predictor, paddle_image
from .crops import crop_bbox
from .weights import check, resolve

DEFAULT_FORMULA_MODEL = "PP-FormulaNet_plus-L"


class PaddleFormulaEngine:
    """linecaster engine for the formulas step: LaTeX for every ``formula`` region, into
    ``region.extra["formula"]``. The page's formula crops are read together, in the regions' list order,
    ``batch_size`` crops per forward pass (a page's result depends only on the page). The model files:
    ``weights`` (a catalog pin of the ``_safetensors`` package) or the catalog's newest pin for
    ``model_name`` (``weights.resolve``)."""

    engine_id: ClassVar[str] = "paddlex.formulas.v1"
    step = "formulas"
    capabilities: ClassVar[dict] = {"unit": "region", "produces": ["formulas", "latex"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid", protected_namespaces=())

        model_name: str = Field(DEFAULT_FORMULA_MODEL, description="PaddleX formula recognizer on the transformers "
                                                                   "engine: PP-FormulaNet_plus-L or PP-FormulaNet-L")
        device: str = Field("auto", description="auto (CUDA if available) or cpu (torch)")
        batch_size: int = Field(8, description="formula crops per forward pass")

    def __init__(self, model_name: str = DEFAULT_FORMULA_MODEL, device: str = "auto", batch_size: int = 8,
                 weights: dict | None = None):
        o = self.Options(model_name=model_name, device=device, batch_size=batch_size)
        check(o.model_name, weights, engine="transformers")
        self.options, self.weights = o, weights
        self.name, self.device, self.batch_size = o.model_name, o.device, o.batch_size
        self.revision: str | None = weights["revision"] if weights else None
        self.predictor = None

    def load(self) -> None:
        model_dir, self.revision = resolve(self.name, self.weights, engine="transformers")
        self.predictor = create_transformers_predictor(self.name, self.device, batch_size=self.batch_size,
                                                       model_dir=model_dir)

    def __call__(self, image: np.ndarray, transcription: Transcription, **params) -> Transcription:
        targets = [r for r in transcription.regions if r.label == "formula"]
        crops = [paddle_image(crop_bbox(image, bbox_of(r.polygon))) for r in targets]
        todo = [i for i, c in enumerate(crops) if c.size]
        latex = [""] * len(targets)
        if todo:
            for i, res in zip(todo, self.predictor.predict([crops[i] for i in todo])):
                latex[i] = str(res["rec_formula"]).strip()
        for region, text in zip(targets, latex):
            region.extra["formula"] = text
        transcription.model.append(ModelInfo(step=self.step, name=self.name, revision=self.revision,
                                             backend="paddlex/transformers",
                                             settings={"batch_size": self.batch_size}, measurements={"formulas": len(targets)}))
        return transcription
