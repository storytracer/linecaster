"""The sample rule (``linecaster.data.sample``): the documented hash, the reference implementation, the prefix
property, ranks that depend only on the ids, the per-item cap, duplicates and tabs."""
import hashlib
import random

import pytest

from linecaster.data.sample import (Sample, SampleRule, item_hash, listing_sha256, page_hash, sample_pairs, select,
                                    selection_sha256)


def h(*ids):
    return int.from_bytes(hashlib.sha256("\t".join(map(str, ids)).encode()).digest()[:8], "big")


def reference(pairs, seed=0, n=None, k=None, m=None):
    """The reference implementation of the docs (``linecaster.data.sample``'s docstring), verbatim."""
    items = {}
    for i, p in dict.fromkeys(pairs): items.setdefault(i, []).append(p)
    order = sorted(items, key=lambda i: (h(seed, i), i))[:m]
    return [(i, p) for i in order for p in sorted(items[i], key=lambda p: (h(seed, i, p), p))[:k]][:n]


def listing(items=40, seed=1, prefix="item"):
    r = random.Random(seed)
    return [(f"{prefix}{i}", f"{prefix}{i}_{j:04d}") for i in range(items) for j in range(1, r.randint(1, 25))]


def ids(sample: Sample):
    return [(s.item_id, s.page_id) for s in sample.selected]


def test_the_hashes_are_the_documented_formula():
    digest = hashlib.sha256(b"7\tbook-1").digest()
    assert item_hash(7, "book-1") == int.from_bytes(digest[:8], "big")
    assert page_hash(7, "book-1", "p3") == int.from_bytes(hashlib.sha256(b"7\tbook-1\tp3").digest()[:8], "big")
    assert item_hash(0, "x") == 0xd07ba18c9302a5f1          # fixed: a change of the formula is a new rule
    assert format(item_hash(0, "x"), "016x") == hashlib.sha256(b"0\tx").hexdigest()[:16]


@pytest.mark.parametrize("rule", [dict(n=50, k=4), dict(k=3), dict(m=5), dict(n=17), dict(n=30, k=2, m=4),
                                  dict(n=10_000, k=8), dict(m=2, k=1)])
@pytest.mark.parametrize("seed", [0, 42])
def test_the_rule_is_the_reference_implementation(rule, seed):
    pairs = listing()
    got = sample_pairs(pairs, SampleRule(pages=rule.get("n"), items=rule.get("m"), per_item=rule.get("k"), seed=seed))
    assert ids(got) == reference(pairs, seed, rule.get("n"), rule.get("k"), rule.get("m"))


def test_a_sample_of_n_is_the_first_n_of_a_sample_of_2n():
    pairs = listing()
    for n in (1, 7, 40, 100):
        small = sample_pairs(pairs, SampleRule(pages=n, per_item=5)).selected
        large = sample_pairs(pairs, SampleRule(pages=2 * n, per_item=5)).selected
        assert large[:n] == small
    assert [s.rank for s in large] == list(range(1, len(large) + 1))


def test_adding_items_moves_no_other_items_pages():
    pairs = listing()
    more = pairs + listing(items=6, seed=9, prefix="added")
    before = ids(sample_pairs(pairs, SampleRule(per_item=3)))
    after = [x for x in ids(sample_pairs(more, SampleRule(per_item=3))) if not x[0].startswith("added")]
    assert after == before
    ranks = {s.item_id: s.page_rank for s in sample_pairs(pairs, SampleRule(per_item=3)).selected}
    assert {s.item_id: s.page_rank for s in sample_pairs(more, SampleRule(per_item=3)).selected
            if s.item_id in ranks} == ranks


def test_the_per_item_cap_holds_and_short_items_give_every_page():
    pairs = listing()
    sizes = {}
    for i, _ in pairs:
        sizes[i] = sizes.get(i, 0) + 1
    got = sample_pairs(pairs, SampleRule(per_item=4)).selected
    taken = {}
    for s in got:
        taken[s.item_id] = taken.get(s.item_id, 0) + 1
        assert s.item_pages == sizes[s.item_id]
    assert taken == {i: min(4, n) for i, n in sizes.items()}


def test_items_and_pages_are_ranked_in_order_with_ties_by_id():
    got = sample_pairs(listing(), SampleRule(per_item=3, seed=5)).selected
    keys = [(s.item_hash, s.item_id, s.page_hash, s.page_id) for s in got]
    assert keys == sorted(keys)
    assert [s.item_rank for s in got] == sorted(s.item_rank for s in got)


def test_pages_of_the_same_name_in_two_items_are_ranked_apart():
    """File names repeat across item folders (0001.png in each): the page hash includes the item."""
    pairs = [(f"b{i}", f"{j:04d}") for i in range(30) for j in range(1, 21)]
    firsts = {s.page_id for s in sample_pairs(pairs, SampleRule(per_item=1)).selected}
    assert len(firsts) > 5


def test_duplicates_count_once_and_are_counted():
    pairs = [("a", "a1"), ("a", "a2"), ("a", "a1"), ("b", "b1")]
    got = sample_pairs(pairs, SampleRule(per_item=5))
    assert sorted(ids(got)) == [("a", "a1"), ("a", "a2"), ("b", "b1")]
    assert got.listing["pages"] == 3 and got.listing["duplicates"] == 1 and got.listing["items"] == 2


def test_pages_without_item_are_one_item_named_empty():
    got = sample_pairs([(None, f"p{i}") for i in range(10)], SampleRule(pages=4))
    assert [s.item_id for s in got.selected] == [""] * 4
    assert ids(got) == reference([("", f"p{i}") for i in range(10)], n=4)


def test_the_listing_and_selection_fingerprints_are_documented_hashes():
    pairs = [("b", "b1"), ("a", "a1"), ("a", "a1")]
    got = sample_pairs(pairs, SampleRule(pages=5))
    assert got.listing["sha256"] == "sha256:" + hashlib.sha256(b"a\ta1\nb\tb1\n").hexdigest()
    lines = "".join(f"{s.item_id}\t{s.page_id}\n" for s in got.selected).encode()
    assert selection_sha256(got.selected) == "sha256:" + hashlib.sha256(lines).hexdigest()
    assert got.record()["selected"]["sha256"] == selection_sha256(got.selected)
    assert listing_sha256(["b", "a", "a"]) == "sha256:" + hashlib.sha256(b"a\nb\n").hexdigest()


def test_pages_are_asked_for_only_as_far_as_the_rule_reaches():
    items = {f"i{n}": [f"i{n}_{p}" for p in range(5)] for n in range(50)}
    asked = []

    def pages(item):
        asked.append(item)
        return items[item]

    got = list(select(items, pages, SampleRule(pages=6, per_item=2)))
    assert len(got) == 6 and len(asked) == 3


def test_an_item_without_pages_takes_no_rank():
    items = {"a": [], "b": ["b1"], "c": ["c1"]}
    got = list(select(items, items.__getitem__, SampleRule(items=2)))
    assert {s.item_id for s in got} == {"b", "c"} and sorted(s.item_rank for s in got) == [1, 2]


def test_a_tab_in_an_id_is_an_error():
    with pytest.raises(ValueError, match="tab"):
        sample_pairs([("a\tb", "p")], SampleRule(pages=1))
    with pytest.raises(ValueError, match="tab"):
        page_hash(0, "a", "p\t1")


@pytest.mark.parametrize("kwargs", [{}, {"pages": 0}, {"per_item": -1}, {"items": 1.5}, {"pages": 1, "seed": "x"}])
def test_a_rule_needs_a_positive_limit_and_a_whole_seed(kwargs):
    with pytest.raises(ValueError):
        SampleRule(**kwargs)
