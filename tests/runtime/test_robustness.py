"""Robustness and provenance (docs/reference/pipelines.md): warm-up, per-page failures with rejects and an error
budget, on CPU with fake engines."""
import io
import time

import pytest
from PIL import Image

from linecaster.backends import InProcess
from linecaster.blocks.base.page import new_page_document, page_of
from linecaster.blocks.layout import SingleRegionLayout
from linecaster.blocks.lines import LineAssigner, LineDetector
from linecaster.blocks.recognition import LineRecognizer
from linecaster.data import Line
from linecaster.runtime.builder import run_pages
from linecaster.runtime.observers import Observer

#: what the fake engines did, in order (reset per test)
EVENTS: list = []


class SlowLines:
    """Two lines; loading takes ``LOAD_SECONDS``."""

    step, name = "lines", "slow-lines"
    LOAD_SECONDS = 0.2

    def __init__(self, **kwargs):
        pass

    def load(self):
        EVENTS.append(("load", "lines"))
        time.sleep(self.LOAD_SECONDS)

    def __call__(self, image, t, **params):
        from linecaster.data.transcription import ModelInfo

        h, w = image.shape[:2]
        t.lines = [Line(id=f"l{i}", bbox=[0, y, w, h // 2]) for i, y in enumerate((0, h // 2))]
        t.model.append(ModelInfo(step="lines", name=self.name))
        return t


class Text:
    """Every line's text; ``fail`` names a page width whose page raises."""

    step, name = "recognition", "text"

    def __init__(self, fail_width: int | None = None, **kwargs):
        self.fail_width = fail_width

    def load(self):
        EVENTS.append(("load", "recognition"))

    def __call__(self, image, t, **params):
        h, w = image.shape[:2]
        if w == self.fail_width:
            raise RuntimeError(f"cannot read a page {w} wide")
        for i, ln in enumerate(t.lines):
            ln.text = f"line {i}"
        return t


@pytest.fixture(autouse=True)
def _events():
    EVENTS.clear()
    yield
    EVENTS.clear()


def _doc(page_id: str = "p1", w: int = 40):
    buf = io.BytesIO()
    Image.new("RGB", (w, 30), "white").save(buf, format="PNG")
    return new_page_document(page_id, buf.getvalue(), uri=f"{page_id}.png")


def _modular(**text):
    return [SingleRegionLayout(), LineDetector(InProcess("test_robustness:SlowLines")), LineAssigner(),
            LineRecognizer(InProcess("test_robustness:Text", **text))]


class WarmUps(Observer):
    def __init__(self):
        self.seen = []

    def on_warm_up(self, block, seconds):
        self.seen.append((type(block).__name__, seconds))


# ------------------------------------------------------------------------------------------------ warm-up

def test_warm_up_loads_before_the_first_page_and_is_its_own_stat():
    blocks = _modular()
    log = WarmUps()
    out = run_pages(blocks, [_doc("p1"), _doc("p2", 50)], observers=[log])
    # blocks warm up as the stream reaches them: the last one first; each engine loads once
    assert EVENTS == [("load", "recognition"), ("load", "lines")]
    assert [name for name, _ in log.seen] == ["LineRecognizer", "LineDetector"]
    lines = blocks[1]
    assert lines.stats["warm_up_seconds"].total >= SlowLines.LOAD_SECONDS
    # a page's measured seconds never include the loading
    for doc in out:
        assert page_of(doc).transcriptions["ocr_new"].model[0].measurements["seconds"] < SlowLines.LOAD_SECONDS
    # blocks without anything to load have no warm-up stat
    assert "warm_up_seconds" not in blocks[2].stats.stats


def test_warm_up_is_idempotent_and_its_failure_fails_the_task():
    b = InProcess("test_robustness:Text")
    b.warm_up()
    b.warm_up()
    assert EVENTS == [("load", "recognition")]
    broken = LineRecognizer(InProcess("test_robustness:NoSuchEngine"))
    with pytest.raises(AttributeError):
        run_pages([SingleRegionLayout(), LineDetector(InProcess("test_robustness:SlowLines")), LineAssigner(), broken],
                  [_doc()])
