"""The catalog (docs/reference/catalog.md): YAML 1.2 booleans, documents, release, immutability, old editions, and
the installed catalog being consistent."""
import datetime as dt
from dataclasses import fields
from pathlib import Path

import pytest

from linecaster.catalog import Evidence, yamlio
from linecaster.catalog.registry import Catalog, Directory, sha256_file, write_entry
from linecaster.errors import CatalogError, PipelineConfigError


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
    write_entry(root / "presets" / "recognition" / "p.yaml", {
        "schema": "linecaster.preset/1", "id": "p", "edition": edition, "step": "recognition",
        "model": {"id": "m", "revision": "abc"}, "engine": "chat.v1", "options": {"adapter": "lighton-ocr-2"},
        "settings": {"sampling": {"temperature": temperature}}, "capabilities": {"unit": "page"}, "support": "core"}, prose)


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
    with pytest.raises(CatalogError, match="edition 3"):
        Catalog([tmp_path]).release("p")


def test_verify_catches_edited_cards_and_dangling_references(tmp_path):
    make(tmp_path)
    (tmp_path / "models" / "m" / "upstream" / "abc" / "README.md").write_text("edited")
    write_entry(tmp_path / "presets" / "recognition" / "q.yaml", {
        "schema": "linecaster.preset/1", "id": "q", "edition": 1, "step": "recognition",
        "model": {"id": "m", "revision": "nope"}, "engine": "k.v1"})
    problems = Catalog([tmp_path]).verify()
    assert any("differs from its pinned sha256" in p for p in problems)
    assert any("preset q" in p and "no pin 'nope'" in p for p in problems)


def test_documents_are_strict(tmp_path):
    make(tmp_path)
    meta = yamlio.read(tmp_path / "presets" / "recognition" / "p.yaml")
    meta["temprature"] = 0.1
    write_entry(tmp_path / "presets" / "recognition" / "p.yaml", meta)
    with pytest.raises(CatalogError, match="temprature"):
        Catalog([tmp_path])


def test_presets_live_in_their_step_folder(tmp_path):
    make(tmp_path)
    (tmp_path / "presets" / "layout").mkdir()
    (tmp_path / "presets" / "recognition" / "p.yaml").rename(tmp_path / "presets" / "layout" / "p.yaml")
    with pytest.raises(CatalogError, match="differs from its folder 'layout'"):
        Catalog([tmp_path])


def test_engine_and_pipeline_ids_are_versioned(tmp_path):
    make(tmp_path)
    meta = yamlio.read(tmp_path / "presets" / "recognition" / "p.yaml")
    meta["engine"] = "chat/1"
    write_entry(tmp_path / "presets" / "recognition" / "p.yaml", meta)
    with pytest.raises(CatalogError, match="versioned"):
        Catalog([tmp_path])


def test_the_catalog_is_consistent():
    """Read as data: engines that are not installed are not an error here (tests/test_engines_catalog.py)."""
    c = Catalog()
    assert c.verify() == []
    assert len(c.presets) >= 39 and all(c.resolve(f"{pid}@{p.edition}").released for pid, (_, p) in c.presets.items())
    assert all(c.resolve_recipe(f"{rid}@{r.edition}").released for rid, (_, r) in c.recipes.items())


def test_docs_from_the_catalog(tmp_path):
    from linecaster.catalog import docs

    root = tmp_path / "cat"
    make(root)
    make_recipe(root)
    (tmp_path / "docs" / "presets").mkdir(parents=True)
    (tmp_path / "docs" / "presets" / "stale.md").write_text("from an earlier run")
    docs.write(Catalog([root]), tmp_path / "docs")
    out = tmp_path / "docs"
    page = (out / "presets" / "recognition" / "p.md").read_text()
    assert "Why these settings." in page
    assert "Evidence" not in page                                       # the pages quote no measurements
    assert "[`chat.v1`](../../engines/chat.v1.md)" in page and "(../../models/m.md)" in page
    model = (out / "models" / "m.md").read_text()
    assert "Ours." in model and "(../../cat/models/m/upstream/abc/README.md)" in model and "../presets/recognition/p.md" in model
    assert "[`p@1`](../presets/recognition/p.md)" in (out / "recipes" / "r.md").read_text()
    assert (out / "engines" / "kraken.recognition.v1.md").exists() and "## Slots" in (out / "pipelines" / "transcribe_modular.v1.md").read_text()
    assert not (out / "presets" / "stale.md").exists()
    index = (out / "README.md").read_text()
    assert "| [`p`](presets/recognition/p.md) | `chat.v1` | MIT |" in index and "(recipes/r.md)" in index
    assert "0.0312" not in index and "CER" not in index


def test_unknown_engines_are_reported(tmp_path):
    make(tmp_path)
    meta = yamlio.read(tmp_path / "presets" / "recognition" / "p.yaml")
    meta["engine"] = "chat.v9"
    write_entry(tmp_path / "presets" / "recognition" / "p.yaml", meta)
    assert any("'chat.v9' is not registered" in p for p in Catalog([tmp_path]).verify())


def make_recipe(root, preset="p@1", window=16, edition=1, pipeline="transcribe_vlm.v1"):
    write_entry(root / "recipes" / "r.yaml", {
        "schema": "linecaster.recipe/1", "id": "r", "edition": edition, "pipeline": pipeline,
        "presets": {"recognition": preset}, "options": {"window": window}, "support": "core"}, "Why this combination.")


def test_a_recipe_cannot_share_a_presets_name(tmp_path):
    """launch.py runs recipes and page presets by name, so a name means one thing."""
    make(tmp_path)
    make_recipe(tmp_path)
    (tmp_path / "recipes" / "r.yaml").rename(tmp_path / "recipes" / "p.yaml")
    meta = yamlio.read(tmp_path / "recipes" / "p.yaml")
    write_entry(tmp_path / "recipes" / "p.yaml", {**meta, "id": "p"})
    with pytest.raises(CatalogError, match="ids used for a preset and a recipe"):
        Catalog([tmp_path])


def test_recipes_pin_released_preset_editions(tmp_path):
    make(tmp_path)
    make_recipe(tmp_path)
    c = Catalog([tmp_path])
    with pytest.raises(CatalogError, match="release its presets first"):
        c.release("r")
    c.release("p")
    c = Catalog([tmp_path])
    entry = c.release("r")
    assert entry.resolved["presets"] == {"recognition": {"ref": "p@1", "sha256": c.resolve("p@1").sha256}}
    assert Catalog([tmp_path]).verify() == []
    make_recipe(tmp_path, window=8)                           # changed without a new edition
    assert any("recipe r@1 is released" in p for p in Catalog([tmp_path]).verify())
    make_recipe(tmp_path, window=8, edition=2)
    c = Catalog([tmp_path])
    assert c.verify() == [] and c.resolve_recipe("r@1").content["options"] == {"window": 16}
    with pytest.raises(CatalogError, match="exact preset editions"):
        make_recipe(tmp_path, preset="p")
        Catalog([tmp_path])


def test_the_evidence_format_stays_for_derivatives():
    """An evaluation's evidence records validate with ``Evidence`` (``linecaster.evidence/1``): one exact preset or
    recipe edition each. The catalog reads none."""
    from pydantic import ValidationError

    ev = Evidence.model_validate({"schema": "linecaster.evidence/1", "recipe": "r@1", "source": "own-run",
                                  "dataset": "d@r", "metrics": {"lines_identical": 10}, "date": dt.date(2026, 11, 3)})
    assert ev.subject == "r@1" and not ev.preset
    with pytest.raises(ValidationError, match="one preset or one recipe"):
        Evidence.model_validate({"schema": "linecaster.evidence/1", "recipe": "r@1", "preset": "p@1",
                                 "source": "own-run", "dataset": "d", "metrics": {}, "date": dt.date(2026, 11, 3)})
    with pytest.raises(ValidationError, match="exact edition"):
        Evidence.model_validate({"schema": "linecaster.evidence/1", "preset": "p", "source": "own-run",
                                 "dataset": "d", "metrics": {}, "date": dt.date(2026, 11, 3)})
    assert "evidence" not in {f.name for f in fields(Directory)}


def test_a_recipe_fills_a_pipeline(tmp_path):
    import argparse

    from linecaster.runtime import run

    make(tmp_path)
    make_recipe(tmp_path)
    Catalog([tmp_path]).release("p")
    Catalog([tmp_path]).release("r")
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe")
    ap.add_argument("--recognition")
    ap.add_argument("--window", type=int, default=48)
    c = Catalog([tmp_path])
    argv = ["--recipe", "r"]
    a = ap.parse_args(argv)
    run.apply_recipe(ap, a, "transcribe_vlm.v1", {"recognition": "recognition"}, argv, c)
    assert (a.recognition, a.window) == ("p@1", 16)
    assert a.recipe_record["ref"] == "r@1" and "overrides" not in a.recipe_record
    argv += ["--window", "8", "--recognition", "other@1"]
    a = ap.parse_args(argv)
    run.apply_recipe(ap, a, "transcribe_vlm.v1", {"recognition": "recognition"}, argv, c)
    assert a.recipe_record["overrides"] == {"recognition": "other@1", "window": 8}
    with pytest.raises(PipelineConfigError, match="not transcribe_modular.v1"):
        run.apply_recipe(ap, ap.parse_args(argv[:2]), "transcribe_modular.v1", {}, argv[:2], c)


def test_a_recipe_edition_locks_its_expanded_pipeline(tmp_path):
    """``release`` records the recipe's pipeline, built from its pipeline shape without the engines; ``verify``
    builds it again and reports drift."""
    from linecaster.catalog import registry
    from linecaster.runtime import provenance, run

    make(tmp_path)
    make_recipe(tmp_path)
    Catalog([tmp_path]).release("p")
    c = Catalog([tmp_path])
    entry = c.release("r")
    assert entry.pipeline_sha256.startswith("sha256:")
    assert [b["block"] for b in entry.pipeline] == ["ImageFolderReader", "PageRecognizer", "RecipeStamper",
                                                    "RejectWriter", "PageJsonlWriter"]
    recognizer = entry.pipeline[1]["params"]
    assert recognizer["backend"]["preset"] == "p@1" and "endpoint" not in recognizer["backend"]
    assert entry.pipeline[2]["params"] == {"recipe": "r@1", "recipe_sha256": entry.sha256}
    # what the shape builds into other folders is the same pipeline (in this process: the catalog put in place)
    from linecaster.pipelines import transcribe_vlm

    with registry.active(c):
        plan = run.describe(transcribe_vlm, ["IN", "ELSEWHERE", "--recipe", "r"], c)
    assert provenance.pipeline_sha256(plan) == entry.pipeline_sha256
    assert Catalog([tmp_path]).verify() == []
    # drift: the lock no longer matches what the pipeline script builds
    lock = (tmp_path / "catalog.lock").read_text()
    (tmp_path / "catalog.lock").write_text(lock.replace("recipe_sha256:", "recipe_sha256_old:").replace(
        entry.pipeline_sha256, "sha256:" + "1" * 64))
    problems = Catalog([tmp_path]).verify()
    assert any("recipe r@1: its expanded pipeline drifted from the lock" in p and "RecipeStamper (block 3)" in p
               for p in problems)
    with pytest.raises(CatalogError, match="drifted"):
        Catalog([tmp_path]).release("r")
    assert Catalog([tmp_path]).release("r", migrate_pipeline=True).pipeline_sha256 == entry.pipeline_sha256
    assert Catalog([tmp_path]).verify() == []
    # a released edition from before pipelines were locked gets its pipeline on release (a catalog migration)
    lock = (tmp_path / "catalog.lock").read_text()
    head, _, _ = lock.partition("    pipeline:\n")
    (tmp_path / "catalog.lock").write_text(head)
    assert any("its expanded pipeline is not in the lock" in p for p in Catalog([tmp_path]).verify())
    again = Catalog([tmp_path]).release("r")
    assert (again.sha256, again.pipeline_sha256) == (entry.sha256, entry.pipeline_sha256)
    # a recipe whose pipeline cannot be built is not released
    make_recipe(tmp_path, edition=2, pipeline="transcribe_modular.v1")
    with pytest.raises(CatalogError, match="its pipeline cannot be built"):
        Catalog([tmp_path]).release("r")


def test_recipe_stamp_names_the_recipe_on_every_step():
    from linecaster.blocks.validation.recipe import RecipeStamper
    from linecaster.data import StepInfo, Transcription
    from linecaster.data.page import Page

    page = Page(page_id="p", item_id="i", transcriptions={"ocr_new": Transcription(steps=[
        StepInfo(step="layout", name="a"), StepInfo(step="recognition", name="b")])})
    out = RecipeStamper("r@1", "sha256:" + "1" * 64).process_page(None, page)
    assert {(m.recipe, m.recipe_sha256[:8]) for m in out.transcriptions["ocr_new"].steps} == {("r@1", "sha256:1")}


def test_committed_schemas_are_the_models():
    """``schemas/`` holds what the Pydantic models generate (`linecaster catalog schemas` rewrites it)."""
    from linecaster.catalog.registry import schema_problems
    from linecaster.catalog.schema import SCHEMA_DIR, json_schemas

    assert schema_problems() == []
    assert sorted(p.name for p in SCHEMA_DIR.glob("*.json")) == sorted(json_schemas())


def test_verify_checks_the_files(tmp_path):
    make(tmp_path)
    assert Catalog([tmp_path]).verify() == []
    p = tmp_path / "presets" / "recognition" / "p.yaml"
    p.write_text(p.read_text().split("\n", 1)[1])                                  # no schema line
    (tmp_path / "presets" / "recognition" / "p.md").unlink()                              # a core preset without prose
    (tmp_path / "presets" / "recognition" / "gone.md").write_text("Prose of a deleted preset.\n")
    (tmp_path / "models" / "m" / "model.md").write_text("---\nlicense: MIT\n---\nOurs.\n")
    (tmp_path / "presets" / "recognition" / "p.json").write_text("{}")
    problems = Catalog([tmp_path]).verify()
    assert any("p.yaml: the first line does not name its schema" in x for x in problems)
    assert any("preset p (core): its prose is missing" in x for x in problems)
    assert any("gone.md: Markdown without its YAML file" in x for x in problems)
    assert any("model.md: front matter in the prose" in x for x in problems)
    assert any("p.json: neither YAML nor Markdown" in x for x in problems)


def test_old_hashes_still_resolve():
    """A catalog migration (changes that keep behavior) recomputes an edition's hash and keeps the old one in the
    lock: run records written before it still resolve."""
    c = Catalog()
    lock = c.dirs[0].lock
    squiddle = lock.recipes["squiddle@1"]
    assert squiddle.previous and squiddle.resolved["pipeline"] == "transcribe_modular.v1"
    for ref, entry in [*lock.presets.items(), *lock.recipes.items()]:
        resolve = c.resolve_recipe if ref in lock.recipes else c.resolve
        for sha in (entry.sha256, *entry.previous):
            assert resolve(ref, sha256=sha).sha256 == entry.sha256
            assert c.by_sha256(sha).ref == ref
    with pytest.raises(CatalogError, match="not sha256:0"):
        c.resolve_recipe("squiddle@1", sha256="sha256:" + "0" * 64)
    with pytest.raises(CatalogError, match="no released edition"):
        c.by_sha256("sha256:" + "0" * 64)


def test_whole_page_vlms_are_recognition_presets():
    """There is no step ``page``: a VLM reading whole pages is ``recognition`` with ``unit: page`` (a page preset)."""
    from linecaster.catalog import STEPS

    c = Catalog()
    assert "page" not in STEPS
    pages = [pid for pid, (_, p) in c.presets.items() if p.page_preset]
    engines = {"surya-ocr-2.5": "surya.recognition.v1", "indra-ocr": "indra.recognition.v1",
               "falcon-ocr": "falcon.recognition.v1", "oxr-1.0": "oxr.recognition.v1"}     # page engines
    assert len(pages) >= 23 and all(c.preset(pid).engine == engines.get(pid, "chat.v1") for pid in pages)
    assert all(c.resolve(pid).content["step"] == "recognition" for pid in pages)


def test_describing_a_recipe_imports_no_engine():
    """The describe mode builds the modular pipeline's blocks without its engines: nothing of them is imported."""
    import json
    import subprocess
    import sys

    check = ("import json, sys\n"
             "from linecaster.runtime.run import describe_recipe\n"
             "d = describe_recipe('squiddle@1')\n"
             "heavy = ('linecaster_kraken', 'linecaster_paddlex', 'linecaster_tesseract', 'kraken', 'torch', "
             "'onnxruntime', 'paddlex')\n"
             "print(json.dumps({'sha': d['pipeline_sha256'], 'loaded': sorted(m for m in sys.modules "
             "if m.split('.')[0] in heavy)}))\n")
    out = json.loads(subprocess.run([sys.executable, "-c", check], capture_output=True, text=True, check=True).stdout)
    assert out["loaded"] == []
    assert out["sha"] == Catalog().dirs[0].lock.recipes["squiddle@1"].pipeline_sha256


def test_a_missing_engine_names_its_package_and_the_scripts_that_install_it():
    """Engine packages are not on PyPI: the error says where an engine is and which pipeline scripts install it, or,
    for kraken, which no pipeline script installs, where it runs instead."""
    from linecaster.catalog import engine_class, engine_spec
    from linecaster.catalog.code import install_hint, script_dependencies
    from linecaster.catalog.registry import engine_ids
    from linecaster.errors import CatalogError

    if "kraken.recognition.v1" in engine_ids():
        pytest.skip("the kraken engine is installed here")
    with pytest.raises(CatalogError, match=r"needs engine 'kraken.recognition.v1', which is not installed: "
                                           r"`kraken.recognition.v1` is in the engine package `linecaster-kraken` "
                                           r"\(engines/kraken, not on PyPI\), which no pipeline script here installs: "
                                           r".*a script of your own.*--backend served --endpoint URL"):
        engine_spec("kraken-ppocrv6-medium")
    with pytest.raises(CatalogError, match=r"`linecaster-paddlex` .*`pipelines/transcribe_modular.py` and "
                                           r"`pipelines/transcribe_vlm.py` install\); installed: "):
        engine_class("paddlex.layout.v1")
    assert install_hint("recomposition.unicode.v1") == "" and install_hint("nowhere.recognition.v1") == ""
    script = Path(__file__).resolve().parents[2] / "pipelines" / "transcribe_modular.py"
    assert {"linecaster", "linecaster-paddlex", "linecaster-tesseract"} == set(script_dependencies(script))
