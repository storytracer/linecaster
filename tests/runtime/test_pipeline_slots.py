"""The rule-based slots of the pipeline scripts (``--typography``, ``--recomposition``, ``--normalization``,
``--composition``), filled by hand or by a recipe, and the item stage they make: built in the describe mode."""
from pathlib import Path

import pytest

from linecaster.errors import PipelineConfigError
from linecaster.runtime import run

PIPELINES = Path(__file__).resolve().parents[2] / "pipelines"
MODULAR, BIND = PIPELINES / "transcribe_modular.py", PIPELINES / "bind.py"
MODELS = ["--lines", "pp-ocrv6-medium-det@1", "--recognition", "kraken-ppocrv6-medium@1"]


def _stages(script, argv):
    plan = run.describe_script(script, argv)
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
        run.describe_script(MODULAR, ["IN", "OUT", *MODELS, "--item-texts", "T", "--recomposition",
                                      "unicode-recomposition"])
    with pytest.raises(PipelineConfigError, match="no step 'composition'"):
        run.describe_script(MODULAR, ["IN", "OUT", *MODELS, "--set", "composition.sections=true"])


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
        run.describe_script(BIND, ["P", "OUT"])
    with pytest.raises(PipelineConfigError, match="nothing to write"):
        run.describe_script(BIND, ["P", "OUT", "--no-texts", "--no-documents"])
