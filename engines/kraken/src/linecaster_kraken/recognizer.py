"""kraken's own recogniser, unchanged: ``RecognitionTaskModel`` on kraken's PP-OCRv6 weights.

Lines are extracted, transformed, batched, decoded and turned into ``ocr_record``s (text,
per-character cuts and confidences) by kraken itself; the weights are kraken's safetensors from
their Hugging Face mirrors (pinned in the catalogue: ``models``), running on torch. Our part is ``segmentation.py`` (linecaster lines -> kraken's
``Segmentation``) and turning records into linecaster lines and words (``record_words``, kraken's rule).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar, Literal

import regex
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from linecaster.geometry import BBox, xywh
from linecaster.transcription import ModelInfo, Transcription, Word

from .models import MODEL_IDS, SIZES, fetch_weights, resolve_kraken_model, size_weights
from .segmentation import lines_to_segmentation


def mean_confidence(rec) -> float:
    conf = [float(c) for c in getattr(rec, "confidences", []) or []]
    return sum(conf) / len(conf) if conf else 0.0


def max_bbox(cuts) -> BBox:
    """kraken's ``serialization.max_bbox``: the box around all points of the character cuts."""
    flat = [x for pol in cuts for point in pol for x in point]
    return BBox(min(flat[::2]), min(flat[1::2]), max(flat[::2]), max(flat[1::2]))


def record_words(rec, line_id: str) -> list[Word]:
    """Words from a kraken record the way kraken's serialiser makes them: the prediction split at
    whitespace, a word's box the box around its characters' cuts, its confidence their mean."""
    words, offset = [], 0
    text = getattr(rec, "prediction", "") or ""
    cuts, confs = list(getattr(rec, "cuts", []) or []), list(getattr(rec, "confidences", []) or [])
    for segment in regex.split(r"(\s+)", text):
        if not segment:
            continue
        if not segment.isspace():
            seg_cuts, seg_conf = cuts[offset:offset + len(segment)], confs[offset:offset + len(segment)]
            words.append(Word(id=f"{line_id}_w{len(words)}", text=segment,
                              bbox=[float(v) for v in xywh(max_bbox(seg_cuts))] if seg_cuts else None,
                              confidence=float(sum(seg_conf) / len(seg_conf)) if seg_conf else None))
        offset += len(segment)
    return words


class KrakenRecognizer:
    """``kraken.tasks.recognition.RecognitionTaskModel`` with a ``RecognitionInferenceConfig``."""

    def __init__(self, model_path: str | Path, device: str = "auto", batch_size: int = 8,
                 num_line_workers: int = 0, text_direction: str = "horizontal-lr", precision: str = "auto",
                 compile_backbone: bool = False):
        import logging

        import torch

        from kraken.configs import RecognitionInferenceConfig
        from kraken.tasks.recognition import RecognitionTaskModel

        logging.getLogger("lightning.pytorch.utilities.rank_zero").setLevel(logging.WARNING)   # Tensor Core hint
        self.model_path = Path(model_path)
        self.task = RecognitionTaskModel.load_model(str(self.model_path))
        self.text_direction = text_direction
        # in-process line extraction (kraken's --num-line-workers 0): the worker pool would receive the whole page
        # image for every line
        # precision: "auto" = bf16-mixed on CUDA (the model was trained in bf16-mixed; 1.6x faster recognition on the
        # GB10, ~0.5 % of lines read differently), 32-true on the CPU. Needs the kraken fix that applies the Fabric
        # precision at inference (storytracer/kraken fix/inference-autocast); on upstream 7.1 the setting is inert.
        if precision == "auto":
            precision = "bf16-mixed" if device != "cpu" and torch.cuda.is_available() else "32-true"
        self.precision = precision
        self.config = RecognitionInferenceConfig(batch_size=max(int(batch_size), 1),
                                                 accelerator="cpu" if device == "cpu" else "auto",
                                                 num_line_workers=num_line_workers,
                                                 precision=precision)
        # RecognitionTaskModel.predict prepares the model on every call (a new Fabric, module moved again);
        # prepare once here and call the model's predict directly
        self.task.net.prepare_for_inference(self.config)
        if compile_backbone:
            import torch._dynamo

            # fewer, larger kernels; a compile error falls back to eager (and says so in the log)
            torch._dynamo.config.suppress_errors = True
            self.task.net.nn.backbone = torch.compile(self.task.net.nn.backbone, dynamic=True)
            logging.getLogger(__name__).info("kraken backbone wrapped in torch.compile(dynamic=True), torch %s",
                                             torch.__version__)

    @property
    def device(self) -> str:
        try:
            return str(next(self.task.net.parameters()).device)
        except StopIteration:  # pragma: no cover
            return "cpu"

    def predict(self, im: Image.Image, segmentation) -> list:
        """kraken's ``PPOCRv6Model.predict`` (what ``RecognitionTaskModel.predict`` calls after preparing the
        model) on a kraken ``Segmentation``; records in line order."""
        return list(self.task.net.predict(im=im, segmentation=segmentation))



class KrakenRecognitionModel:
    """linecaster engine model for the recognition step: kraken's PP-OCRv6 recogniser on every line of
    the transcription, in list order (the line step's processing order), ``batch_size`` lines per
    forward pass. A page's result depends only on the page. Fills text, confidence and words.

    The model file: ``weights`` (a catalogue pin, as a preset passes it) when given, else ``model``: a size
    name, resolved to its model document's newest pin, or a kraken model file."""

    engine_id: ClassVar[str] = "kraken.recognition.v1"
    step = "recognition"
    capabilities: ClassVar[dict] = {"unit": "line",
                                    "produces": ["text", "words", "word_confidences", "line_confidences"]}

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        model: str = Field("medium", description="PP-OCRv6 size (tiny, small, medium) or a path to a kraken "
                                                 "model file; with weights, the size the pin is of")
        device: str = Field("auto", description="auto (CUDA if available), cpu or cuda")
        batch_size: int = Field(8, description="lines per forward pass; kraken pads a batch to its widest line, "
                                               "so the batch size can move numerics")
        precision: str = Field("auto", description="Lightning precision at inference; auto: bf16-mixed on CUDA "
                                                   "(the training precision), 32-true on the CPU")
        text_direction: Literal["horizontal-lr", "horizontal-rl", "vertical-lr", "vertical-rl"] = Field(
            "horizontal-lr", description="kraken's text direction of the lines (horizontal-rl: right to left)")
        compile_backbone: bool = Field(False, description="torch.compile the backbone (dynamic shapes): fewer "
                                                          "kernel launches, minutes of compiling when the model "
                                                          "loads; moves a few characters")

    def __init__(self, model: str = "medium", device: str = "auto", batch_size: int = 8, precision: str = "auto",
                 text_direction: str = "horizontal-lr", compile_backbone: bool = False, weights: dict | None = None):
        o = self.Options(model=str(model), device=device, batch_size=batch_size, precision=precision,
                         text_direction=text_direction, compile_backbone=compile_backbone)
        self.options, self.weights = o, weights
        self.model, self.device, self.batch_size, self.precision_setting = o.model, o.device, o.batch_size, o.precision
        self.text_direction, self.compile_backbone = o.text_direction, o.compile_backbone
        size = o.model.lower()
        if weights is not None and MODEL_IDS.get(size) != weights["model"]:
            raise ValueError(f"model={o.model!r} does not name the pinned weights {weights['model']!r}")
        self.name = weights["model"] if weights else MODEL_IDS.get(size, o.model)
        self.revision: str | None = weights["revision"] if weights else None
        self.recognizer: KrakenRecognizer | None = None

    def load(self) -> None:
        import torch

        torch.backends.cudnn.benchmark = False   # no autotuning: the same kernels for the same shapes every run
        weights = self.weights
        if weights is None and self.model.lower() in SIZES and not Path(self.model).is_file():
            weights = size_weights(self.model.lower())
        path = fetch_weights(weights) if weights is not None else resolve_kraken_model(self.model)
        self.revision = weights["revision"] if weights is not None else None
        self.recognizer = KrakenRecognizer(path, self.device, self.batch_size, text_direction=self.text_direction,
                                           precision=self.precision_setting, compile_backbone=self.compile_backbone)

    def __call__(self, image, transcription: Transcription, **params) -> Transcription:
        lines = transcription.lines
        if lines:
            h, w = image.shape[:2]
            seg = lines_to_segmentation(w, h, lines, self.text_direction)
            for ln, rec in zip(lines, self.recognizer.predict(Image.fromarray(image), seg), strict=True):
                ln.text = rec.prediction
                ln.confidence = mean_confidence(rec)
                ln.words = record_words(rec, ln.id)
        transcription.model.append(ModelInfo(step=self.step, name=self.name, revision=self.revision,
                                             backend=f"kraken/torch ({self.recognizer.device})",
                                             settings={"batch_size": self.batch_size, "precision": self.recognizer.precision,
                                                       "text_direction": self.text_direction,
                                                       **({"compile_backbone": True} if self.compile_backbone else {})}))
        return transcription
