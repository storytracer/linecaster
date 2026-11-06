"""The base of linecaster's blocks: one page per datatrove ``Document`` (``PageBlock``), the model blocks' base
with its backend (``ModelBlock``), the rule-based blocks' (``RuleBlock``); contracts (``Contract``, ``Part``),
composites (``Composite``) and item records (``item``)."""
from .composite import Composite
from .contract import Contract, Contracted, Part
from .model import ModelBlock
from .page import PageBlock, decode_rgb, image_bytes, new_page_document, page_of, set_page
from .rule import RuleBlock

__all__ = ["Composite", "Contract", "Contracted", "decode_rgb", "image_bytes", "ModelBlock", "new_page_document",
           "page_of", "PageBlock", "Part", "RuleBlock", "set_page"]
