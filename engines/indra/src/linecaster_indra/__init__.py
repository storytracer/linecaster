"""Indra OCR engines for linecaster: Datalab's CPU OCR pipeline (the ``indra-ocr`` package, ONNX Runtime) on whole
pages."""
from .recognizer import IndraRecognitionEngine

__all__ = ["IndraRecognitionEngine"]
