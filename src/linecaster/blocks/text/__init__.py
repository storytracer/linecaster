"""Text: the as-written layer in one Unicode normalization form, and its normalized texts."""
from .normalizer import CharacterNormalizer
from .unicode import UnicodeNormalizer

__all__ = ["CharacterNormalizer", "UnicodeNormalizer"]
