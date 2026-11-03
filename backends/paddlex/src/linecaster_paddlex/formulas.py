"""Formula recognition with PaddleX's PP-FormulaNet.

PP-FormulaNet_plus-L and PP-FormulaNet-L ship as safetensors for PaddleX's ``transformers`` engine
(Hugging Face ``transformers`` on torch), so they run on the same torch and GPU as kraken's
recogniser; the official model source has no ONNX package for any formula model, and Paddle
Inference is not used. A formula region's crop goes in, LaTeX comes out. Ported from squiddleocr.
"""
from __future__ import annotations

import numpy as np

from linecaster.geometry import bbox_of
from linecaster.transcription import ModelInfo, Transcription

from .compat import create_transformers_predictor, paddle_image
from .crops import crop_bbox

DEFAULT_FORMULA_MODEL = "PP-FormulaNet_plus-L"


class PaddleFormulaModel:
    """linecaster engine model for the formulas step: LaTeX for every ``formula`` region, into
    ``region.extra["formula"]``. The page's formula crops are read together, in the regions' list order,
    ``batch_size`` crops per forward pass (a page's result depends only on the page)."""

    step = "formulas"

    def __init__(self, model_name: str = DEFAULT_FORMULA_MODEL, device: str = "auto", batch_size: int = 8):
        self.name, self.device, self.batch_size = model_name, device, batch_size
        self.predictor = None

    def load(self) -> None:
        self.predictor = create_transformers_predictor(self.name, self.device, batch_size=self.batch_size)

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
        transcription.model.append(ModelInfo(step=self.step, name=self.name, backend="paddlex/transformers",
                                             settings={"batch_size": self.batch_size}, measurements={"formulas": len(targets)}))
        return transcription
