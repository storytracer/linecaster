"""linecaster's built-in engines: the rule-based steps (``image``, ``hierarchy``, ``paragraphs``,
``document``, ``import``), the taggers (``tagging``, ``linecaster.engines.tagging``) and the single-region
layout, pure Python and in-process only, registered in ``linecaster.catalog.registry.BUILTIN_ENGINES``. The protocol and the dispatch by script are in
``linecaster.engines.base``, the scripts in ``linecaster.engines.scripts``; the rules themselves stay in
``linecaster.text``, ``linecaster.images`` and ``linecaster.formats`` (the engines are thin). Import-light, like
the data model: no datatrove, saturate, blocks or runtime."""
from linecaster.engines.base import RuleEngine, ScriptDispatch, Strategy
from linecaster.engines.document import LinkedDocumentEngine
from linecaster.engines.image import ImageConvertEngine, WebpLosslessImageEngine
from linecaster.engines.importers import (
    AltoImporter, AutoImporter, DoclingImporter, HocrImporter, HtmlImporter, IiifImporter, Importer,
    OmniDocBenchImporter, PageXmlImporter, TeiImporter, TextImporter,
)
from linecaster.engines.layout import SingleRegionLayoutEngine
from linecaster.engines.paragraphs.engine import ByScriptParagraphsEngine, UnicodeParagraphsEngine
from linecaster.engines.tagging import ChatTaggingEngine, GeometryTaggingEngine
from linecaster.engines.hierarchy.engine import RatiosHierarchyEngine

__all__ = [
    "AltoImporter", "AutoImporter", "DoclingImporter", "HocrImporter", "HtmlImporter", "IiifImporter", "Importer",
    "OmniDocBenchImporter", "PageXmlImporter",
    "TeiImporter", "TextImporter", "ByScriptParagraphsEngine", "LinkedDocumentEngine", "ImageConvertEngine",
    "ChatTaggingEngine", "GeometryTaggingEngine", "RatiosHierarchyEngine", "RuleEngine", "ScriptDispatch",
    "SingleRegionLayoutEngine", "Strategy", "UnicodeParagraphsEngine", "WebpLosslessImageEngine",
]
