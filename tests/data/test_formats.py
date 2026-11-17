"""Data formats name their writer and their version: an annotator its linecaster, a document its producer, the
scores' Parquet its metadata; a reader refuses a format it does not know (docs/reference/compatibility.md)."""
import pytest

from linecaster.data import Annotator, Transcription
from linecaster.data.transcription import producer


def test_an_annotator_names_the_linecaster_that_recorded_it():
    from linecaster import __version__

    t = Transcription()
    a = t.add_annotator(Annotator(step="layout", name="m"))
    assert t.annotators[a].linecaster == producer() and producer().startswith(__version__)
    b = t.add_annotator(Annotator(step="layout", name="m", linecaster="0.9.3"))       # one read from a record
    assert t.annotators[b].linecaster == "0.9.3"
    assert Transcription.model_validate_json(t.model_dump_json()).annotators[a].linecaster == producer()


def test_a_document_names_its_producer_and_its_format_is_checked():
    from pydantic import ValidationError

    from linecaster.document import build_document, from_json, to_json

    doc = build_document(Transcription())
    assert doc.producer == producer() and from_json(to_json(doc)).producer == producer()
    with pytest.raises(ValidationError, match="unknown document format 'linecaster.document/9'"):
        from_json(to_json(doc).replace("linecaster.document/2", "linecaster.document/9"))


def test_scores_name_their_writer(tmp_path):
    import pyarrow.parquet as pq

    from linecaster.evaluation.run import write_scores

    path = write_scores([{"page": "p", "cer": 0.1}], tmp_path / "scores.parquet")
    assert pq.read_schema(path).metadata[b"linecaster"].decode() == producer()
