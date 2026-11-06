"""Surya OCR engines for linecaster: Datalab's ``surya-ocr`` package, its full-page path, attached to a vLLM server
that serves the pinned checkpoint."""
from .recognizer import SuryaRecognitionEngine, blocks_of, package_flags

__all__ = ["SuryaRecognitionEngine", "blocks_of", "package_flags"]
