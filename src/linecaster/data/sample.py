"""The sample: the pages a run reads, chosen by a fixed rule from the IDs of its input before anything is read.

The rule (``RULE``, ``linecaster.sample/1``), with ``H(s)`` the first 8 bytes of ``sha256(s)`` (UTF-8) as an
unsigned big-endian integer:

1. the input's listing is its distinct ``(item_id, page_id)`` pairs (a page without item has the item id ``""``);
2. the items are ordered by ``(H(f"{seed}\\t{item_id}"), item_id)``, and only the first ``items`` (M) are kept;
3. within an item, the pages are ordered by ``(H(f"{seed}\\t{item_id}\\t{page_id}"), page_id)``, and only the first
   ``per_item`` (K) are kept (an item with fewer pages gives them all);
4. the pages, in the order (item rank, page rank), are cut after the first ``pages`` (N).

The ranks depend only on the IDs and the seed: an item added to the input does not move the others' pages, and a
sample of N is the first N pages of a sample of 2N. Reproduced without linecaster::

    import hashlib

    def h(*ids):
        return int.from_bytes(hashlib.sha256("\\t".join(map(str, ids)).encode()).digest()[:8], "big")

    def sample(pairs, seed=0, n=None, k=None, m=None):
        items = {}
        for i, p in dict.fromkeys(pairs): items.setdefault(i, []).append(p)
        order = sorted(items, key=lambda i: (h(seed, i), i))[:m]
        return [(i, p) for i in order for p in sorted(items[i], key=lambda p: (h(seed, i, p), p))[:k]][:n]

The first 16 hex digits of the SHA-256 sort as ``H`` does, so SQL can order by them.

Two optional parts of the rule, which leave every selection without them as it was:

* **splits** (``splits``, ``split``): named fractions of the items (``test: 0.2, train: 0.8``), an item in the split
  where ``H(f"split\\t{seed}\\t{item_id}") / 2**64`` falls among the fractions' running sums, in the order given;
  every page of an item is on the same side, an added item moves no other, and another seed gives other splits.
  ``split`` names the one a sample takes (``split_of`` says where any item is);
* **strata** (``stratify``): a value per page the caller supplies (a mapping of page ids, or a function of the item
  and page ids: the language a ground truth records, ``linecaster.scoring.truth.page_values``), and each value's
  pages, its stratum, sampled apart by steps 2 to 4: ``per_stratum`` pages of each stratum, or ``pages`` (N) shared in
  proportion to the strata's pages in the listing (largest remainders, ties by the stratum's value), or neither (the
  rule's ``items`` and ``per_item`` in each stratum). The strata's pages together, in the order of the hashes above.
  A page without a value is in the stratum ``""``. A stratified sample reads the whole listing.

Import-light: the standard library only.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import NamedTuple

#: the rule's id, recorded with every sample; a rule that selects differently gets a new number
RULE = "linecaster.sample/1"
#: the hashes, as the run record states them
HASH = ('items: H(f"{seed}\\t{item_id}"), pages: H(f"{seed}\\t{item_id}\\t{page_id}"); H(s) = the first 8 bytes of '
        "sha256(s.encode('utf-8')) as an unsigned big-endian integer; ties by id")
#: the hash that puts an item in a split, as the run record states it (only where a rule has splits)
SPLIT_HASH = ('splits: H(f"split\\t{seed}\\t{item_id}") / 2**64 among the fractions\' running sums, in their order')


def _h(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def _checked(value: str, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{what} {value!r} is not a string")
    if "\t" in value:
        raise ValueError(f"{what} {value!r} contains a tab, which separates the hashed ids")
    return value


def item_hash(seed: int, item_id: str) -> int:
    """``H(f"{seed}\\t{item_id}")``: the key that orders the items; a tab in the id is a ``ValueError``."""
    return _h(f"{seed}\t{_checked(item_id, 'item id')}")


def page_hash(seed: int, item_id: str, page_id: str) -> int:
    """``H(f"{seed}\\t{item_id}\\t{page_id}")``: the key that orders an item's pages; a tab in an id is a
    ``ValueError``."""
    return _h(f"{seed}\t{_checked(item_id, 'item id')}\t{_checked(page_id, 'page id')}")


def split_hash(seed: int, item_id: str) -> int:
    """``H(f"split\\t{seed}\\t{item_id}")``: the key that puts an item in a split; a tab in the id is a
    ``ValueError``."""
    return _h(f"split\t{seed}\t{_checked(item_id, 'item id')}")


def _splits(value) -> tuple[tuple[str, float], ...] | None:
    if value is None:
        return None
    pairs = list(value.items()) if isinstance(value, Mapping) else [tuple(x) for x in value]
    if not pairs:
        raise ValueError("splits: name at least one split")
    names = [n for n, _ in pairs]
    for name, fraction in pairs:
        if not isinstance(name, str) or not name or "\t" in name:
            raise ValueError(f"split name {name!r}: a non-empty string without tabs")
        if isinstance(fraction, bool) or not isinstance(fraction, int | float) or not 0 < fraction <= 1:
            raise ValueError(f"split {name}: its fraction must be above 0 and at most 1, not {fraction!r}")
    if len(set(names)) != len(names):
        raise ValueError(f"splits: a name twice in {names}")
    if abs(sum(f for _, f in pairs) - 1) > 1e-9:
        raise ValueError(f"splits: the fractions add up to {sum(f for _, f in pairs)}, not 1")
    return tuple((n, float(f)) for n, f in pairs)


def split_of(seed: int, item_id: str, splits: Iterable[tuple[str, float]] | Mapping[str, float]) -> str:
    """The split ``item_id`` is in: where ``split_hash(seed, item_id) / 2**64`` falls among the running sums of the
    fractions, in their order (module docstring)."""
    pairs = _splits(splits)
    u = split_hash(seed, item_id) / 2 ** 64
    total = 0.0
    for name, fraction in pairs:
        total += fraction
        if u < total:
            return name
    return pairs[-1][0]                                     # the sums' rounding: the last split


@dataclass(frozen=True)
class SampleRule:
    """What a sample takes: at most ``pages`` (N) pages in all, ``items`` (M) items, ``per_item`` (K) pages of each
    item, ranked with ``seed``. Each limit may be None (no limit), but at least one is given (or a ``split``, or
    ``per_stratum``).

    Optional (module docstring): ``splits``, named fractions of the items (a mapping or ``(name, fraction)`` pairs,
    in order), and ``split``, the one taken; ``stratify``, the name of the page value the caller supplies to
    ``select`` (``language``), with ``per_stratum`` pages of each stratum or ``pages`` shared in proportion. Left out
    of ``to_dict`` when unset, so a rule without them is written, and hashed, as before."""

    pages: int | None = None
    items: int | None = None
    per_item: int | None = None
    seed: int = 0
    stratify: str | None = None
    per_stratum: int | None = None
    splits: tuple[tuple[str, float], ...] | None = None
    split: str | None = None

    def __post_init__(self):
        for name in ("pages", "items", "per_item", "per_stratum"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
                raise ValueError(f"sample {name} must be a whole number of at least 1, not {value!r}")
        if self.pages is None and self.items is None and self.per_item is None and self.per_stratum is None \
                and self.split is None:
            raise ValueError("a sample needs pages, items, per_item, per_stratum or a split")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError(f"the sample seed must be a whole number, not {self.seed!r}")
        if self.stratify is not None and (not isinstance(self.stratify, str) or not self.stratify):
            raise ValueError(f"stratify names the page value strata are made of, not {self.stratify!r}")
        if self.per_stratum is not None and self.stratify is None:
            raise ValueError("per_stratum needs stratify")
        if self.per_stratum is not None and self.pages is not None:
            raise ValueError("a stratified sample takes per_stratum pages of each stratum or pages in all, not both")
        object.__setattr__(self, "splits", _splits(self.splits))
        if (self.split is None) != (self.splits is None):
            raise ValueError("a split is taken from splits: give both")
        if self.split is not None and self.split not in dict(self.splits):
            raise ValueError(f"split {self.split!r} is not one of {[n for n, _ in self.splits]}")

    def to_dict(self) -> dict:
        out = {"pages": self.pages, "items": self.items, "per_item": self.per_item, "seed": self.seed}
        if self.stratify is not None:
            out["stratify"] = self.stratify
        if self.per_stratum is not None:
            out["per_stratum"] = self.per_stratum
        if self.splits is not None:
            out["splits"] = dict(self.splits)
            out["split"] = self.split
        return out


class Selected(NamedTuple):
    """One page of a sample: its ``rank`` in the sample (1-based: a sample of N is ``rank <= N``), its item's rank
    among the items with pages and its own rank in the item (both 1-based), both hashes, and its item's page count
    in the listing."""

    rank: int
    item_id: str
    page_id: str
    item_rank: int
    page_rank: int
    item_hash: int
    page_hash: int
    item_pages: int


def select(items: Iterable[str], pages: Callable[[str], Iterable[str]], rule: SampleRule,
           strata: Mapping[str, str | None] | Callable[[str, str], str | None] | None = None) -> Iterator[Selected]:
    """The sample of ``rule``, in its order: the ``items`` (ids, duplicates once) ranked, then each item's pages
    (``pages(item_id)``, duplicates once) asked for in item order, only as far as the rule reaches, so a listing
    whose pages cost a request (a manifest) is read only that far. An item without pages is not in the listing:
    it takes no rank.

    A rule with a ``split`` takes the items of that split only; one that ``stratify``s needs ``strata``, each page's
    value (a mapping of page ids, or a function of the item and page ids), and reads every item's pages (module
    docstring)."""
    if rule.split is not None:
        chosen = [i for i in dict.fromkeys(items) if split_of(rule.seed, i, rule.splits) == rule.split]
    else:
        chosen = items
    if rule.stratify is None:
        yield from _select(chosen, pages, rule.seed, rule.pages, rule.items, rule.per_item)
        return
    if strata is None:
        raise ValueError(f"a sample stratified by {rule.stratify} needs each page's value (strata)")
    value = strata if callable(strata) else (lambda item, page: strata.get(page))
    listing = {i: list(dict.fromkeys(pages(i))) for i in dict.fromkeys(chosen)}
    by: dict[str, dict[str, list[str]]] = {}
    for item, ids in listing.items():
        for p in ids:
            v = value(item, p)
            by.setdefault("" if v is None else str(v), {}).setdefault(item, []).append(p)
    counts = {s: sum(len(ps) for ps in its.values()) for s, its in by.items()}
    shares = _shares(counts, rule.pages) if rule.pages is not None else {s: rule.per_stratum for s in by}
    taken = []
    for s in sorted(by):
        its = by[s]
        if shares[s] == 0:
            continue
        taken += [(x.item_hash, x.item_id, x.page_hash, x.page_id)
                  for x in _select(its, its.__getitem__, rule.seed, shares[s], rule.items, rule.per_item)]
    taken.sort()
    item_ranks = {i: r for r, (_, i) in enumerate(sorted((item_hash(rule.seed, i), i) for i, ps in listing.items()
                                                         if ps), 1)}
    page_ranks: dict[str, dict[str, int]] = {}
    for rank, (ih, item, ph, page) in enumerate(taken, 1):
        ids = listing[item]
        if item not in page_ranks:
            page_ranks[item] = {p: r for r, (_, p) in enumerate(sorted((page_hash(rule.seed, item, p), p)
                                                                         for p in ids), 1)}
        yield Selected(rank, item, page, item_ranks[item], page_ranks[item][page], ih, ph, len(ids))


def _shares(counts: dict[str, int], n: int) -> dict[str, int]:
    """``n`` pages shared among strata in proportion to their pages (``counts``): each its whole share, the pages
    left over to the largest remainders (ties by the stratum's value); all of them when ``n`` is not fewer."""
    total = sum(counts.values())
    if n >= total:
        return dict(counts)
    exact = {s: n * c / total for s, c in counts.items()}
    shares = {s: int(x) for s, x in exact.items()}
    left = n - sum(shares.values())
    for s in sorted(counts, key=lambda s: (-(exact[s] - shares[s]), s))[:left]:
        shares[s] += 1
    return shares


def _select(items: Iterable[str], pages: Callable[[str], Iterable[str]], seed: int, n: int | None, m: int | None,
            k: int | None) -> Iterator[Selected]:
    """Steps 2 to 4 of the rule (module docstring) with the limits ``n`` pages, ``m`` items, ``k`` pages per item."""
    ranked = sorted(((item_hash(seed, i), i) for i in dict.fromkeys(items)))
    rank = item_rank = 0
    for ih, item in ranked:
        if m is not None and item_rank >= m or n is not None and rank >= n:
            return
        ids = list(dict.fromkeys(pages(item)))
        if not ids:
            continue
        item_rank += 1
        order = sorted((page_hash(seed, item, p), p) for p in ids)
        for page_rank, (ph, page) in enumerate(order[:k], 1):
            if n is not None and rank >= n:
                return
            rank += 1
            yield Selected(rank, item, page, item_rank, page_rank, ih, ph, len(ids))


def group(pairs: Iterable[tuple[str | None, str]]) -> dict[str, list[str]]:
    """A listing's ``(item_id, page_id)`` pairs as item -> page ids, in the order they come (``None`` as ``""``)."""
    out: dict[str, list[str]] = {}
    for item, page in pairs:
        out.setdefault("" if item is None else item, []).append(page)
    return out


def listing_sha256(lines: Iterable[str]) -> str:
    """``sha256:<hex>`` of the distinct ``lines`` sorted (code point order), each followed by a newline: of a page
    listing as ``f"{item_id}\\t{page_id}"``, of an item listing as ``item_id``."""
    digest = hashlib.sha256()
    for line in sorted(set(lines)):
        digest.update(f"{line}\n".encode())
    return f"sha256:{digest.hexdigest()}"


def selection_sha256(selected: Iterable[Selected]) -> str:
    """``sha256:<hex>`` of the sample's ``f"{item_id}\\t{page_id}\\n"`` lines in its order."""
    digest = hashlib.sha256()
    for s in selected:
        digest.update(f"{s.item_id}\t{s.page_id}\n".encode())
    return f"sha256:{digest.hexdigest()}"


@dataclass
class Sample:
    """A sample as a reader computed it: the ``rule``, the ``selected`` pages in order, and what the listing held
    (``listing``: ``scope`` ``pages`` or ``items`` (the pages of a manifest are known once it is read), ``items``,
    ``pages``, ``duplicates`` (pairs listed more than once), ``sha256``)."""

    rule: SampleRule
    selected: list[Selected]
    listing: dict = field(default_factory=dict)

    def keys(self) -> set[tuple[str, str]]:
        """The selected ``(item_id, page_id)`` pairs."""
        return {(s.item_id, s.page_id) for s in self.selected}

    def record(self) -> dict:
        """The run record's ``sample`` section (``linecaster.runtime.record.SampleRecord``)."""
        extra = {"split_hash": SPLIT_HASH} if self.rule.splits is not None else {}
        return {"rule": RULE, "hash": HASH, **extra, **self.rule.to_dict(), "listing": dict(self.listing),
                "selected": {"items": len({s.item_id for s in self.selected}), "pages": len(self.selected),
                             "sha256": selection_sha256(self.selected)},
                "file": "sample.parquet"}


def sample_pairs(pairs: Iterable[tuple[str | None, str]], rule: SampleRule,
                 strata: Mapping[str, str | None] | Callable[[str, str], str | None] | None = None) -> Sample:
    """The sample of a listing given whole, as ``(item_id, page_id)`` pairs (``None`` items as ``""``); ``strata``
    each page's value, for a rule that ``stratify``s (``select``)."""
    listed = list(pairs)
    items = group(listed)
    distinct = {(i, p) for i, ps in items.items() for p in ps}
    selected = list(select(items, items.__getitem__, rule, strata))
    listing = {"scope": "pages", "items": len(items), "pages": len(distinct), "duplicates": len(listed) - len(distinct),
               "sha256": listing_sha256(f"{i}\t{p}" for i, p in distinct)}
    return Sample(rule, selected, listing)
