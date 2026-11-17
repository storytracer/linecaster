"""The word metrics' tokenizers on scripts with combining marks and without spaces; a benchmark names its tokenizer
and keeps its hash when it names the default; evidence compares the word metrics too."""
from __future__ import annotations

import pytest

from linecaster.data import Annotator, Source, Transcription
from linecaster.data.sample import listing_sha256
from linecaster.evaluation import WORDS_VERSION, role_words, score_page, tokens, words

IDS = ["library.test_item1_0001"]


@pytest.mark.parametrize("text,whole", [
    ("नमस्ते दुनिया", ["नमस्ते", "दुनिया"]),                # Devanagari: vowel signs and virama are marks
    ("كَتَبَ الوَلَدُ", ["كَتَبَ", "الوَلَدُ"]),                # Arabic with its vowel marks
    ("שָׁלוֹם עוֹלָם", ["שָׁלוֹם", "עוֹלָם"]),                # Hebrew with points
    ("สวัสดีครับ วันนี้", ["สวัสดีครับ", "วันนี้"]),          # Thai: vowels above and below are marks
    ("한국어 텍스트", ["한국어", "텍스트"]),
    ("The ship, x² a_b", ["The", "ship", "x²", "a_b"]),       # English as before: \w, the underscore
])
def test_whitespace_words_keep_their_marks(text, whole):
    assert tokens(text, "whitespace") == whole


def test_format_characters_stay_in_their_word_but_the_zero_width_space_separates():
    assert tokens("می\u200cخواهم", "whitespace") == ["می\u200cخواهم"]      # Persian: a zero-width non-joiner
    assert tokens("ᠪᠠᠢᠨ\u180eᠠ", "whitespace") == ["ᠪᠠᠢᠨ\u180eᠠ"]          # Mongolian: the vowel separator
    assert tokens("ไทย\u200bภาษา \u00ad", "whitespace") == ["ไทย", "ภาษา"] # a lone soft hyphen is no word


def test_whitespace_is_one_word_per_run_in_scripts_without_spaces():
    assert tokens("東京は晴れです", "whitespace") == ["東京は晴れです"]


def test_uax29_cuts_by_unicode_s_word_boundaries():
    assert tokens("東京は晴れです", "uax29") == ["東", "京", "は", "晴", "れ", "で", "す"]
    assert tokens("カタカナ と ひらがな", "uax29") == ["カタカナ", "と", "ひ", "ら", "が", "な"]
    assert tokens("The ship's log, 1887.", "uax29") == ["The", "ship's", "log", "1887"]
    assert tokens("नमस्ते दुनिया", "uax29") == ["नमस्ते", "दुनिया"]
    assert tokens("a�c ok", "uax29") == ["a�c", "ok"]       # an illegible character stays in its word


def test_characters_are_grapheme_clusters_with_a_letter_mark_or_digit():
    assert tokens("中文, 1!", "characters") == ["中", "文", "1"]
    assert tokens("हिन्दी", "characters") == ["हि", "न्दी"]


def test_an_unknown_tokenizer_is_refused():
    with pytest.raises(ValueError):
        tokens("x", "nowhere")


def test_words_leave_out_illegible_words_by_any_tokenizer():
    assert words("sh�p ship", tokenizer="uax29") == {"ship": 1}
    assert words("sh�p ship") == {"ship": 1}


def _page(lines, illegible=None) -> Transcription:
    t = Transcription(source=Source(image_width=1000, image_height=1000))
    a = t.add_annotator(Annotator(step="layout", name="test"))
    for k, (role, s) in enumerate(lines):
        t.add_region(a, f"r{k}", [0, 100 * k, 1000, 90], role=role)
        t.add_line(a, f"l{k}", region=f"r{k}", text=s)
    t.add_order(a, [r.id for r in t.regions], [ln.id for ln in t.lines])
    if illegible:
        t.classify(a, illegible, "status", "illegible")
    return t


def test_role_words_count_what_the_texts_count():
    t = _page([("header", "The ſhip"), ("paragraph", "sailed far")], illegible="l1[0:1]")
    assert role_words(t, lane="diplomatic") == {"header": {"The": 1, "ſhip": 1}, "paragraph": {"far": 1}}  # illegible
    assert role_words(t, lane="diplomatic", strategy="long-s")["header"] == {"The": 1, "ship": 1}


def test_score_page_names_its_tokenizer():
    t = _page([("paragraph", "東京は晴れです")])
    o = _page([("paragraph", "東京は晴れでず")])
    (row, _body) = score_page(t, o, tokenizer="uax29")["rows"]
    assert (row["words"], row["words_true"], row["words_both"]) == ("uax29", 7, 6)
    (row, _body) = score_page(t, o, tokenizer="whitespace")["rows"]
    assert (row["words"], row["words_true"], row["words_both"]) == ("whitespace", 1, 0)
    assert score_page(t, o)["rows"][0]["words"] == "uax29"                  # the default


def _bench(**fields):
    from linecaster.evaluation.benchmark import Benchmark

    return Benchmark.model_validate({"schema": "linecaster.benchmark/2", "id": "b",
                                     "dataset": {"repo": "x@1", "importer": "alto"},
                                     "pages": {"ids": IDS, "sha256": listing_sha256(IDS)}, **fields})


def test_a_benchmark_names_its_tokenizer_and_keeps_its_hash_with_the_default():
    assert _bench().words == "uax29" and _bench().sha256 == _bench(words="uax29").sha256
    # a benchmark/2 naming 0.10.5's default metrics keeps 0.10.5's hash (the default now adds element metrics)
    old = ["cer", "token_recall", "over_extraction"]
    assert _bench(metrics=old).sha256 == "sha256:0098ab3838d45cb503fe940ae30becdf0eacde58b447e1262d8d21a045b2f056"
    assert _bench().sha256 != _bench(metrics=old).sha256
    assert _bench(words="whitespace").sha256 != _bench().sha256
    with pytest.raises(ValueError):
        _bench(words="nowhere")


def test_an_output_strategy_that_changes_structure_is_refused():
    with pytest.raises(ValueError, match="structure"):
        _bench(output="divided-words")


def test_evidence_compares_the_word_metrics():
    from linecaster.evaluation.evidence_format import Evidence3

    def ev(words=None):
        named = {"id": "x", "sha256": "sha256:" + "1" * 64}
        scoring = {"policy": named, "output": named, "lanes": [named], "unit": "grapheme", "scorer": "linecaster x"}
        if words is not None:
            scoring["words"] = words
        return Evidence3.model_validate({"schema": "linecaster.evidence/3", "recipe": "r", "source": "own-run",
                                         "benchmark": {"ref": "b@1", "sha256": "sha256:" + "0" * 64},
                                         "scoring": scoring, "metrics": {}, "date": "2026-11-16"})

    now = {"tokenizer": "whitespace", "version": WORDS_VERSION}
    assert ev(now).comparable(ev(now))
    assert not ev(now).comparable(ev())                           # before 0.11: marks dropped (version 1)
    assert not ev(now).comparable(ev({"tokenizer": "uax29", "version": WORDS_VERSION}))
