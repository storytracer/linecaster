"""linecaster-tesseract: the engine's conformance (``linecaster.testing.check_engine``) and its own helpers. Run in
an environment with the package (README: the test command)."""
import numpy as np
import pytest

from linecaster.engines.api import weights_of
from linecaster.testing import check_engine
from linecaster_tesseract import TesseractRecognitionEngine
from linecaster_tesseract import models as tess
from linecaster_tesseract.recognizer import crop_line


@pytest.mark.network
def test_conformance():
    out = check_engine(TesseractRecognitionEngine, options={"weights": weights_of("tessdata-best"), "lang": "eng"})
    assert [ln.reading.text for ln in out.lines][0].startswith("The species")
    assert all(w.confidence is not None for ln in out.lines for w in ln.reading.words)


def test_the_data_is_the_catalog_pin():
    td = tess.tessdata("fast")
    assert td.model == "tessdata-fast" and td.commit == weights_of("tessdata-fast")["revision"]
    assert td.repo == "tesseract-ocr/tessdata_fast" and "eng.traineddata" in td.files
    with pytest.raises(ValueError, match="comes from a GitHub repository"):
        tess.Tessdata.of({**weights_of("tessdata-fast"), "source": {"kind": "hf", "ref": "x/y"}})


def test_strict_data_accepts_only_pinned_languages(tmp_path, monkeypatch):
    monkeypatch.setenv("LINECASTER_CACHE", str(tmp_path))
    with pytest.raises(ValueError, match="is not pinned"):
        tess.tessdata_dir("klingon", "best", download=False, strict=True)
    with pytest.raises(FileNotFoundError):                   # not in this (empty) cache, and no download
        tess.tessdata_dir("eng", "best", download=False)


def test_a_line_crop_is_white_outside_the_polygon():
    image = np.zeros((50, 100), dtype=np.uint8)
    crop, dx, dy = crop_line(image, [[10, 10], [60, 10], [60, 20], [10, 20]], pad=2)
    assert (dx, dy) == (8, 8) and crop.shape == (14, 54) and crop[0, 0] == 255 and crop[5, 5] == 0


# each script preset's options (the catalog's tesseract-best-<script>) on the script sample it reads
# (linecaster.testing.scripts), with the largest share of its characters it may get wrong on the drawn page (NOTES.md
# has the measurement)
SCRIPT_PRESETS = [("script/Fraktur", False, "fraktur", 0.05), ("script/Greek", False, "greek", 0.05),
                  ("script/Cyrillic", False, "cyrillic", 0.1), ("script/Arabic", False, "arabic", 0.4),
                  ("script/Hebrew", False, "hebrew", 0.3), ("script/Devanagari", False, "devanagari", 0.05),
                  ("script/Thai", True, "thai", 0.1), ("script/Hangul", True, "korean", 0.2),
                  ("script/HanT_vert", True, "chinese", 0.15), ("script/Japanese_vert", True, "japanese", 0.1)]


def _distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


@pytest.mark.network
@pytest.mark.parametrize("lang, spaces, sample, most", SCRIPT_PRESETS)
def test_a_script_model_reads_its_script_in_its_direction(lang, spaces, sample, most):
    from linecaster.data import Annotator, Transcription
    from linecaster.testing.scripts import script_image, script_page

    try:
        image = np.asarray(script_image(sample))
    except LookupError as e:
        pytest.skip(str(e))
    truth = script_page(sample)
    t = Transcription(source=truth.source)
    a = t.add_annotator(Annotator(step="lines", name="sample"))
    t.classify(a, "", "direction", truth.direction(""))
    for ln in truth.ordered_lines():
        t.add_line(a, ln.id, ln.box)
    engine = TesseractRecognitionEngine(lang=lang, preserve_interword_spaces=spaces,
                                        weights=weights_of("tessdata-best"))
    engine.load()
    engine(image, t)
    pairs = [(truth.text_of(ref), t.text_of(out)) for ref, out in zip(truth.lines, t.lines)]
    assert sum(_distance(r, o) for r, o in pairs) / sum(len(r) for r, _ in pairs) <= most
    for ref, out in pairs:                               # words in reading order: those read right, in its order
        right = [w for w in out.split() if w in ref.split()]
        assert right == [w for w in ref.split() if w in right]
    assert any(w in pairs[0][0].split() for w in pairs[0][1].split())
