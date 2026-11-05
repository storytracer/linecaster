"""Robustness and provenance (docs/reference/pipelines.md): warm-up, per-page failures with rejects and an error
budget, on CPU with fake engines."""
import gzip
import io
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from linecaster.backends import InProcess
from linecaster.blocks.base.page import new_page_document, page_of
from linecaster.blocks.layout import SingleRegionLayout
from linecaster.blocks.lines import LineAssigner, LineDetector
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.recognition import LineRecognizer
from linecaster.blocks.writers import PageJsonlWriter
from linecaster.data import Line
from linecaster.errors import PageError
from linecaster.runtime.builder import build, run_pages, run_plan
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
    """Every line's text; a page whose width is in ``fail_widths`` raises."""

    step, name = "recognition", "text"

    def __init__(self, fail_widths=(), **kwargs):
        self.fail_widths = tuple(fail_widths)

    def load(self):
        EVENTS.append(("load", "recognition"))

    def __call__(self, image, t, **params):
        h, w = image.shape[:2]
        EVENTS.append(("read", w))
        if w in self.fail_widths:
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
    assert [e for e in EVENTS if e[0] == "load"] == [("load", "recognition"), ("load", "lines")]
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


# ------------------------------------------------------------------------------------------------ per-page failures

class FailingLines(SlowLines):
    """No lines for a page 50 wide: it raises."""

    LOAD_SECONDS = 0

    def __call__(self, image, t, **params):
        if image.shape[1] == 50:
            raise ValueError("no lines found")
        return super().__call__(image, t, **params)


def test_a_failing_page_carries_its_error_and_the_others_are_unaffected():
    out = run_pages(_modular(fail_widths=(50,)), [_doc("p1"), _doc("p2", 50), _doc("p3", 60)])
    assert [d.id for d in out] == ["p1", "p2", "p3"]
    assert out[1].metadata["errors"] == [{"block": "LineRecognizer", "step": "recognition", "preset": None,
                                          "type": "RuntimeError", "error": "cannot read a page 50 wide"}]
    for d in (out[0], out[2]):
        assert not d.metadata.get("errors")
        assert [ln.text for ln in page_of(d).transcriptions["ocr_new"].lines] == ["line 0", "line 1"]


def test_later_model_blocks_pass_a_failed_page_by():
    blocks = [SingleRegionLayout(), LineDetector(InProcess("test_robustness:FailingLines")), LineAssigner(),
              LineRecognizer(InProcess("test_robustness:Text"))]
    out = run_pages(blocks, [_doc("p1"), _doc("p2", 50)])
    assert out[1].metadata["errors"][0]["error"] == "no lines found"
    assert [e for e in EVENTS if e[0] == "read"] == [("read", 40)]       # the recognizer never saw p2
    assert blocks[3].stats["skipped_after_error"].total == 1 and blocks[1].stats["errors"].total == 1


def test_failed_pages_leave_at_once():
    """A page an earlier block failed on comes out of a model block before the next page goes in."""
    out_first = threading.Event()
    failed = _doc("failed")
    failed.metadata["errors"] = [{"block": "X", "type": "RuntimeError", "error": "earlier"}]

    def pages():
        yield failed
        assert out_first.wait(5), "the failed page was held back"
        yield _doc("p2")

    block = LineRecognizer(InProcess("test_robustness:Text"))
    seen = []
    for d in block.run(pages()):
        seen.append(d.id)
        out_first.set()
    assert seen == ["failed", "p2"]


def test_the_error_budget_fails_the_task(monkeypatch):
    from linecaster.blocks.base import page as base_page

    # judged from the ERROR_GRACE-th page on: when the 3rd page comes, 1 error is more than 1 % of 3 pages
    monkeypatch.setattr(base_page, "ERROR_GRACE", 3)
    with pytest.raises(PageError, match="1 of 3 pages failed") as e:
        run_pages(_modular(fail_widths=(50, 60)), [_doc("p1"), _doc("p2", 50), _doc("p3", 60)])
    assert e.value.block == "LineRecognizer" and isinstance(e.value.__cause__, RuntimeError)
    # a budget given to the builder
    blocks = _modular(fail_widths=(50, 60))
    plan = build([ImageFolderReader("x"), *blocks], max_page_errors=0.5)
    assert blocks[3].max_page_errors == 0.5 and plan.problems == []
    blocks[3].max_page_errors = None                    # no limit
    assert len(run_pages(blocks, [_doc("p1"), _doc("p2", 50), _doc("p3", 60)])) == 3
    # fewer pages than ERROR_GRACE: too few to judge
    monkeypatch.setattr(base_page, "ERROR_GRACE", 100)
    assert len(run_pages(_modular(fail_widths=(50, 60)), [_doc("p1"), _doc("p2", 50), _doc("p3", 60)])) == 3


def _rows(folder: Path) -> dict:
    out = {}
    for f in sorted(folder.rglob("*.jsonl.gz")):
        for line in gzip.open(f, "rt"):
            row = json.loads(line)
            out[row["id"]] = row
    return out


def test_failed_pages_are_written_to_rejects_and_kept_in_the_page_records(tmp_path: Path):
    for k, w in enumerate((40, 50, 60)):
        Image.new("RGB", (w, 30), "white").save(tmp_path / f"p{k + 1}.png")
    out = tmp_path / "out"
    plan = build([ImageFolderReader(str(tmp_path), glob_pattern="*.png"), *_modular(fail_widths=(50,)),
                  PageJsonlWriter(str(out / "pages"))], run_folder=str(out))
    assert [type(b).__name__ for b in plan.blocks][-2:] == ["RejectWriter", "PageJsonlWriter"]
    run_plan(plan)
    rejects = [json.loads(x) for x in (out / "rejects" / "00000.jsonl").read_text().splitlines()]
    assert rejects == [{"key": "p2", "field": "recognition", "error": "cannot read a page 50 wide", "raw_value": None,
                        "block": "LineRecognizer", "step": "recognition", "preset": None, "type": "RuntimeError"}]
    records = _rows(out / "pages")
    assert sorted(records) == ["p1", "p2", "p3"] and records["p2"]["errors"][0]["type"] == "RuntimeError"


# ------------------------------------------------------------------------------------------------ secrets

def test_an_env_var_is_never_pickled_with_its_value(monkeypatch):
    import pickle

    import dill
    import saturate

    from linecaster.backends import Served
    from linecaster.errors import PipelineConfigError
    from linecaster.runtime.secrets import EnvVar

    monkeypatch.setenv("LC_TEST_KEY", "s3cret-value")
    monkeypatch.setenv("LC_TEST_TOKEN", "t0ken-value")
    backend = Served("https://api.example.org/v1", model="m", api_key=EnvVar("LC_TEST_KEY"),
                     headers={"X-Team": "ocr", "X-Token": EnvVar("LC_TEST_TOKEN")})
    block = LineRecognizer(backend)
    for blob in (pickle.dumps(block), dill.dumps(block), dill.dumps([block])):
        assert b"s3cret-value" not in blob and b"t0ken-value" not in blob and b"LC_TEST_KEY" in blob
    again = pickle.loads(pickle.dumps(block))
    assert again.backend.api_key == EnvVar("LC_TEST_KEY")
    assert again.backend.request_headers() == {"X-Team": "ocr", "X-Token": "t0ken-value",
                                               "Authorization": "Bearer s3cret-value"}
    assert repr(EnvVar("LC_TEST_KEY")) == "EnvVar('LC_TEST_KEY')" and EnvVar("X").to_dict() == {"env": "X"}

    # the client gets the headers, read in the task
    seen = {}

    class Client:
        def __init__(self, endpoint, **kwargs):
            seen.update(kwargs, endpoint=endpoint)
            raise RuntimeError("no server here")

    monkeypatch.setattr(saturate, "AdaptiveClient", Client)
    with pytest.raises(RuntimeError, match="no server here"):
        list(block.run(iter([_doc()])))
    assert seen["endpoint"] == "https://api.example.org/v1"
    assert seen["headers"]["Authorization"] == "Bearer s3cret-value" and seen["headers"]["X-Team"] == "ocr"

    # a missing variable fails the warm-up; a key given as text is refused
    monkeypatch.delenv("LC_TEST_KEY")
    with pytest.raises(PipelineConfigError, match="LC_TEST_KEY is not set"):
        block.warm_up()
    with pytest.raises(PipelineConfigError, match="EnvVar"):
        Served("https://api.example.org/v1", model="m", api_key="s3cret-value")


# ------------------------------------------------------------------------------------------------ logging

def test_task_logs_are_json_lines_on_jobs(tmp_path: Path, monkeypatch):
    from datatrove.io import get_datafolder
    from datatrove.utils.logging import close_task_logger
    from loguru import logger

    from linecaster.runtime import logs

    folder = get_datafolder(str(tmp_path))
    monkeypatch.setenv(logs.JSON_ENV, "1")
    f = logs.add_task_logger(folder, 3)
    logger.warning("page {page_id} failed in {block}", page_id="b_0001", block="LineRecognizer")
    close_task_logger(f)
    lines = [json.loads(x) for x in (tmp_path / "logs" / "task_00003.log").read_text().splitlines()]
    last = lines[-1]["record"]
    assert last["message"] == "page b_0001 failed in LineRecognizer"
    assert last["extra"] == {"page_id": "b_0001", "block": "LineRecognizer"}
    # without the variable: datatrove's own text format
    monkeypatch.delenv(logs.JSON_ENV)
    f = logs.add_task_logger(folder, 4)
    logger.info("plain")
    close_task_logger(f)
    assert "| INFO" in (tmp_path / "logs" / "task_00004.log").read_text()
    logger.remove()
    logger.add(__import__("sys").stderr)


def test_job_dependencies_come_from_the_commit_they_install():
    """A Job's dependencies are read from the pipeline script as it is at the pinned commit, not from the checkout."""
    import subprocess

    from linecaster.runtime.jobs import ENGINE_SCRIPT, ROOT, at_commit

    first = subprocess.run(["git", "-C", str(ROOT), "rev-list", "--max-parents=0", "HEAD"], capture_output=True,
                           text=True).stdout.split()[0]
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert at_commit(ENGINE_SCRIPT, head) == subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{ENGINE_SCRIPT.relative_to(ROOT).as_posix()}"],
        capture_output=True, text=True).stdout
    with pytest.raises(FileNotFoundError):        # the modular script did not exist in the first commit
        at_commit(ROOT / "pipelines" / "no-such-script.py", first)
