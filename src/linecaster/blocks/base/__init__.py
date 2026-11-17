"""The base of linecaster's blocks: one page per datatrove ``Document`` (``PageBlock``), the model blocks' base
with its backend (``ModelBlock``), the rule-based blocks' (``RuleBlock``); contracts (``Contract``, ``Part``),
composites (``Composite``) and item records (``item``)."""
from linecaster.blocks.base.composite import Composite
from linecaster.blocks.base.contract import Contract, Contracted, Part
from linecaster.blocks.base.model import ModelBlock
from linecaster.blocks.base.page import PageBlock, decode_rgb, image_bytes, new_page_document, page_of, set_page
from linecaster.blocks.base.rule import RuleBlock

__all__ = ["Composite", "Contract", "Contracted", "decode_rgb", "image_bytes", "ModelBlock", "new_page_document",
           "page_of", "PageBlock", "Part", "RuleBlock", "set_page"]
