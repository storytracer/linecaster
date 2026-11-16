"""Matching the ground truth's elements to the output's (``linecaster.scoring.matching``): deterministic groups for
splits, merges, swaps, duplicates, missed and extra elements, in any script."""
from __future__ import annotations

import os
import random
import subprocess
import sys

import pytest

pytest.importorskip("rapidfuzz")

from linecaster.scoring.counts import units  # noqa: E402
from linecaster.scoring.matching import (Settings, containment, encode, local_distance, match,  # noqa: E402
                                         similarity)


def _match(truth: list[str], output: list[str], **settings):
    t, o = encode([units(x, "grapheme") for x in truth], [units(x, "grapheme") for x in output])
    return [(g.kind, g.truth, g.output) for g in match(t, o, Settings(**settings))]


def test_the_local_distance_aligns_the_shorter_text_against_the_best_stretch():
    a, b = encode([list("ship")], [list("the shop sailed")])
    assert local_distance(a[0], b[0]) == 1
    assert containment(a[0], b[0]) == pytest.approx(0.75)
    assert local_distance(a[0][:0], b[0]) == 0 and local_distance(a[0], b[0][:0]) == 4
    assert similarity(a[0], a[0]) == 1.0


def test_an_illegible_unit_equals_nothing_not_even_another():
    t, o = encode([["a", "�", "c"]], [["a", "�", "c"]])
    assert local_distance(t[0], o[0]) == 1


def test_one_to_one_in_the_ground_truth_s_order_whatever_the_output_s():
    truth = ["The first paragraph of the page", "A second paragraph follows here", "and a third one closes it"]
    assert _match(truth, truth[::-1]) == [("one", (0,), (2,)), ("one", (1,), (1,)), ("one", (2,), (0,))]


def test_a_split_a_merge_missed_and_extra_elements():
    truth = ["The whole paragraph that the model cut in two halves", "a heading", "Notes at the foot"]
    output = ["The whole paragraph that", "the model cut in two halves", "a heading Notes at the foot",
              "something nobody wrote"]
    groups = _match(truth, output)
    assert groups[0] == ("split", (0,), (0, 1))
    assert groups[1] == ("merge", (1, 2), (2,))
    assert groups[2] == ("extra", (), (3,))
    assert _match(["only in the ground truth"], []) == [("missed", (0,), ())]
    assert _match([], ["only in the output"]) == [("extra", (), (0,))]


def test_a_duplicated_output_element_finds_its_home_once_each():
    truth = ["Chapter one begins on this page"]
    groups = _match(truth, ["Chapter one begins on this page", "Chapter one begins on this page"])
    assert groups == [("split", (0,), (0, 1))]


def test_short_elements_need_similarity_not_containment():
    assert _match(["12"], ["12 and the whole text of the page"]) == [("missed", (0,), ()), ("extra", (), (0,))]
    assert _match(["12"], ["12"]) == [("one", (0,), (0,))]


@pytest.mark.parametrize("truth, output", [
    (["東京は晴れです。", "明日は雨が降るでしょう。"], ["明日は雨が降るでしょう。", "東京は晴れです。"]),
    (["यह पहला वाक्य है", "और यह दूसरा वाक्य है"], ["और यह दूसरा वाक्य है", "यह पहला वाक्य है"]),
    (["هذه هي الجملة الأولى", "وهذه هي الجملة الثانية"], ["وهذه هي الجملة الثانية", "هذه هي الجملة الأولى"]),
])
def test_scripts_without_spaces_with_marks_and_right_to_left_match_by_grapheme(truth, output):
    assert _match(truth, output) == [("one", (0,), (1,)), ("one", (1,), (0,))]


def test_past_the_cell_cap_a_page_is_one_group():
    assert _match(["a long paragraph", "another"], ["a long paragraph", "another"], max_cells=1) == \
        [("page", (0, 1), (0, 1))]


def test_matching_does_not_depend_on_the_order_of_candidates_or_the_hash_seed():
    rnd = random.Random(3)
    truth = [" ".join(rnd.choice(["ship", "sail", "port", "wind", "sea", "harbor"]) for _ in range(8))
             for _ in range(40)]
    output = [x[:len(x) // 2] for x in truth] + [x[len(x) // 2:] for x in truth]
    first = _match(truth, output)
    assert first == _match(truth, output)
    code = ("from tests.scoring.test_matching import _match; import random; rnd = random.Random(3); "
            "truth = [' '.join(rnd.choice(['ship','sail','port','wind','sea','harbor']) for _ in range(8)) "
            "for _ in range(40)]; output = [x[:len(x)//2] for x in truth] + [x[len(x)//2:] for x in truth]; "
            "print(_match(truth, output))")
    runs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                           env={**os.environ, "PYTHONHASHSEED": seed}).stdout for seed in ("1", "2")}
    assert runs == {f"{first}\n"}
