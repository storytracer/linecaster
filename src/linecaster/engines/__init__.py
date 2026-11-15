"""linecaster's built-in engines: the rule-based steps (``image``, ``typography``, ``recomposition``,
``composition``, ``import``) and the single-region layout, pure Python and in-process only, registered in
``linecaster.catalog.registry.BUILTIN_ENGINES``. The protocol and the dispatch by script are in
``linecaster.engines.base``, the scripts in ``linecaster.engines.scripts``; the rules themselves stay in
``linecaster.text``, ``linecaster.images`` and ``linecaster.formats`` (the engines are thin). Import-light, like
the data model: no datatrove, saturate, blocks or runtime."""
from .base import RuleEngine, ScriptDispatch, Strategy
from .composition import LinkedCompositionEngine
from .image import ImageConvertEngine, WebpLosslessImageEngine
from .importers import (
    AltoImporter, AutoImporter, DoclingImporter, HocrImporter, HtmlImporter, Importer, PageXmlImporter, TeiImporter,
    TextImporter,
)
from .layout import SingleRegionLayoutEngine
from .recomposition import ByScriptRecompositionEngine, UnicodeRecompositionEngine
from .typography import RatiosTypographyEngine

__all__ = [
    "AltoImporter", "AutoImporter", "DoclingImporter", "HocrImporter", "HtmlImporter", "Importer", "PageXmlImporter",
    "TeiImporter", "TextImporter", "ByScriptRecompositionEngine", "LinkedCompositionEngine", "ImageConvertEngine",
    "RatiosTypographyEngine", "RuleEngine", "ScriptDispatch",
    "SingleRegionLayoutEngine", "Strategy", "UnicodeRecompositionEngine", "WebpLosslessImageEngine",
]
