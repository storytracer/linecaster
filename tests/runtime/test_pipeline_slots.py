"""The rule-based slots of the pipeline shapes (``--typography``, ``--recomposition``, ``--composition``), filled by
hand or by a recipe, the item stage they make and the texts it writes (``--text``): built in the describe mode."""
import pytest

from linecaster.errors import PipelineConfigError
from linecaster.pipelines import bind as BIND
from linecaster.pipelines import transcribe_modular as MODULAR
from linecaster.runtime import run

MODELS = ["--layout", "single-region", "--lines", "pp-ocrv6-medium-det", "--recognition", "kraken-ppocrv6-medium"]

#: the item stage's presets (bind.v1's slots)
PRESETS = ("--recomposition", "unicode-recomposition", "--composition",
           "linked-composition")


def _stages(shape, argv):
    plan = run.describe(shape, argv)
    plan.check()
    return [[type(b).__name__ for b in s.blocks] for s in plan.stages], plan


def test_the_modular_slots():
    (blocks,), _ = _stages(MODULAR, ["IN", "OUT", *MODELS])
    assert not {"Typographer", "Recomposer", "Composer"} & set(blocks)     # none picked
    (blocks,), plan = _stages(MODULAR, ["IN", "OUT", *MODELS, "--typography", "ratios", "--composition",
                                        "linked-composition", "--set", "composition.sections=true"])
    assert blocks[blocks.index("Typographer") + 1] == "Composer" and "Recomposer" not in blocks   # as laid out
    composer = next(b for b in plan.stages[0].blocks if type(b).__name__ == "Composer")
    assert composer.backend.overrides == {"sections": True}
    with pytest.raises(PipelineConfigError, match="pick --composition"):
        run.describe(MODULAR, ["IN", "OUT", *MODELS, "--item-texts", "T", "--recomposition",
                                      "unicode-recomposition"])
    with pytest.raises(PipelineConfigError, match="no step 'composition'"):
        run.describe(MODULAR, ["IN", "OUT", *MODELS, "--set", "composition.sections=true"])
    with pytest.raises(PipelineConfigError, match="pick --layout"):        # single-region is a slot like any
        run.describe(MODULAR, ["IN", "OUT", *MODELS[2:]])


def test_the_modular_page_files_are_named_by_item_or_flat_with_a_suffix():
    def writer(*argv):
        plan = run.describe(MODULAR, ["IN", "OUT", *MODELS, "--files", "F", *argv])
        return next(b for b in plan.stages[0].blocks if type(b).__name__ == "PageFileWriter")

    w = writer()
    assert (w.bucket_by_item, w.suffix) == (True, "")                    # <item>/<page>.<ext>
    w = writer("--naming", "flat", "--suffix", ".paddle")
    assert (w.bucket_by_item, w.suffix) == (False, ".paddle")            # <page>.paddle.<ext>
    assert writer("--suffix", ".x").bucket_by_item


def test_the_squiddle_recipe_fills_the_rule_based_slots():
    (blocks,), _ = _stages(MODULAR, ["IN", "OUT", "--recipe", "squiddle"])
    assert [b for b in blocks if b in ("Typographer", "Recomposer", "Composer")] == [
        "Typographer", "Recomposer", "Composer"]
    (blocks,), plan = _stages(MODULAR, ["IN", "OUT", "--recipe", "squiddle", "--item-texts", "T",
                                        "--text", "literal:txt", "--text", "latin-historic+unicode-marks+flow:md"])
    assert blocks[blocks.index("Binder"):] == ["Binder", "Recomposer", "Composer", "ItemDocumentWriter",
                                               "ItemTextWriter"]
    writer = next(b for b in plan.stages[0].blocks if type(b).__name__ == "ItemDocumentWriter")
    assert writer.texts == (("literal", "txt"), ("latin-historic+unicode-marks+flow", "md"))
    stages, plan = _stages(MODULAR, ["IN", "OUT", "--recipe", "squiddle", "--item-texts", "T", "--tasks", "2"])
    assert [s.name for s in plan.stages] == ["pages", "items"]
    assert stages[1][:4] == ["PageRecordReader", "Binder", "Recomposer", "Composer"]


def test_bind_takes_its_presets_and_texts():
    (blocks,), plan = _stages(BIND, ["P", "OUT", *PRESETS, "--text", "literal:txt", "--text", "nfc+flow:md", "--jsonl"])
    assert blocks == ["PageRecordReader", "RejectWriter", "Binder", "Recomposer", "Composer", "ItemDocumentWriter",
                      "ItemTextWriter"]
    writer = plan.stages[0].blocks[-2]
    assert writer.texts == (("literal", "txt"), ("nfc+flow", "md"))
    (blocks,), plan = _stages(BIND, ["P", "OUT", "--composition", "linked-composition"])
    assert blocks == ["PageRecordReader", "RejectWriter", "Binder", "Composer", "ItemDocumentWriter"]
    assert plan.stages[0].blocks[-1].texts == (("literal", "json"),)      # by default the document as it is
    with pytest.raises(PipelineConfigError, match="pick --composition"):
        run.describe(BIND, ["P", "OUT"])
    with pytest.raises(PipelineConfigError, match="no-such"):
        run.describe(BIND, ["P", "OUT", *PRESETS, "--text", "no-such:md"])
    with pytest.raises(PipelineConfigError, match="<strategy>:<format>"):
        run.describe(BIND, ["P", "OUT", *PRESETS, "--text", "literal"])
