"""Readers with a sample (``sample=SampleRule``, ``--sample``): the sample comes from the input's ids before any image
is read, it is the same whatever the task count, every sample page is read by one task, and nothing else is read;
the manifests a sample reads are saved and read back; the launch records the sample and writes ``OUT/sample.parquet``;
``linecaster sample`` writes the same file."""
import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from linecaster.blocks.base.page import page_of
from linecaster.blocks.readers.images import ImageFolderReader, ImageParquetReader
from linecaster.blocks.readers.manifests import SAMPLE_INDEX, ManifestReader
from linecaster.blocks.readers.records import PageRecordReader
from linecaster.catalog import yamlio
from linecaster.data.page import PAGE_SCHEMA
from linecaster.data.sample import SampleRule, sample_pairs
from linecaster.errors import PipelineConfigError
from linecaster.runtime import run
from linecaster.runtime.record import RunRecord
from linecaster.testing import sample_png

RULE = SampleRule(pages=12, per_item=3, seed=7)
FAST = {"retry_wait_min": 0, "retry_wait_max": 0, "max_retries": 1, "trust_env": False}
SIZES = [5, 1, 8, 3, 6, 2, 7, 4]                 # pages of items i0 ... i7


def read(make, world_size: int) -> list[tuple[str, str]]:
    """The (item, page) ids every task of ``world_size`` reads, each task from a fresh reader (as in a task)."""
    out = []
    for rank in range(world_size):
        docs = list(make().run(rank=rank, world_size=world_size))
        assert not any(d.metadata.get("errors") for d in docs)        # nothing outside the sample was read
        out += [(page_of(d).item_id or "", page_of(d).page_id) for d in docs]
    assert len(out) == len(set(out))                                  # every sample page in one task
    return sorted(out)


def expected(pairs, rule=RULE) -> list[tuple[str, str]]:
    return sorted((s.item_id, s.page_id) for s in sample_pairs(pairs, rule).selected)


# ------------------------------------------------------------------------------------------------ image files


def scans(tmp_path: Path) -> tuple[str, list]:
    """Item folders whose files are named alike in every item (0001.png ...)."""
    root, png, pairs = tmp_path / "scans", sample_png(80, 40, 1), []
    for i, n in enumerate(SIZES):
        (root / f"i{i}").mkdir(parents=True)
        for p in range(1, n + 1):
            (root / f"i{i}" / f"{p:04d}.png").write_bytes(png)
            pairs.append((f"i{i}", f"{p:04d}"))
    return str(root), pairs


@pytest.mark.parametrize("world_size", [1, 3, 7])
def test_image_files_give_the_same_sample_whatever_the_tasks(tmp_path, world_size):
    root, pairs = scans(tmp_path)
    make = lambda: ImageFolderReader(root, item_from_parent=True, sequence=True, sample=RULE)  # noqa: E731
    assert read(make, world_size) == expected(pairs)
    assert len(expected(pairs)) == 12


def test_image_files_outside_the_sample_are_never_opened(tmp_path):
    """A paths file may list files that do not exist: those outside the sample are not read."""
    root, pairs = scans(tmp_path)
    keep = set(expected(pairs))
    listed = [f"i{i}/{p:04d}.png" for i, n in enumerate(SIZES) for p in range(1, n + 1)]
    for path in listed:
        item, name = path.split("/")
        if (item, name[:-4]) not in keep:
            (Path(root) / path).unlink()
    (tmp_path / "paths.txt").write_text("\n".join(listed) + "\n")
    make = lambda: ImageFolderReader(root, paths_file=str(tmp_path / "paths.txt"), item_from_parent=True,  # noqa: E731
                                     sample=RULE)
    assert read(make, 3) == sorted(keep)


def test_sequence_stays_the_files_place_in_its_item(tmp_path):
    root, _ = scans(tmp_path)
    for d in ImageFolderReader(root, item_from_parent=True, sequence=True, sample=RULE).run():
        assert page_of(d).sequence == int(page_of(d).page_id)


def test_a_sample_and_max_pages_exclude_each_other(tmp_path):
    with pytest.raises(PipelineConfigError, match="exclude"):
        ImageFolderReader(str(tmp_path), sample=RULE, max_pages=3)


def test_items_and_per_item_need_items(tmp_path):
    with pytest.raises(PipelineConfigError, match="need items"):
        ImageFolderReader(str(tmp_path), sample=SampleRule(per_item=2))
    with pytest.raises(PipelineConfigError, match="need items"):
        ImageParquetReader(str(tmp_path), sample=SampleRule(items=2))
    ImageFolderReader(str(tmp_path), sample=SampleRule(pages=5))         # pages alone: one item ""


# ------------------------------------------------------------------------------------------------ Parquet


def table(tmp_path: Path, missing_outside: set | None = None) -> tuple[str, list]:
    """Two Parquet files of items' pages (row groups of 4), with image bytes, or for rows outside
    ``missing_outside`` a path to a file that does not exist."""
    folder, png = tmp_path / "data", sample_png(80, 40, 1)
    folder.mkdir()
    pairs, rows = [], []
    for i, n in enumerate(SIZES):
        for p in range(1, n + 1):
            pairs.append((f"i{i}", f"i{i}_{p:04d}"))
            image = (png if missing_outside is None or (f"i{i}", f"i{i}_{p:04d}") in missing_outside
                     else {"bytes": None, "path": "missing/none.png"})
            rows.append({"book": f"i{i}", "page": p, "image": image if isinstance(image, dict) else
                         {"bytes": image, "path": None}})
    half = len(rows) // 2
    for k, part in enumerate((rows[:half], rows[half:])):
        pq.write_table(pa.Table.from_pylist(part), folder / f"part-{k}.parquet", row_group_size=4)
    return str(folder), pairs


@pytest.mark.parametrize("world_size", [1, 3, 7])
def test_parquet_rows_outside_the_sample_are_never_read(tmp_path, world_size):
    pairs = manifest_pairs()
    folder, _ = table(tmp_path, missing_outside=set(expected(pairs)))
    make = lambda: ImageParquetReader(folder, item_key="book", sequence_key="page", sample=RULE)  # noqa: E731
    assert read(make, world_size) == expected(pairs)


def test_parquet_sample_reads_only_the_id_columns(tmp_path, monkeypatch):
    folder, pairs = table(tmp_path)
    seen = []
    original = pq.ParquetFile.read_row_group

    def spy(self, i, columns=None, **kw):
        seen.append(tuple(columns or ()))
        return original(self, i, columns=columns, **kw)

    monkeypatch.setattr(pq.ParquetFile, "read_row_group", spy)
    reader = ImageParquetReader(folder, item_key="book", sequence_key="page", sample=RULE)
    assert sorted((s.item_id, s.page_id) for s in reader.sampled().selected) == expected(pairs)
    assert seen and all(c and "image" not in c for c in seen)


def test_parquet_task_count_and_task_per_item_follow_the_sample(tmp_path):
    folder, pairs = table(tmp_path)
    rule = SampleRule(per_item=2)
    reader = ImageParquetReader(folder, item_key="book", sequence_key="page", sample=rule, task_per_item=True)
    assert reader.auto_tasks() == len(SIZES)
    per_task = [{page_of(d).item_id for d in reader.run(rank=r, world_size=len(SIZES))} for r in range(len(SIZES))]
    assert all(len(items) == 1 for items in per_task) and len(set().union(*per_task)) == len(SIZES)
    assert sum(reader.task_pages(r, 3) for r in range(3)) == len(expected(pairs, rule))


# ------------------------------------------------------------------------------------------------ manifests


@pytest.fixture
def library():
    """Manifests (IIIF 3, images without a service) and images on loopback; every request is counted."""
    state = {"manifests": {}, "requests": [], "png": sample_png(80, 40, 1)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["requests"].append(self.path)
            if self.path in state["manifests"]:
                body, ctype = json.dumps(state["manifests"][self.path]).encode(), "application/json"
            elif self.path.startswith("/img/"):
                body, ctype = state["png"], "image/png"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    base = state["base"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    for i, n in enumerate(SIZES):
        state["manifests"][f"/i{i}/manifest"] = {
            "@context": "http://iiif.io/api/presentation/3/context.json", "id": f"{base}/i{i}/manifest",
            "type": "Manifest", "label": {"none": [f"Item {i}"]}, "items": [
                {"id": f"{base}/i{i}/canvas/{p}", "type": "Canvas", "items": [{"type": "AnnotationPage", "items": [
                    {"type": "Annotation", "body": {"id": f"{base}/img/i{i}/{p}.png", "type": "Image"}}]}]}
                for p in range(1, n + 1)]}
    yield state
    httpd.shutdown()


def manifest_list(library, tmp_path: Path) -> str:
    path = tmp_path / "manifests.txt"
    path.write_text("".join(f"{library['base']}/i{i}/manifest\n" for i in range(len(SIZES))))
    return str(path)


def manifest_pairs():
    return [(f"i{i}", f"i{i}_{p:04d}") for i, n in enumerate(SIZES) for p in range(1, n + 1)]


@pytest.mark.parametrize("world_size", [1, 3])
def test_manifests_sample_requests_only_the_sample_images(library, tmp_path, world_size):
    paths = manifest_list(library, tmp_path)
    make = lambda: ManifestReader(paths_file=paths, http=FAST, sample=RULE)  # noqa: E731
    assert read(make, world_size) == expected(manifest_pairs())
    images = [r for r in library["requests"] if r.startswith("/img/")]
    assert len(images) == 12


def test_the_manifests_a_sample_read_are_saved_and_read_back(library, tmp_path):
    paths, saved = manifest_list(library, tmp_path), tmp_path / "out" / "manifests"
    reader = ManifestReader(paths_file=paths, http=FAST, sample=RULE, manifest_folder=str(saved))
    sample = reader.sampled()
    reached = sorted({s.item_id for s in sample.selected})
    index = [json.loads(line) for line in (saved / SAMPLE_INDEX).read_text().splitlines()]
    assert [d["item_id"] for d in index] == sorted(d["item_id"] for d in index)
    assert set(reached) <= {d["item_id"] for d in index} == {p.stem for p in saved.glob("*.json")}
    assert sample.listing["scope"] == "items" and sample.listing["manifests_read"] == len(index)
    manifests = len([r for r in library["requests"] if r.endswith("/manifest")])
    assert manifests == len(index) < len(SIZES)               # only as far as the rule reaches
    # the tasks read the copies, and a later launch computes the same sample from them, without a request
    library["requests"].clear()
    again = ManifestReader(paths_file=paths, http=FAST, sample=RULE, manifest_folder=str(saved))
    assert again.sampled().record() == sample.record()
    got = sorted((page_of(d).item_id, page_of(d).page_id) for r in range(2) for d in again.run(rank=r, world_size=2))
    assert got == expected(manifest_pairs())
    assert not [r for r in library["requests"] if r.endswith("/manifest")]
    meta = page_of(next(iter(again.run()))).metadata["manifest"]
    assert meta["url"].startswith(library["base"])            # the page's manifest is where it came from


def test_a_manifest_that_cannot_be_read_stops_the_sample(library, tmp_path):
    del library["manifests"]["/i3/manifest"]
    paths = manifest_list(library, tmp_path)
    with pytest.raises(PipelineConfigError, match="could not be read"):
        ManifestReader(paths_file=paths, http=FAST, sample=SampleRule(per_item=1)).sampled()


def test_item_tables_give_the_same_sample_whatever_the_tasks(library, tmp_path):
    pq.write_table(pa.table({"id": [f"i{i}" for i in range(len(SIZES))],
                             "link": [f"{library['base']}/i{i}/manifest" for i in range(len(SIZES))]}),
                   tmp_path / "items.parquet", row_group_size=3)
    make = lambda: ManifestReader(str(tmp_path), glob_pattern="items.parquet", manifest_key="link",  # noqa: E731
                                  item_key="id", http=FAST, sample=RULE)
    assert read(make, 1) == read(make, 3) == expected(manifest_pairs())


# ------------------------------------------------------------------------------------------------ page records


def records(tmp_path: Path, keep: set | None = None) -> tuple[str, list]:
    """Page records in three JSONL files; the image of a page outside ``keep`` does not exist."""
    folder, png = tmp_path / "pages", tmp_path / "img.png"
    folder.mkdir(parents=True)
    png.write_bytes(sample_png(80, 40, 1))
    pairs = manifest_pairs()
    for k in range(3):
        with gzip.open(folder / f"{k:05d}.jsonl.gz", "wt") as f:
            for item, page in pairs[k::3]:
                uri = str(png) if keep is None or (item, page) in keep else str(tmp_path / "gone.png")
                f.write(json.dumps({"schema": PAGE_SCHEMA, "id": page, "text": "", "page": {
                    "page_id": page, "item_id": item, "image": {"uri": uri}}}) + "\n")
    return str(folder), pairs


@pytest.mark.parametrize("world_size", [1, 3])
def test_page_records_outside_the_sample_are_not_passed_on_or_fetched(tmp_path, world_size):
    pairs = manifest_pairs()
    folder, _ = records(tmp_path, keep=set(expected(pairs)))
    make = lambda: PageRecordReader(folder, sample=RULE)  # noqa: E731
    assert read(make, world_size) == expected(pairs)


# ------------------------------------------------------------------------------------------------ the launch


def launch(tmp_path: Path, input_argv: list[str], out: str, *extra):
    argv = [*input_argv[:1], out, *input_argv[1:], "--sample", "12", "--sample-per-item", "3", "--sample-seed", "7", *extra]
    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(argv))
    a.has_engines = False
    run.run(a, [run.reader(a), run.pages(a)], __file__, argv=argv)
    return a


def test_a_run_records_its_sample_and_writes_the_same_file_whatever_the_tasks(tmp_path):
    root, pairs = scans(tmp_path)
    one, three = str(tmp_path / "one"), str(tmp_path / "three")
    launch(tmp_path, [root, "--item-from-parent"], one, "--tasks", "1")
    launch(tmp_path, [root, "--item-from-parent"], three, "--tasks", "3")
    a, b = (Path(o, "sample.parquet").read_bytes() for o in (one, three))
    assert a == b
    t = pq.read_table(Path(one, "sample.parquet"))
    assert sorted(zip(t["item_id"].to_pylist(), t["page_id"].to_pylist())) == expected(pairs)
    assert t["rank"].to_pylist() == list(range(1, 13))
    assert json.loads(t.schema.metadata[b"linecaster.sample"])["rule"] == "linecaster.sample/1"
    rec = yamlio.load(Path(one, "run.yaml").read_text())
    RunRecord.model_validate(rec)
    s = rec["sample"]
    assert (s["pages"], s["per_item"], s.get("items"), s["seed"]) == (12, 3, None, 7)
    assert s["listing"]["pages"] == len(pairs) and s["listing"]["scope"] == "pages"
    assert s["selected"]["pages"] == 12 and s["selected"]["sha256"].startswith("sha256:")
    written = []
    for f in Path(three, "pages").glob("*.jsonl.gz"):
        with gzip.open(f, "rt") as fh:
            written += [(json.loads(line)["page"]["item_id"], json.loads(line)["id"]) for line in fh]
    assert sorted(written) == expected(pairs)


def test_a_resume_with_another_sample_is_refused(tmp_path):
    root, _ = scans(tmp_path)
    out = str(tmp_path / "out")
    launch(tmp_path, [root, "--item-from-parent"], out)
    launch(tmp_path, [root, "--item-from-parent"], out)                      # the same sample: a resume
    with pytest.raises(PipelineConfigError, match="another sample"):
        launch(tmp_path, [root, "--item-from-parent"], out, "--sample-items", "2")


def test_the_sample_command_writes_the_file_a_run_writes(tmp_path, capsys):
    root, _ = scans(tmp_path)
    launch(tmp_path, [root, "--item-from-parent"], str(tmp_path / "run"))
    run.sample([root, str(tmp_path / "cmd"), "--item-from-parent", "--sample", "12", "--sample-per-item", "3",
                "--sample-seed", "7"])
    assert Path(tmp_path, "cmd", "sample.parquet").read_bytes() == Path(tmp_path, "run", "sample.parquet").read_bytes()
    assert json.loads(capsys.readouterr().out)["selected"]["pages"] == 12


@pytest.mark.parametrize("argv, message", [
    (["IN", "OUT", "--sample-seed", "3"], "--sample-seed orders a sample"),
    (["IN", "OUT", "--sample", "5", "--max-pages", "9"], "exclude each other"),
    (["IN", "OUT", "--sample", "0"], "at least 1"),
    (["--items", "t.parquet", "--item-key", "id", "OUT", "--sample", "5"], "a sample is of"),
])
def test_sample_options_that_do_not_fit_the_input_are_refused(argv, message, capsys):
    ap = run.parser(None)
    with pytest.raises(SystemExit):
        run.check(ap, ap.parse_args(argv))
    assert message in capsys.readouterr().err


def test_bind_reads_a_sample_of_its_page_records():
    from linecaster.pipelines import bind

    p = run.describe(bind, ["OUT1/pages", "OUT2", "--recipe", "item-texts", "--sample-items", "2"])
    reader = p.blocks[0]
    assert isinstance(reader, PageRecordReader) and reader.sample == SampleRule(items=2)
