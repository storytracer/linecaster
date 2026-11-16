"""Stratified samples and item-level splits (``linecaster.data.sample``): a rule without them selects and is written
exactly as before; splits keep an item's pages together, are deterministic and depend on the seed; each stratum gets
its share, by the same hashes."""
import hashlib
import json
import random
from collections import Counter

import pytest

from linecaster.data.sample import (
    Sample,
    SampleRule,
    sample_pairs,
    select,
    selection_sha256,
    split_hash,
    split_of,
)


def listing(items=60, seed=3, prefix="item"):
    r = random.Random(seed)
    return [(f"{prefix}{i}", f"{prefix}{i}_{j:04d}") for i in range(items) for j in range(1, r.randint(2, 15))]


def ids(sample: Sample):
    return [(s.item_id, s.page_id) for s in sample.selected]


def language(item, page):
    """A page value: every third item is in German, a few pages of the others in Hebrew, the rest English."""
    n = int(item.removeprefix("item"))
    return "de" if n % 3 == 0 else "he" if page.endswith("1") else "en"


# ------------------------------------------------------------------------------------- unchanged without them
def test_a_rule_without_strata_or_splits_is_written_and_selects_as_before():
    rule = SampleRule(pages=40, per_item=3, seed=7)
    assert rule.to_dict() == {"pages": 40, "items": None, "per_item": 3, "seed": 7}
    got = sample_pairs(listing(), rule)
    # fixed: the selection of this listing and rule before strata and splits existed
    assert selection_sha256(got.selected) == FIXED_SELECTION
    record = got.record()
    assert set(record) == {"rule", "hash", "pages", "items", "per_item", "seed", "listing", "selected", "file"}
    assert SampleRule(**{k: v for k, v in rule.to_dict().items()}) == rule


#: ``selection_sha256`` of ``SampleRule(pages=40, per_item=3, seed=7)`` on ``listing()``, as the rule selected before
#: strata and splits existed (the module docstring's reference implementation gives the same)
FIXED_SELECTION = "sha256:ee5f88bbb5cc30b8135cc05188af9d7a42a859754f762bd3e88bdc949a09223c"


def test_strata_given_to_a_rule_that_does_not_stratify_change_nothing():
    rule = SampleRule(pages=25, per_item=2)
    assert ids(sample_pairs(listing(), rule, strata=language)) == ids(sample_pairs(listing(), rule))


# ------------------------------------------------------------------------------------------------- splits
def test_splits_keep_an_item_s_pages_together_and_follow_the_fractions():
    pairs = listing(items=400)
    splits = {"test": 0.2, "train": 0.8}
    test = sample_pairs(pairs, SampleRule(seed=1, splits=splits, split="test"))
    train = sample_pairs(pairs, SampleRule(seed=1, splits=splits, split="train"))
    test_items = {s.item_id for s in test.selected}
    train_items = {s.item_id for s in train.selected}
    assert not test_items & train_items
    assert test_items | train_items == {i for i, _ in pairs}
    assert len(test.selected) + len(train.selected) == len(set(pairs))
    assert 0.12 < len(test_items) / 400 < 0.28
    assert all(split_of(1, i, splits) == "test" for i in test_items)


def test_a_split_is_deterministic_seeded_and_an_added_item_moves_no_other():
    splits = [("a", 0.5), ("b", 0.5)]
    items = [f"item{i}" for i in range(200)]
    first = {i: split_of(0, i, splits) for i in items}
    assert first == {i: split_of(0, i, splits) for i in reversed(items)}
    assert first != {i: split_of(1, i, splits) for i in items}
    assert split_hash(0, "x") == int.from_bytes(hashlib.sha256(b"split\t0\tx").digest()[:8], "big")
    pairs = [(i, f"{i}_1") for i in items]
    before = ids(sample_pairs(pairs, SampleRule(splits=splits, split="a")))
    more = pairs + [(f"added{i}", f"added{i}_1") for i in range(30)]
    after = [x for x in ids(sample_pairs(more, SampleRule(splits=splits, split="a"))) if not x[0].startswith("added")]
    assert after == before


def test_a_split_sample_takes_the_rule_s_limits_within_the_split():
    pairs = listing(items=100)
    rule = SampleRule(pages=10, per_item=1, seed=2, splits={"dev": 0.5, "test": 0.5}, split="dev")
    got = sample_pairs(pairs, rule)
    assert len(got.selected) == 10 and len({s.item_id for s in got.selected}) == 10
    assert {split_of(2, s.item_id, rule.splits) for s in got.selected} == {"dev"}
    assert got.record()["splits"] == {"dev": 0.5, "test": 0.5} and got.record()["split"] == "dev"
    assert "split_hash" in got.record()
    assert json.loads(json.dumps(rule.to_dict())) == {"pages": 10, "items": None, "per_item": 1, "seed": 2,
                                                      "splits": {"dev": 0.5, "test": 0.5}, "split": "dev"}
    assert SampleRule(**rule.to_dict()) == rule


@pytest.mark.parametrize("bad", [dict(splits={"a": 0.5}, split="a"), dict(splits={"a": 1.0}),
                                 dict(split="a", pages=1), dict(splits={"a": 0.5, "b": 0.5}, split="c"),
                                 dict(splits={"": 1.0}, split=""), dict(splits=[("a", 0.5), ("a", 0.5)], split="a"),
                                 dict(per_stratum=2), dict(stratify="language", per_stratum=2, pages=4)])
def test_ill_formed_splits_and_strata_are_errors(bad):
    with pytest.raises(ValueError):
        SampleRule(**bad)


# -------------------------------------------------------------------------------------------------- strata
def test_each_stratum_gets_per_stratum_pages():
    pairs = listing()
    got = sample_pairs(pairs, SampleRule(stratify="language", per_stratum=5, per_item=2, seed=4), strata=language)
    assert Counter(language(i, p) for i, p in ids(got)) == {"de": 5, "en": 5, "he": 5}
    assert [s.rank for s in got.selected] == list(range(1, 16))
    keys = [(s.item_hash, s.item_id, s.page_hash, s.page_id) for s in got.selected]
    assert keys == sorted(keys)                                     # the strata together, in the hashes' order
    # within a stratum: the rule as it is, on the stratum's pages alone
    de = [(i, p) for i, p in pairs if language(i, p) == "de"]
    assert [x for x in ids(got) if language(*x) == "de"] == ids(sample_pairs(de, SampleRule(pages=5, per_item=2,
                                                                                            seed=4)))


def test_pages_are_shared_in_proportion_to_the_strata():
    pairs = listing()
    counts = Counter(language(i, p) for i, p in pairs)
    got = sample_pairs(pairs, SampleRule(stratify="language", pages=30), strata=language)
    taken = Counter(language(i, p) for i, p in ids(got))
    assert sum(taken.values()) == 30
    for s, c in counts.items():
        assert abs(taken[s] - 30 * c / sum(counts.values())) < 1
    again = sample_pairs(list(reversed(pairs)), SampleRule(stratify="language", pages=30), strata=language)
    assert ids(again) == ids(got)


def test_a_mapping_of_page_ids_and_pages_without_a_value():
    pairs = [("a", "a1"), ("a", "a2"), ("b", "b1"), ("c", "c1"), ("c", "c2")]
    got = sample_pairs(pairs, SampleRule(stratify="script", per_stratum=1), strata={"a1": "Latn", "b1": "Hebr"})
    assert sorted(p for _, p in ids(got)) == sorted(["a1", "b1", next(p for _, p in ids(got) if p not in ("a1", "b1"))])
    assert len(got.selected) == 3                                   # Latn, Hebr and the pages without one ("")
    with pytest.raises(ValueError, match="strata"):
        list(select({"a": ["a1"]}, {"a": ["a1"]}.__getitem__, SampleRule(stratify="script", per_stratum=1)))


def test_strata_and_a_split_together():
    pairs = listing(items=120)
    rule = SampleRule(stratify="language", per_stratum=3, seed=9, splits={"test": 0.3, "train": 0.7}, split="test")
    got = sample_pairs(pairs, rule, strata=language)
    assert {split_of(9, s.item_id, rule.splits) for s in got.selected} == {"test"}
    assert Counter(language(*x) for x in ids(got)) == {"de": 3, "en": 3, "he": 3}
