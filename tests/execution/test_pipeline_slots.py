"""The rule-based slots of the pipeline shapes (``--hierarchy``, ``--paragraphs``, ``--document``), filled by
hand or by a recipe, the item stage they make and the texts it writes (``--text``): built in the describe mode."""
import pytest

from linecaster.errors import PipelineConfigError
from linecaster.templates import bind as BIND
from linecaster.templates import transcribe_modular as MODULAR
from linecaster.execution import run

MODELS = ["--layout", "single-region", "--lines", "pp-ocrv6-medium-det", "--recognition", "kraken-ppocrv6-medium"]

#: the item stage's presets (bind.v1's slots)
PRESETS = ("--paragraphs", "unicode-paragraphs", "--document",
           "linked-document")


def _stages(shape, argv):
    plan = run.describe(shape, argv)
    plan.check()
    return [[type(b).__name__ for b in s.components] for s in plan.stages], plan


def test_the_modular_slots():
    (components,), _ = _stages(MODULAR, ["IN", "OUT", *MODELS])
    assert not {"HierarchyDetector", "ParagraphBuilder", "DocumentComposer"} & set(components)     # none picked
    (components,), plan = _stages(MODULAR, ["IN", "OUT", *MODELS, "--hierarchy", "ratios", "--document",
                                        "linked-document", "--set", "document.sections=true"])
    assert components[components.index("HierarchyDetector") + 1] == "DocumentComposer" and "ParagraphBuilder" not in components   # as laid out
    composer = next(b for b in plan.stages[0].components if type(b).__name__ == "DocumentComposer")
    assert composer.backend.overrides == {"sections": True}
    with pytest.raises(PipelineConfigError, match="pick --document"):
        run.describe(MODULAR, ["IN", "OUT", *MODELS, "--item-texts", "T", "--paragraphs",
                                      "unicode-paragraphs"])
    with pytest.raises(PipelineConfigError, match="no step 'document'"):
        run.describe(MODULAR, ["IN", "OUT", *MODELS, "--set", "document.sections=true"])
    with pytest.raises(PipelineConfigError, match="pick --layout"):        # single-region is a slot like any
        run.describe(MODULAR, ["IN", "OUT", *MODELS[2:]])


def test_the_modular_page_files_are_named_by_item_or_flat_with_a_suffix():
    def writer(*argv):
        plan = run.describe(MODULAR, ["IN", "OUT", *MODELS, "--files", "F", *argv])
        return next(b for b in plan.stages[0].components if type(b).__name__ == "PageFileWriter")

    w = writer()
    assert (w.bucket_by_item, w.suffix) == (True, "")                    # <item>/<page>.<ext>
    w = writer("--naming", "flat", "--suffix", ".paddle")
    assert (w.bucket_by_item, w.suffix) == (False, ".paddle")            # <page>.paddle.<ext>
    assert writer("--suffix", ".x").bucket_by_item


def test_the_squiddle_recipe_fills_the_rule_based_slots():
    (components,), _ = _stages(MODULAR, ["IN", "OUT", "--recipe", "squiddle"])
    assert [b for b in components if b in ("HierarchyDetector", "ParagraphBuilder", "DocumentComposer")] == [
        "HierarchyDetector", "ParagraphBuilder", "DocumentComposer"]
    (components,), plan = _stages(MODULAR, ["IN", "OUT", "--recipe", "squiddle", "--item-texts", "T",
                                        "--text", "literal:txt", "--text", "latin-historic+unicode-marks+flow:md"])
    assert components[components.index("ItemAssembler"):] == ["ItemAssembler", "ParagraphBuilder", "DocumentComposer", "ItemDocumentWriter",
                                               "ItemTextWriter"]
    writer = next(b for b in plan.stages[0].components if type(b).__name__ == "ItemDocumentWriter")
    assert writer.texts == (("literal", "txt"), ("latin-historic+unicode-marks+flow", "md"))
    stages, plan = _stages(MODULAR, ["IN", "OUT", "--recipe", "squiddle", "--item-texts", "T", "--tasks", "2"])
    assert [s.name for s in plan.stages] == ["pages", "items"]
    assert stages[1][:4] == ["PageRecordReader", "ItemAssembler", "ParagraphBuilder", "DocumentComposer"]


def test_bind_takes_its_presets_and_texts():
    (components,), plan = _stages(BIND, ["P", "OUT", *PRESETS, "--text", "literal:txt", "--text", "nfc+flow:md", "--jsonl"])
    assert components == ["PageRecordReader", "RejectWriter", "ItemAssembler", "ParagraphBuilder", "DocumentComposer", "ItemDocumentWriter",
                      "ItemTextWriter"]
    writer = plan.stages[0].components[-2]
    assert writer.texts == (("literal", "txt"), ("nfc+flow", "md"))
    (components,), plan = _stages(BIND, ["P", "OUT", "--document", "linked-document"])
    assert components == ["PageRecordReader", "RejectWriter", "ItemAssembler", "DocumentComposer", "ItemDocumentWriter"]
    assert plan.stages[0].components[-1].texts == (("literal", "json"),)      # by default the document as it is
    with pytest.raises(PipelineConfigError, match="pick --document"):
        run.describe(BIND, ["P", "OUT"])
    with pytest.raises(PipelineConfigError, match="no-such"):
        run.describe(BIND, ["P", "OUT", *PRESETS, "--text", "no-such:md"])
    with pytest.raises(PipelineConfigError, match="<strategy>:<format>"):
        run.describe(BIND, ["P", "OUT", *PRESETS, "--text", "literal"])
