"""Words for the word metrics (recall, over-extraction, role words): a text's tokens by a tokenizer a benchmark names.

* ``whitespace`` (the default): runs between whitespace, everything but letters, combining marks, digits, the
  underscore and U+FFFD a word boundary: a word keeps its combining marks (Devanagari vowel signs, Arabic vowel marks,
  Hebrew points, Thai vowels), a text without spaces (Chinese, Japanese, Thai) is one word per run.
* ``uax29``: Unicode's word boundaries (UAX #29, ``uniseg``), tokens with a letter, mark or digit: Chinese ideographs,
  Hiragana and Thai one token per character (UAX #29 leaves those scripts to a dictionary), Katakana runs whole, the
  other scripts by their own boundaries; U+FFFD counts as a letter, so an illegible character stays in its word.
* ``characters``: grapheme clusters with a letter, mark or digit, for scripts whose words mean little to a count.

A token with an illegible character (U+FFFD) is left out by the metrics: no output can be required to have it.
"""
from __future__ import annotations

import unicodedata
from typing import Literal

import regex

REPLACEMENT = "�"
#: the tokenizers a benchmark may name
WORDS = ("whitespace", "uax29", "characters")
#: the version of the word metrics' rules, in evidence: 2 since combining marks stay in their words
WORDS_VERSION = 2

_WORDLIKE = regex.compile(r"[\p{L}\p{M}\p{N}�]")


def _in_word(c: str) -> bool:
    """Python's ``\\w`` (``str.isalnum`` and the underscore), whitespace, U+FFFD, and a combining mark."""
    return c.isalnum() or c == "_" or c.isspace() or c == REPLACEMENT or unicodedata.category(c)[0] == "M"


def _uax29_property(c: str):
    from uniseg.wordbreak import WordBreak, word_break

    return WordBreak.ALETTER if c == REPLACEMENT else word_break(c)


def tokens(s: str, words: Literal["whitespace", "uax29", "characters"] = "whitespace") -> list[str]:
    """The tokens of ``s`` by the tokenizer ``words`` (``WORDS``), in order."""
    if words == "whitespace":
        return "".join(c if _in_word(c) else " " for c in s).split()
    if words == "uax29":
        from uniseg.wordbreak import words as uax29_words

        return [w for w in uax29_words(s, property=_uax29_property) if _WORDLIKE.search(w)]
    if words == "characters":
        from uniseg.graphemecluster import grapheme_clusters

        return [g for g in grapheme_clusters(s) if _WORDLIKE.search(g)]
    raise ValueError(f"unknown tokenizer {words!r}; known: {', '.join(WORDS)}")
