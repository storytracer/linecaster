"""Text transforms on transcriptions: the named text variants (``variants``), Unicode normalization
(``unicode``), recomposition of lines into running text (``recomposition``) and the typographic hierarchy
(``typography``). Import-light: no datatrove, saturate or engines."""
from .unicode import FORMS, normalize_transcription
from .variants import VARIANTS

__all__ = ["FORMS", "VARIANTS", "normalize_transcription"]
