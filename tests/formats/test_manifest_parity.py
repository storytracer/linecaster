"""Temporary: linecaster's manifest parser against pybookget's on every manifest fixture (and variants of them that
break them in many ways): the same pages, ids, sequence, image URLs, OCR links and metadata, or the same kind of
error. Reverted once pybookget is gone."""
import copy
import json

import pytest

pybookget = pytest.importorskip("pybookget.formats.manifest")
from pybookget.config import Config  # noqa: E402

from linecaster.formats import manifests as ours  # noqa: E402

import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fx = _load("formats/test_manifest_formats.py", "_parity_fx")
rx = _load("blocks/readers/test_manifests.py", "_parity_rx")


def outcome(read, *args, **kwargs):
    try:
        return "ok", read(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - the same kind of error either way
        return type(e).__name__, None


def as_tuple(item):
    if item is None:
        return None
    pages = [(p.index, p.id, p.label, p.url, p.fallback_url, p.ocr_url, p.ocr_format) for p in item.pages]
    return (item.format, item.id, item.label, item.rights, item.required_statement, item.identifiers, item.metadata,
            pages)


def compare(data, fmt=None, **options):
    config = Config(trust_env=False, **options)
    theirs_kind, theirs = outcome(pybookget.read_manifest, copy.deepcopy(data), config, format=fmt)
    ours_kind, mine = outcome(ours.read_manifest, copy.deepcopy(data), fmt, iiif_format=config.iiif_format,
                              iiif_quality=config.iiif_quality, image_groups=config.mets_image_groups,
                              ocr_groups=config.mets_ocr_groups)
    assert (ours_kind, as_tuple(mine)) == (theirs_kind, as_tuple(theirs))
    d1, d2 = outcome(pybookget.detect_format, copy.deepcopy(data)), outcome(ours.detect_format, copy.deepcopy(data))
    assert d1 == d2
    if d1[1] == "iiif-collection":
        c1 = outcome(pybookget.read_collection, copy.deepcopy(data))
        c2 = outcome(ours.read_collection, copy.deepcopy(data))
        assert c1[0] == c2[0]
        if c1[1] is not None:
            assert [(m.id, m.label, m.kind) for m in c1[1]] == [(m.id, m.label, m.kind) for m in c2[1]]


BASE = "http://library.test:8000"


def reader_fixtures():
    out = {
        "reader_mets": rx.mets(BASE, ["f1", "f2", "f3"]),
        "reader_mets_default": rx.mets(BASE, ["f1"], groups=("DEFAULT",)),
        "reader_mets_local": rx.mets(BASE, ["f1", "f2"], href=lambda g, n: f"{g.lower()}/{n}.png"),
        "reader_v2": rx.v2(BASE, "it", [("a", True), ("b", False)]),
        "reader_v3": rx.v3(BASE, "it", ["a", "b"]),
        "reader_collection": rx.collection(BASE, "flora", [("Manifest", f"{BASE}/a/manifest"),
                                                           ("Collection", f"{BASE}/b/manifest")]),
    }
    out["reader_oai"] = rx.oai(out["reader_mets"])
    return out


FIXTURES = {**fx.FIXTURES, **reader_fixtures(), "collection_v2": fx.COLLECTION_V2, "collection_v3": fx.COLLECTION_V3}


def json_variants(data: dict):
    """The manifest with one value at a time replaced by something odd."""
    yield data
    paths = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                paths.append((*path, k))
                walk(v, (*path, k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                paths.append((*path, i))
                walk(v, (*path, i))
    walk(data, ())
    for path in paths:
        for odd in (None, "", "x", [], {}, 1, ["http://iiif.io/api/image/3/x"], {"@value": "v"}):
            d = copy.deepcopy(data)
            node = d
            for p in path[:-1]:
                node = node[p]
            node[path[-1]] = odd
            yield d
        d = copy.deepcopy(data)
        node = d
        for p in path[:-1]:
            node = node[p]
        del node[path[-1]]
        yield d


def xml_variants(text: str):
    yield text
    yield text.encode()
    for a, b in (('TYPE="page"', 'TYPE="other"'), ('ORDER="1"', 'ORDER="x"'), ('USE="MAX"', 'USE="max"'),
                 ('MIMETYPE="image/png"', 'MIMETYPE=""'), ('MIMETYPE="image/jpeg"', 'MIMETYPE="application/pdf"'),
                 ('LOCTYPE="URL"', 'LOCTYPE="OTHER"'), ("<mods:mods>", "<mods:mods><mods:titleInfo/>"),
                 ('TYPE="LOGICAL"', 'TYPE="PHYSICAL"'), ('TYPE="PHYSICAL"', 'TYPE="LOGICAL"'),
                 ("keyDate=\"yes\"", "point=\"start\""), ("</mets:mets>", "</mets:mets>junk"),
                 ('<mets:fileSec>', '<!-- c --><mets:fileSec>'), ("mets:FLocat", "mets:Flocat"),
                 ('DMDID="dmd1"', 'DMDID="missing"'), ('xlink:href', 'href')):
        if a in text:
            yield text.replace(a, b)
            yield text.replace(a, b, 1)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_parity(name):
    data = FIXTURES[name]
    variants = json_variants(data) if isinstance(data, dict) else xml_variants(data)
    for variant in variants:
        compare(variant)
        if isinstance(variant, dict):
            compare(json.dumps(variant))
        for fmt in ("iiif", "mets"):
            compare(variant, fmt)
        compare(variant, iiif_format="png", iiif_quality="gray", mets_image_groups=("DEFAULT", "MAX"),
                mets_ocr_groups=("OCR",))
