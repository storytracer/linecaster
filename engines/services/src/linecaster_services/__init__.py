"""Page engines for linecaster that call a vendor's page pipeline behind its own HTTP API: Falcon-OCR's pipeline
service and OXR's all-in-one service. Each service runs in the vendor's image (linecaster's ``ServiceServer`` starts
it from the preset); the engines are its clients, in the pipeline's process, one page per request."""
from .falcon import FalconRecognitionEngine
from .oxr import OxrRecognitionEngine

__all__ = ["FalconRecognitionEngine", "OxrRecognitionEngine"]
