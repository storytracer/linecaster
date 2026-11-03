"""The catalogue (specs/catalog.md): YAML 1.2 booleans, documents, release, immutability, old editions, and
the installed catalogue being consistent."""
import datetime as dt

import pytest

from linecaster.catalog import yamlio
from linecaster.catalog.registry import Catalog, catalogue_dirs, sha256_file


def test_yaml_12_booleans():
    assert yamlio.load("lang: [NO, yes, on]\nok: true\nv: '1.0'") == {"lang": ["NO", "yes", "on"], "ok": True,
                                                                       "v": "1.0"}
    assert yamlio.load(yamlio.dump({"x": "no", "y": "multi\nline"})) == {"x": "no", "y": "multi\nline"}


def make(root, temperature=0.0, edition=1, prose="Why these settings."):
    up = root / "models" / "m" / "upstream" / "abc"
    up.mkdir(parents=True, exist_ok=True)
    (up / "README.md").write_text("---\nlicense: mit\n---\n# upstream card\n")
    yamlio.write_front_matter(root / "models" / "m" / "model.md", {
        "schema": "linecaster.model/1", "id": "m", "source": {"kind": "hf", "ref": "org/m"},
        "pins": [{"revision": "abc", "pinned": dt.date(2026, 11, 3), "files": {"w.safetensors": "sha256:" + "0" * 64},
                  "card": "upstream/abc/README.md", "card_sha256": sha256_file(up / "README.md")}],
        "license": "MIT"}, "Ours.\n")
    yamlio.write_front_matter(root / "presets" / "p.md", {
        "schema": "linecaster.preset/1", "id": "p", "edition": edition, "step": "page",
        "model": {"id": "m", "revision": "abc"}, "engine": {"kind": "chat/1", "options": {"adapter": "x"}},
        "settings": {"sampling": {"temperature": temperature}}, "support": "core"}, prose)


def test_release_freezes_an_edition(tmp_path):
    make(tmp_path)
    c = Catalog([tmp_path])
    assert c.verify() == []
    entry = c.release("p", commit="deadbee", today=dt.date(2026, 11, 3))
    assert entry.resolved["model"] == {"id": "m", "revision": "abc", "files": {"w.safetensors": "sha256:" + "0" * 64}}
    assert (tmp_path / "catalog.lock").read_text().startswith("# generated")

    make(tmp_path, prose="Better prose.")                  # prose is not functional: still the same edition
    assert Catalog([tmp_path]).verify() == []

    make(tmp_path, temperature=0.2)                        # a functional change without a new edition
    assert any("give it edition 2" in p for p in Catalog([tmp_path]).verify())

    make(tmp_path, temperature=0.2, edition=2)             # as edition 2: fine, and edition 1 stays resolvable
    c = Catalog([tmp_path])
    assert c.verify() == []
    assert c.resolve("p@1").content["settings"] == {"sampling": {"temperature": 0.0}}
    assert c.resolve("p").edition == 2 and not c.resolve("p").released
    c.release("p")
    assert set(Catalog([tmp_path]).dirs[0].lock.presets) == {"p@1", "p@2"}
    make(tmp_path, temperature=0.5, edition=2)             # released edition 2 cannot be released again changed
    with pytest.raises(ValueError, match="edition 3"):
        Catalog([tmp_path]).release("p")


def test_verify_catches_edited_cards_and_dangling_references(tmp_path):
    make(tmp_path)
    (tmp_path / "models" / "m" / "upstream" / "abc" / "README.md").write_text("edited")
    yamlio.write_front_matter(tmp_path / "presets" / "q.md", {
        "schema": "linecaster.preset/1", "id": "q", "edition": 1, "step": "recognition",
        "model": {"id": "m", "revision": "nope"}, "engine": {"kind": "k/1"}})
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "e.yaml").write_text(yamlio.dump({
        "schema": "linecaster.evidence/1", "preset": "p@7", "source": "own-run", "dataset": "d@r",
        "metrics": {"cer_reading": 0.03}, "date": dt.date(2026, 11, 3)}))
    problems = Catalog([tmp_path]).verify()
    assert any("differs from its pinned sha256" in p for p in problems)
    assert any("preset q" in p and "no pin 'nope'" in p for p in problems)
    assert any("evidence e.yaml" in p for p in problems)


def test_documents_are_strict(tmp_path):
    make(tmp_path)
    meta, body = yamlio.read_front_matter(tmp_path / "presets" / "p.md")
    meta["temprature"] = 0.1
    yamlio.write_front_matter(tmp_path / "presets" / "p.md", meta, body)
    with pytest.raises(ValueError, match="temprature"):
        Catalog([tmp_path])


def test_installed_catalogue_is_consistent():
    c = Catalog(catalogue_dirs())
    assert c.verify() == []


def test_docs_from_the_catalogue(tmp_path):
    from linecaster.catalog import docs

    root = tmp_path / "cat"
    make(root)
    (root / "evidence").mkdir()
    (root / "evidence" / "e.yaml").write_text(yamlio.dump({
        "schema": "linecaster.evidence/1", "preset": "p@1", "source": "own-run", "dataset": "d@r",
        "metrics": {"cer_reading": 0.0312}, "date": dt.date(2026, 11, 3)}))
    readme = tmp_path / "README.md"
    readme.write_text("intro\n<!-- catalog:start -->\nold\n<!-- catalog:end -->\noutro\n")
    docs.write(Catalog([root]), tmp_path / "docs", readme=readme)
    page = (tmp_path / "docs" / "p.md").read_text()
    assert "Why these settings." in page and "| 2026-11-03 | Linecaster run | d@r | cer_reading 0.0312 |" in page
    assert "upstream/abc/README.md" in page
    assert "| [p](p.md) | MIT | 0.0312 |" in (tmp_path / "docs" / "README.md").read_text()
    text = readme.read_text()
    assert "old" not in text and "[`p`](docs/p.md) ✅" in text and text.endswith("outro\n")


def test_repository_catalogues_are_consistent():
    """Every catalogue in the checkout, the engines' too, read as data (no engine installed)."""
    from pathlib import Path

    from linecaster.catalog.registry import CORE

    root = Path(__file__).resolve().parents[1]
    dirs = [CORE, *sorted(root.glob("engines/*/src/*/catalog"))]
    c = Catalog(dirs)
    assert c.verify() == []
    assert len(c.presets) >= 18 and all(c.resolve(f"{pid}@{p.edition}").released for pid, (_, p) in c.presets.items())


def test_unknown_engine_kinds_are_reported(tmp_path):
    make(tmp_path)
    meta, body = yamlio.read_front_matter(tmp_path / "presets" / "p.md")
    meta["engine"]["kind"] = "chat/9"
    yamlio.write_front_matter(tmp_path / "presets" / "p.md", meta, body)
    assert any("'chat/9' is not registered" in p for p in Catalog([tmp_path]).verify())
