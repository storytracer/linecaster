"""The rule-based slots of the pipeline shapes (``--typography``, ``--recomposition``, ``--normalization``,
``--composition``), filled by hand or by a recipe, and the item stage they make: built in the describe mode."""
from pathlib import Path

import pytest

from linecaster.errors import PipelineConfigError
from linecaster.runtime import run

from linecaster.pipelines import transcribe_modular as MODULAR

PIPELINES = Path(__file__).resolve().parents[2] / "pipelines"
BIND = PIPELINES / "bind.py"
MODELS = ["--layout", "single-region@1", "--lines", "pp-ocrv6-medium-det@1", "--recognition", "kraken-ppocrv6-medium@1"]


def _describe(shape, argv):
    return run.describe(shape, argv) if not isinstance(shape, Path) else run.describe_script(shape, argv)


def _stages(shape, argv):
    plan = _describe(shape, argv)
    plan.check()
    return [[type(b).__name__ for b in s.blocks] for s in plan.stages], plan


def test_the_modular_slots():
    (blocks,), _ = _stages(MODULAR, ["IN", "OUT", *MODELS])
    assert not {"Typographer", "Recomposer", "Composer", "CharacterNormalizer"} & set(blocks)     # none picked
    (blocks,), plan = _stages(MODULAR, ["IN", "OUT", *MODELS, "--typography", "ratios", "--composition",
                                        "docling-composition", "--set", "composition.sections=true"])
    assert blocks[blocks.index("Typographer") + 1] == "Composer" and "Recomposer" not in blocks   # as laid out
    composer = next(b for b in plan.stages[0].blocks if type(b).__name__ == "Composer")
    assert composer.backend.overrides == {"sections": True}
    with pytest.raises(PipelineConfigError, match="pick --recomposition and --normalization"):
        run.describe(MODULAR, ["IN", "OUT", *MODELS, "--item-texts", "T", "--recomposition",
                                      "unicode-recomposition"])
    with pytest.raises(PipelineConfigError, match="no step 'composition'"):
        run.describe(MODULAR, ["IN", "OUT", *MODELS, "--set", "composition.sections=true"])
    with pytest.raises(PipelineConfigError, match="pick --layout"):        # single-region@1 is a slot like any
        run.describe(MODULAR, ["IN", "OUT", *MODELS[2:]])


def test_the_squiddle_recipe_fills_the_rule_based_slots():
    (blocks,), _ = _stages(MODULAR, ["IN", "OUT", "--recipe", "squiddle"])
    assert [b for b in blocks if b in ("Typographer", "Recomposer", "CharacterNormalizer", "Composer")] == [
        "Typographer", "Recomposer", "Composer"]              # the normalization is the item texts'
    (blocks,), _ = _stages(MODULAR, ["IN", "OUT", "--recipe", "squiddle", "--item-texts", "T"])
    assert blocks[blocks.index("Binder"):] == ["Binder", "Recomposer", "CharacterNormalizer", "ItemTextWriter",
                                               "ItemTextWriter"]
    stages, plan = _stages(MODULAR, ["IN", "OUT", "--recipe", "squiddle", "--item-texts", "T", "--tasks", "2"])
    assert [s.name for s in plan.stages] == ["pages", "items"]
    assert stages[1][:4] == ["PageRecordReader", "Binder", "Recomposer", "CharacterNormalizer"]


def test_bind_takes_the_item_texts_recipe():
    (blocks,), plan = _stages(BIND, ["P", "OUT", "--recipe", "item-texts", "--files"])
    assert blocks == ["PageRecordReader", "RejectWriter", "Binder", "Recomposer", "CharacterNormalizer", "Composer",
                      "RecipeStamper", "ItemTextWriter", "ItemTextWriter", "ItemDocumentWriter"]
    writer = plan.stages[0].blocks[-1]
    assert writer.by_format and writer.formats == ("md", "txt", "json")
    (blocks,), _ = _stages(BIND, ["P", "OUT", "--no-documents", "--variants", "verbatim_txt"])
    assert blocks == ["PageRecordReader", "RejectWriter", "Binder", "ItemTextWriter"]
    with pytest.raises(PipelineConfigError, match="pick --recomposition and --normalization and --composition"):
        _describe(BIND, ["P", "OUT"])
    with pytest.raises(PipelineConfigError, match="nothing to write"):
        _describe(BIND, ["P", "OUT", "--no-texts", "--no-documents"])
