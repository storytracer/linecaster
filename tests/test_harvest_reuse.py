"""The harvest pipeline (``linecaster.pipelines.harvest``): reusing images an earlier launch wrote is opt-in
(``--reuse``); by default an item's pages are fetched again without a listing of its folder."""
from linecaster.pipelines import harvest
from linecaster.runtime import run


def build(*extra):
    ap = run.parser(None)
    harvest.options(ap)
    a = run.check(ap, ap.parse_args(["--parquet", "pages.parquet", "--item-key", "item", "--image-key", "url",
                                     "OUT", *extra]))
    return harvest.pipeline(a, None)[0]


def test_reuse_is_off_by_default_and_on_with_the_flag():
    assert build().reuse_folder is None
    assert build("--reuse").reuse_folder == "OUT/images"
