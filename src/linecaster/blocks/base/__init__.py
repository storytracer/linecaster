"""The base of linecaster's blocks: one page per datatrove ``Document`` (``PageStep``), and the model
blocks' base with its backend (``ModelStep``)."""
from .model import ModelStep
from .page import PageStep, decode_rgb, image_bytes, new_page_document, page_of, set_page

__all__ = ["decode_rgb", "image_bytes", "ModelStep", "new_page_document", "page_of", "PageStep", "set_page"]
