"""The base of linecaster's blocks: one page per datatrove ``Document`` (``PageBlock``), and the model
blocks' base with its backend (``ModelBlock``)."""
from .model import ModelBlock
from .page import PageBlock, decode_rgb, image_bytes, new_page_document, page_of, set_page

__all__ = ["decode_rgb", "image_bytes", "ModelBlock", "new_page_document", "page_of", "PageBlock", "set_page"]
