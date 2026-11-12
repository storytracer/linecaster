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

The first 16 hex digits of the SHA-256 sort as ``H`` does, so SQL can order by them. Import-light: the standard
library only.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import NamedTuple

#: the rule's id, recorded with every sample; a rule that selects differently gets a new number
RULE = "linecaster.sample/1"
#: the hashes, as the run record states them
HASH = ('items: H(f"{seed}\\t{item_id}"), pages: H(f"{seed}\\t{item_id}\\t{page_id}"); H(s) = the first 8 bytes of '
        "sha256(s.encode('utf-8')) as an unsigned big-endian integer; ties by id")


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


@dataclass(frozen=True)
class SampleRule:
    """What a sample takes: at most ``pages`` (N) pages in all, ``items`` (M) items, ``per_item`` (K) pages of each
    item, ranked with ``seed``. Each limit may be None (no limit), but at least one is given."""

    pages: int | None = None
    items: int | None = None
    per_item: int | None = None
    seed: int = 0

    def __post_init__(self):
        for name in ("pages", "items", "per_item"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
                raise ValueError(f"sample {name} must be a whole number of at least 1, not {value!r}")
        if self.pages is None and self.items is None and self.per_item is None:
            raise ValueError("a sample needs pages, items or per_item")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError(f"the sample seed must be a whole number, not {self.seed!r}")

    def to_dict(self) -> dict:
        return {"pages": self.pages, "items": self.items, "per_item": self.per_item, "seed": self.seed}


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


def select(items: Iterable[str], pages: Callable[[str], Iterable[str]], rule: SampleRule) -> Iterator[Selected]:
    """The sample of ``rule``, in its order: the ``items`` (ids, duplicates once) ranked, then each item's pages
    (``pages(item_id)``, duplicates once) asked for in item order, only as far as the rule reaches, so a listing
    whose pages cost a request (a manifest) is read only that far. An item without pages is not in the listing:
    it takes no rank."""
    seed = rule.seed
    ranked = sorted(((item_hash(seed, i), i) for i in dict.fromkeys(items)))
    rank = item_rank = 0
    for ih, item in ranked:
        if rule.items is not None and item_rank >= rule.items or rule.pages is not None and rank >= rule.pages:
            return
        ids = list(dict.fromkeys(pages(item)))
        if not ids:
            continue
        item_rank += 1
        order = sorted((page_hash(seed, item, p), p) for p in ids)
        for page_rank, (ph, page) in enumerate(order[:rule.per_item], 1):
            if rule.pages is not None and rank >= rule.pages:
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
        return {"rule": RULE, "hash": HASH, **self.rule.to_dict(), "listing": dict(self.listing),
                "selected": {"items": len({s.item_id for s in self.selected}), "pages": len(self.selected),
                             "sha256": selection_sha256(self.selected)},
                "file": "sample.parquet"}


def sample_pairs(pairs: Iterable[tuple[str | None, str]], rule: SampleRule) -> Sample:
    """The sample of a listing given whole, as ``(item_id, page_id)`` pairs (``None`` items as ``""``)."""
    listed = list(pairs)
    items = group(listed)
    distinct = {(i, p) for i, ps in items.items() for p in ps}
    selected = list(select(items, items.__getitem__, rule))
    listing = {"scope": "pages", "items": len(items), "pages": len(distinct), "duplicates": len(listed) - len(distinct),
               "sha256": listing_sha256(f"{i}\t{p}" for i, p in distinct)}
    return Sample(rule, selected, listing)
