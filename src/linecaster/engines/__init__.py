"""linecaster's built-in engines: the rule-based steps (``image``, ``normalization``, ``typography``,
``recomposition``, ``composition``), pure Python and in-process only, registered in
``linecaster.catalog.registry.BUILTIN_ENGINES``. The protocol and the dispatch by script are in
``linecaster.engines.base``, the scripts in ``linecaster.engines.scripts``; the rules themselves stay in
``linecaster.text``, ``linecaster.images`` and ``linecaster.formats`` (the engines are thin). Import-light, like
the data model: no datatrove, saturate, blocks or runtime."""
from .base import RuleEngine, ScriptDispatch, Strategy
from .composition import DoclingCompositionEngine
from .image import WebpLosslessImageEngine
from .normalization import ByScriptNormalizationEngine, LatinHistoricNormalizationEngine
from .recomposition import ByScriptRecompositionEngine, UnicodeRecompositionEngine
from .typography import RatiosTypographyEngine

__all__ = [
    "ByScriptNormalizationEngine", "ByScriptRecompositionEngine", "DoclingCompositionEngine",
    "LatinHistoricNormalizationEngine", "RatiosTypographyEngine", "RuleEngine", "ScriptDispatch", "Strategy",
    "UnicodeRecompositionEngine", "WebpLosslessImageEngine",
]
