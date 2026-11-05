"""The catalogue (docs/reference/catalog.md): YAML 1.2 booleans, documents, release, immutability, old editions, and
the installed catalogue being consistent."""
import datetime as dt

import pytest

from linecaster.catalog import yamlio
from linecaster.catalog.registry import Catalog, sha256_file, write_entry


def test_yaml_12_booleans():
    assert yamlio.load("lang: [NO, yes, on]\nok: true\nv: '1.0'") == {"lang": ["NO", "yes", "on"], "ok": True,
                                                                       "v": "1.0"}
    assert yamlio.load(yamlio.dump({"x": "no", "y": "multi\nline"})) == {"x": "no", "y": "multi\nline"}


def test_yaml_duplicate_keys_are_errors():
    from ruamel.yaml.constructor import DuplicateKeyError

    with pytest.raises(DuplicateKeyError):
        yamlio.load("a: 1\na: 2\n")


def test_yaml_written_back_keeps_comments():
    doc = yamlio.load_rt("# head\nb: 1  # why\nc:\n  x: 1\n")
    yamlio.update(doc, {"a": 0, "b": 1, "c": {"x": 2}})
    text = yamlio.dump_rt(doc)
    assert text.startswith("# head\n") and "b: 1  # why" in text and yamlio.load(text) == {"a": 0, "b": 1, "c": {"x": 2}}
    assert list(yamlio.load(text)) == ["a", "b", "c"]          # a new key among sorted keys goes where it sorts


def make(root, temperature=0.0, edition=1, prose="Why these settings."):
    up = root / "models" / "m" / "upstream" / "abc"
    up.mkdir(parents=True, exist_ok=True)
    (up / "README.md").write_text("---\nlicense: mit\n---\n# upstream card\n")
    write_entry(root / "models" / "m" / "model.yaml", {
        "schema": "linecaster.model/1", "id": "m", "source": {"kind": "hf", "ref": "org/m"},
        "pins": [{"revision": "abc", "pinned": dt.date(2026, 11, 3), "files": {"w.safetensors": "sha256:" + "0" * 64},
                  "card": "upstream/abc/README.md", "card_sha256": sha256_file(up / "README.md")}],
        "license": "MIT"}, "Ours.\n")
    write_entry(root / "presets" / "page" / "p.yaml", {
        "schema": "linecaster.preset/1", "id": "p", "edition": edition, "step": "page",
        "model": {"id": "m", "revision": "abc"}, "engine": "chat.v1", "options": {"adapter": "x"},
        "settings": {"sampling": {"temperature": temperature}}, "support": "core"}, prose)


def test_release_freezes_an_edition(tmp_path):
    make(tmp_path)
    c = Catalog([tmp_path])
    assert c.verify() == []
    entry = c.release("p", commit="deadbee", today=dt.date(2026, 11, 3))
    assert entry.resolved["model"] == {"id": "m", "revision": "abc", "files": {"w.safetensors": "sha256:" + "0" * 64}}
    lock = (tmp_path / "catalog.lock").read_text()
    assert lock.startswith("# yaml-language-server: $schema=") and lock.splitlines()[1].startswith("# generated")
    (tmp_path / "catalog.lock").write_text(lock.replace("  p@1:\n", "  p@1:  # the first\n"))

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
    assert "p@1:  # the first" in (tmp_path / "catalog.lock").read_text()       # written back with its comments
    make(tmp_path, temperature=0.5, edition=2)             # released edition 2 cannot be released again changed
    with pytest.raises(ValueError, match="edition 3"):
        Catalog([tmp_path]).release("p")


def test_verify_catches_edited_cards_and_dangling_references(tmp_path):
    make(tmp_path)
    (tmp_path / "models" / "m" / "upstream" / "abc" / "README.md").write_text("edited")
    write_entry(tmp_path / "presets" / "recognition" / "q.yaml", {
        "schema": "linecaster.preset/1", "id": "q", "edition": 1, "step": "recognition",
        "model": {"id": "m", "revision": "nope"}, "engine": "k.v1"})
    write_entry(tmp_path / "evidence" / "e.yaml", {
        "schema": "linecaster.evidence/1", "preset": "p@7", "source": "own-run", "dataset": "d@r",
        "metrics": {"cer_reading": 0.03}, "date": dt.date(2026, 11, 3)})
    problems = Catalog([tmp_path]).verify()
    assert any("differs from its pinned sha256" in p for p in problems)
    assert any("preset q" in p and "no pin 'nope'" in p for p in problems)
    assert any("evidence e.yaml" in p for p in problems)


def test_documents_are_strict(tmp_path):
    make(tmp_path)
    meta = yamlio.read(tmp_path / "presets" / "page" / "p.yaml")
    meta["temprature"] = 0.1
    write_entry(tmp_path / "presets" / "page" / "p.yaml", meta)
    with pytest.raises(ValueError, match="temprature"):
        Catalog([tmp_path])


def test_presets_live_in_their_step_folder(tmp_path):
    make(tmp_path)
    (tmp_path / "presets" / "layout").mkdir()
    (tmp_path / "presets" / "page" / "p.yaml").rename(tmp_path / "presets" / "layout" / "p.yaml")
    with pytest.raises(ValueError, match="differs from its folder 'layout'"):
        Catalog([tmp_path])


def test_engine_and_pipeline_ids_are_versioned(tmp_path):
    make(tmp_path)
    meta = yamlio.read(tmp_path / "presets" / "page" / "p.yaml")
    meta["engine"] = "chat/1"
    write_entry(tmp_path / "presets" / "page" / "p.yaml", meta)
    with pytest.raises(ValueError, match="versioned"):
        Catalog([tmp_path])


def test_the_catalogue_is_consistent():
    """Read as data: engines that are not installed are not an error here (tests/test_engines_catalog.py)."""
    c = Catalog()
    assert c.verify() == []
    assert len(c.presets) >= 39 and all(c.resolve(f"{pid}@{p.edition}").released for pid, (_, p) in c.presets.items())
    assert all(c.resolve_recipe(f"{rid}@{r.edition}").released for rid, (_, r) in c.recipes.items())


def test_docs_from_the_catalogue(tmp_path):
    from linecaster.catalog import docs

    root = tmp_path / "cat"
    make(root)
    make_recipe(root)
    write_entry(root / "evidence" / "e.yaml", {
        "schema": "linecaster.evidence/1", "preset": "p@1", "source": "own-run", "dataset": "d@r",
        "metrics": {"cer_reading": 0.0312}, "date": dt.date(2026, 11, 3)})
    readme = tmp_path / "README.md"
    readme.write_text("intro\n<!-- catalog:start -->\nold\n<!-- catalog:end -->\noutro\n")
    (tmp_path / "docs" / "presets").mkdir(parents=True)
    (tmp_path / "docs" / "presets" / "stale.md").write_text("from an earlier run")
    docs.write(Catalog([root]), tmp_path / "docs", readme=readme)
    out = tmp_path / "docs"
    page = (out / "presets" / "page" / "p.md").read_text()
    assert "Why these settings." in page and "| 2026-11-03 | Linecaster run | d@r | cer_reading 0.0312 |" in page
    assert "[`chat.v1`](../../engines/chat.v1.md)" in page and "(../../models/m.md)" in page
    model = (out / "models" / "m.md").read_text()
    assert "Ours." in model and "(../../cat/models/m/upstream/abc/README.md)" in model and "../presets/page/p.md" in model
    assert "[`p@1`](../presets/page/p.md)" in (out / "recipes" / "r.md").read_text()
    assert (out / "engines" / "kraken.recognition.v1.md").exists() and "## Slots" in (out / "pipelines" / "chain.v1.md").read_text()
    assert not (out / "presets" / "stale.md").exists()
    index = (out / "README.md").read_text()
    assert "| [`p`](presets/page/p.md) | `chat.v1` | MIT | 0.0312 |" in index and "(recipes/r.md)" in index
    text = readme.read_text()
    assert "old" not in text and "[`p`](docs/presets/page/p.md) |" in text and "✅" not in text and text.endswith("outro\n")


def test_unknown_engines_are_reported(tmp_path):
    make(tmp_path)
    meta = yamlio.read(tmp_path / "presets" / "page" / "p.yaml")
    meta["engine"] = "chat.v9"
    write_entry(tmp_path / "presets" / "page" / "p.yaml", meta)
    assert any("'chat.v9' is not registered" in p for p in Catalog([tmp_path]).verify())


def make_recipe(root, preset="p@1", text="reflow", edition=1):
    write_entry(root / "recipes" / "r.yaml", {
        "schema": "linecaster.recipe/1", "id": "r", "edition": edition, "pipeline": "chain.v1",
        "presets": {"recognition": preset}, "options": {"text": text}, "support": "core"}, "Why this combination.")


def test_a_recipe_cannot_share_a_presets_name(tmp_path):
    """launch.py runs recipes and whole-page presets by name, so a name means one thing."""
    make(tmp_path)
    make_recipe(tmp_path)
    (tmp_path / "recipes" / "r.yaml").rename(tmp_path / "recipes" / "p.yaml")
    meta = yamlio.read(tmp_path / "recipes" / "p.yaml")
    write_entry(tmp_path / "recipes" / "p.yaml", {**meta, "id": "p"})
    with pytest.raises(ValueError, match="ids used for a preset and a recipe"):
        Catalog([tmp_path])


def test_recipes_pin_released_preset_editions(tmp_path):
    make(tmp_path)
    make_recipe(tmp_path)
    c = Catalog([tmp_path])
    with pytest.raises(ValueError, match="release its presets first"):
        c.release("r")
    c.release("p")
    c = Catalog([tmp_path])
    entry = c.release("r")
    assert entry.resolved["presets"] == {"recognition": {"ref": "p@1", "sha256": c.resolve("p@1").sha256}}
    assert Catalog([tmp_path]).verify() == []
    make_recipe(tmp_path, text="lines")                       # changed without a new edition
    assert any("recipe r@1 is released" in p for p in Catalog([tmp_path]).verify())
    make_recipe(tmp_path, text="lines", edition=2)
    c = Catalog([tmp_path])
    assert c.verify() == [] and c.resolve_recipe("r@1").content["options"] == {"text": "reflow"}
    with pytest.raises(ValueError, match="exact preset editions"):
        make_recipe(tmp_path, preset="p")
        Catalog([tmp_path])


def test_evidence_for_a_recipe(tmp_path):
    make(tmp_path)
    make_recipe(tmp_path)
    Catalog([tmp_path]).release("p")
    write_entry(tmp_path / "evidence" / "e.yaml", {
        "schema": "linecaster.evidence/1", "recipe": "r@1", "source": "own-run", "dataset": "d@r",
        "metrics": {"lines_identical": 10}, "date": dt.date(2026, 11, 3)})
    assert Catalog([tmp_path]).verify() == []
    write_entry(tmp_path / "evidence" / "e.yaml", {
        "schema": "linecaster.evidence/1", "recipe": "r@1", "preset": "p@1", "source": "own-run", "dataset": "d",
        "metrics": {}, "date": dt.date(2026, 11, 3)})
    with pytest.raises(ValueError, match="one preset or one recipe"):
        Catalog([tmp_path])


def test_a_recipe_fills_a_pipeline(tmp_path):
    import argparse

    from linecaster.runtime import run

    make(tmp_path)
    make_recipe(tmp_path)
    Catalog([tmp_path]).release("p")
    Catalog([tmp_path]).release("r")
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe")
    ap.add_argument("--recognizer")
    ap.add_argument("--text", default="lines")
    c = Catalog([tmp_path])
    argv = ["--recipe", "r"]
    a = ap.parse_args(argv)
    run.apply_recipe(ap, a, "chain.v1", {"recognition": "recognizer"}, argv, c)
    assert (a.recognizer, a.text) == ("p@1", "reflow")
    assert a.recipe_record["ref"] == "r@1" and "overrides" not in a.recipe_record
    argv += ["--text", "lines", "--recognizer", "other@1"]
    a = ap.parse_args(argv)
    run.apply_recipe(ap, a, "chain.v1", {"recognition": "recognizer"}, argv, c)
    assert a.recipe_record["overrides"] == {"recognition": "other@1", "text": "lines"}
    with pytest.raises(SystemExit, match="not vlm.v1"):
        run.apply_recipe(ap, ap.parse_args(argv[:2]), "vlm.v1", {}, argv[:2], c)


def test_recipe_stamp_names_the_recipe_on_every_step():
    from linecaster.blocks.validation.recipe import RecipeStamper
    from linecaster.data import ModelInfo, Transcription
    from linecaster.data.page import Page

    page = Page(page_id="p", item_id="i", transcriptions={"ocr_new": Transcription(model=[
        ModelInfo(step="layout", name="a"), ModelInfo(step="recognition", name="b")])})
    out = RecipeStamper("r@1", "sha256:" + "1" * 64).process_page(None, page)
    assert {(m.recipe, m.recipe_sha256[:8]) for m in out.transcriptions["ocr_new"].model} == {("r@1", "sha256:1")}


def test_committed_schemas_are_the_models():
    """``schemas/`` holds what the Pydantic models generate (`linecaster catalog schemas` rewrites it)."""
    from linecaster.catalog.registry import schema_problems
    from linecaster.catalog.schema import SCHEMA_DIR, json_schemas

    assert schema_problems() == []
    assert sorted(p.name for p in SCHEMA_DIR.glob("*.json")) == sorted(json_schemas())


def test_verify_checks_the_files(tmp_path):
    make(tmp_path)
    assert Catalog([tmp_path]).verify() == []
    p = tmp_path / "presets" / "page" / "p.yaml"
    p.write_text(p.read_text().split("\n", 1)[1])                                  # no schema line
    (tmp_path / "presets" / "page" / "p.md").unlink()                              # a core preset without prose
    (tmp_path / "presets" / "page" / "gone.md").write_text("Prose of a deleted preset.\n")
    (tmp_path / "models" / "m" / "model.md").write_text("---\nlicense: MIT\n---\nOurs.\n")
    (tmp_path / "presets" / "page" / "p.json").write_text("{}")
    problems = Catalog([tmp_path]).verify()
    assert any("p.yaml: the first line does not name its schema" in x for x in problems)
    assert any("preset p (core): its prose is missing" in x for x in problems)
    assert any("gone.md: Markdown without its YAML file" in x for x in problems)
    assert any("model.md: front matter in the prose" in x for x in problems)
    assert any("p.json: neither YAML nor Markdown" in x for x in problems)
