"""``pipelines/harvest.py``: reusing images an earlier launch wrote is opt-in (``--reuse``); by default an item's
pages are fetched again without a listing of its folder."""
from pathlib import Path

from linecaster.runtime import run

HARVEST = Path(__file__).resolve().parents[1] / "pipelines" / "harvest.py"


def build(*extra):
    script = run.load_script(HARVEST)
    ap = run.parser(None)
    script.options(ap)
    a = run.check(ap, ap.parse_args(["--parquet", "pages.parquet", "--item-key", "item", "--image-key", "url",
                                     "OUT", *extra]))
    return script.pipeline(a, str(HARVEST))[0]


def test_reuse_is_off_by_default_and_on_with_the_flag():
    assert build().reuse_folder is None
    assert build("--reuse").reuse_folder == "OUT/images"
