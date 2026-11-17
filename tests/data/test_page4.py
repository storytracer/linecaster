"""``linecaster.page/4``: anchors into the source text, the source's revision, a status's reason, the conventions an
importer applied; page/3 rows read as they are."""
import pytest
from pydantic import ValidationError

from linecaster.data import REASONS, Anchor, Annotator, Classification, Source, Transcription
from linecaster.data.upgrade import upgrade


def test_anchor_is_a_span_of_the_source():
    t = Transcription(source=Source(kind="ground_truth", format="mediawiki", record="Page:Example.djvu/1",
                                    revision="123"))
    a = t.add_annotator(Annotator(kind="human", step="transcription", name="editors"))
    r = t.add_region(a, "r1", role="paragraph", anchor=Anchor(start=10, end=42))
    assert (r.anchor.start, r.anchor.end) == (10, 42) and t.source.revision == "123"
    with pytest.raises(ValidationError):
        Anchor(start=5, end=4)


def test_reason_belongs_to_a_status():
    c = Classification(annotator=0, target="r1", scheme="status", value="removed", reason="editorial")
    assert c.reason in REASONS
    with pytest.raises(ValidationError):
        Classification(annotator=0, target="r1", scheme="role", value="paragraph", reason="editorial")
    with pytest.raises(ValidationError):
        Classification(annotator=0, target="r1", scheme="status", value="removed", reason="unknown")


def test_annotator_names_its_conventions():
    a = Annotator(kind="rule", step="import", name="mediawiki", engine="import.mediawiki.v1",
                  conventions="mediawiki>example@2", conventions_sha256="0" * 64)
    assert Annotator.model_validate(a.model_dump()).conventions == "mediawiki>example@2"


def test_page3_rows_are_read_as_they_are():
    row = {"schema": "linecaster.page/3", "id": "p1", "text": "", "page": {"page_id": "p1"}}
    assert upgrade(row) == {**row, "schema": "linecaster.page/6"}
    with pytest.raises(ValueError):
        upgrade({"schema": "linecaster.page/9", "id": "p1"})


def test_a_page_5_row_names_the_renamed_steps_by_their_new_ids():
    """page/6 (linecaster 0.12): the annotators of ``typography``, ``recomposition`` and ``composition`` name
    ``hierarchy``, ``paragraphs`` and ``document``; everything else is as it was."""
    from linecaster.data.upgrade import upgrade

    sets = {"ocr_new": {"annotators": [{"kind": "model", "step": "layout"}, {"kind": "rule", "step": "typography"},
                                       {"kind": "rule", "step": "recomposition"}, {"kind": "rule", "step": "composition"}]}}
    row = upgrade({"schema": "linecaster.page/5", "id": "p", "page": {"page_id": "p", "transcriptions": sets}})
    assert row["schema"] == "linecaster.page/6"
    assert [a["step"] for a in row["page"]["transcriptions"]["ocr_new"]["annotators"]] == [
        "layout", "hierarchy", "paragraphs", "document"]
