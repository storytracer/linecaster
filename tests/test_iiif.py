"""IIIF manifests and http(s) images through pybookget (``linecaster[pybookget]``), against a small IIIF server on
loopback: manifests are reader entries distributed over tasks in turn (an item's pages in one task), images at
full size through the image service with the fallback on 404, failures counted, ``limit``/``skip`` before
downloading; the harvest stage's image files and rows; ``http(s)://`` paths in the other readers."""
import io
import json
import pickle
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

pytest.importorskip("pybookget")

from linecaster.blocks.base import image_bytes, page_of  # noqa: E402
from linecaster.blocks.iiif import IIIFManifestReader, manifest_item_id  # noqa: E402
from linecaster.blocks.readers import ImageFolderReader, ImageParquetReader, PageRowReader  # noqa: E402
from linecaster.blocks.writers import ImageFilesWriter, PageJsonlWriter  # noqa: E402

FAST = {"retry_wait_min": 0, "retry_wait_max": 0, "max_retries": 2, "proxy": None}


def png(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (6, 4), color).save(buf, format="PNG")
    return buf.getvalue()


def v2(base, item, pages):
    """A v2 manifest; a page is (name, has_service)."""
    canvases = []
    for name, service in pages:
        resource = {"@id": f"{base}/direct/{name}.png"}
        if service:
            resource["service"] = {"@context": "http://iiif.io/api/image/2/context.json",
                                   "@id": f"{base}/iiif/{name}"}
        canvases.append({"@id": f"{base}/{item}/canvas/{name}", "label": f"p. {name}",
                         "images": [{"resource": resource}]})
    return {"@context": "http://iiif.io/api/presentation/2/context.json", "@id": f"{base}/{item}/manifest",
            "label": f"Item {item}", "license": "http://creativecommons.org/publicdomain/mark/1.0/",
            "sequences": [{"canvases": canvases}]}


def v3(base, item, names):
    return {"@context": "http://iiif.io/api/presentation/3/context.json", "id": f"{base}/{item}/manifest",
            "type": "Manifest", "label": {"none": [f"Item {item}"]}, "items": [
                {"id": f"{base}/{item}/canvas/{n}", "type": "Canvas", "label": {"none": [n]}, "items": [
                    {"type": "AnnotationPage", "items": [{"type": "Annotation", "body": {
                        "id": f"{base}/direct/{n}.png", "type": "Image",
                        "service": [{"id": f"{base}/iiif/{n}", "type": "ImageService3"}]}}]}]}
                for n in names]}


@pytest.fixture
def server():
    """A IIIF server on loopback. Images: ``/iiif/<name>/full/<size>/0/default.png`` (``gone`` only at its
    direct URL, ``lost`` nowhere) and ``/direct/<name>.png``; manifests under ``/<item>/manifest``."""
    state = {"manifests": {}, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path
            state["requests"].append(path)
            body, ctype = None, "image/png"
            parts = path.strip("/").split("/")
            if path in state["manifests"]:
                body, ctype = json.dumps(state["manifests"][path]).encode(), "application/json"
            elif parts[0] == "iiif" and len(parts) == 6 and parts[1] not in ("gone", "lost"):
                body = png("red" if parts[3] in ("full", "max") else "black")
            elif parts[0] == "direct" and parts[1] == "html.png":
                body, ctype = b"<html>busy</html>", "text/html"      # an error page sent with 200
            elif parts[0] == "direct" and parts[1] != "lost.png":
                body = png("blue")
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state["base"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()


def publish(server, item, manifest):
    server["manifests"][f"/{item}/manifest"] = manifest
    return f"{server['base']}/{item}/manifest"


def pages(reader, rank=0, world_size=1):
    return [page_of(d) for d in reader.run(rank=rank, world_size=world_size)]


@pytest.mark.parametrize("entry, item", [
    ("https://www.loc.gov/item/ltf90007547/manifest.json", "ltf90007547"),
    ("https://iiif.wellcomecollection.org/presentation/v3/b18035723", "b18035723"),
    ("https://www.e-rara.ch/i3f/v20/12345/manifest", "12345"),
    ("https://iiif.lib.harvard.edu/manifests/drs:427015", "drs_427015"),
    ("https://iiif.bodleian.ox.ac.uk/iiif/manifest/e32a277e.json?x=1", "e32a277e"),
    ("manifests/flora-1.json", "flora-1"),
])
def test_item_ids_from_manifest_entries(entry, item):
    assert manifest_item_id(entry) == item


def test_item_id_pattern():
    assert manifest_item_id("https://example.org/ark:/12148/bpt6k1/manifest.json", r"ark:/\d+/(\w+)") == "bpt6k1"
    with pytest.raises(ValueError, match="does not match"):
        manifest_item_id("https://example.org/x", r"ark:/(\w+)")


def test_manifests_are_entries_with_whole_items_per_task(server, tmp_path):
    base = server["base"]
    urls = [publish(server, "a", v2(base, "a", [("a1", True), ("gone", True), ("a3", False)])),
            publish(server, "b", v3(base, "b", ["b1", "b2"])),
            publish(server, "c", v2(base, "c", [("c1", True), ("lost", True), ("html", False)])),
            f"{base}/missing/manifest"]
    (tmp_path / "manifests.txt").write_text("\n".join(urls) + "\n")
    reader = lambda: IIIFManifestReader(paths_file=str(tmp_path / "manifests.txt"),  # noqa: E731
                                        http={**FAST, "iiif_format": "png"}, prefetch=2)
    task0, task1 = pages(reader(), 0, 2), pages(reader(), 1, 2)
    assert [(p.item_id, p.page_id, p.sequence) for p in task0] == [
        ("a", "a_0001", 1), ("a", "a_0002", 2), ("a", "a_0003", 3), ("c", "c_0001", 1)]   # c's "lost" failed, "html" is no image
    assert [p.page_id for p in task1] == ["b_0001", "b_0002"]                             # "missing" failed
    a1, gone, a3 = task0[:3]
    assert a1.image.uri.endswith("/iiif/a1/full/full/0/default.png")      # the image service, full size
    assert gone.image.uri == f"{base}/direct/gone.png"                      # the fallback after a 404
    assert a3.image.uri == f"{base}/direct/a3.png"                          # no service: its own URL
    assert task1[0].image.uri.endswith("/iiif/b1/full/max/0/default.png")   # Image API 3: max
    assert a1.metadata["iiif"] == {
        "manifest": urls[0], "label": "Item a", "rights": "http://creativecommons.org/publicdomain/mark/1.0/",
        "required_statement": None, "canvas": f"{base}/a/canvas/a1", "canvas_label": "p. a1",
        "request": f"{base}/iiif/a1/full/full/0/default.png"}
    assert a1.image.width == 6 and a1.image.format == "png"


@pytest.fixture
def png_format():
    return {**FAST, "iiif_format": "png"}


def test_limit_and_skip_count_pages_before_downloading(server, tmp_path, png_format):
    base = server["base"]
    urls = [publish(server, "a", v3(base, "a", ["a1", "a2", "a3"])), publish(server, "b", v3(base, "b", ["b1"]))]
    (tmp_path / "m.txt").write_text("\n".join(urls))
    got = pages(IIIFManifestReader(paths_file=str(tmp_path / "m.txt"), skip=1, limit=2, http=png_format))
    assert [p.page_id for p in got] == ["a_0002", "a_0003"]
    images = [r for r in server["requests"] if r.startswith("/iiif/")]
    assert images == ["/iiif/a2/full/max/0/default.png", "/iiif/a3/full/max/0/default.png"]


def test_manifest_files_in_a_folder(server, tmp_path, png_format):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "flora-1.json").write_text(json.dumps(v3(server["base"], "flora-1", ["f1"])))
    [page] = pages(IIIFManifestReader(str(tmp_path / "m"), http=png_format))
    assert (page.item_id, page.page_id) == ("flora-1", "flora-1_0001")
    assert page.metadata["iiif"]["manifest"].endswith("m/flora-1.json")
    with pytest.raises(RuntimeError, match="No manifests"):
        list(IIIFManifestReader(str(tmp_path / "empty-or-missing"), http=png_format).run())


def test_harvest_writes_item_folders_and_rows_that_point_at_the_copies(server, tmp_path, png_format):
    url = publish(server, "a", v3(server["base"], "a", ["a1", "a2"]))
    (tmp_path / "m.txt").write_text(url)
    docs = IIIFManifestReader(paths_file=str(tmp_path / "m.txt"), http=png_format).run()
    with PageJsonlWriter(str(tmp_path / "rows")) as w:
        for doc in ImageFilesWriter(str(tmp_path / "images")).run(docs):
            w.write(doc, 0)
    assert sorted(p.name for p in (tmp_path / "images" / "a").iterdir()) == ["a_0001.png", "a_0002.png"]
    rows = [page_of(d) for d in PageRowReader(str(tmp_path / "rows")).run()]
    assert rows[0].image.uri == str(tmp_path / "images" / "a" / "a_0001.png")
    assert rows[0].image.extra["source_uri"].endswith("/iiif/a1/full/max/0/default.png")
    assert rows[0].metadata["iiif"]["manifest"] == url
    folder = [page_of(d) for d in ImageFolderReader(str(tmp_path / "images"), item_from_parent=True).run()]
    assert [(p.item_id, p.page_id) for p in folder] == [("a", "a_0001"), ("a", "a_0002")]


def test_http_image_paths_in_parquet(server, tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    (tmp_path / "data").mkdir()
    pq.write_table(pa.table({"id": ["p1"], "image": [f"{server['base']}/direct/p1.png"]}),
                   tmp_path / "data" / "part-0.parquet")
    reader = ImageParquetReader(str(tmp_path / "data"), http=FAST)
    [doc] = list(reader.run())
    assert Image.open(io.BytesIO(image_bytes(doc))).getpixel((0, 0)) == (0, 0, 255)
    assert page_of(doc).image.uri == f"{server['base']}/direct/p1.png"
    pickle.dumps(reader)               # executors pickle the pipeline: the fetcher is left out


def test_run_options(tmp_path):
    from linecaster import run

    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(["--manifests", f"{tmp_path}/m.txt", "OUT", "--rate-limit", "5/1",
                                      "--rate-limit", "200/60", "--iiif-format", "png"]))
    assert a.rate_limits == [(5, 1.0), (200, 60.0)]
    r = run.reader(a)
    assert isinstance(r, IIIFManifestReader) and r.paths_file == f"{tmp_path}/m.txt"
    assert r.http == {"iiif_format": "png", "rate_limits": [(5, 1.0), (200, 60.0)]}
    assert isinstance(run.reader(run.check(ap, ap.parse_args(["--rows", str(tmp_path), "OUT"]))), PageRowReader)
    for argv in (["IMAGES", "--manifests", "m.txt", "OUT"], ["--manifests", "m.txt", "OUT", "--item-from-parent"],
                 ["--rows", "R", "OUT", "--limit", "3"], ["--manifests", "m.txt", "OUT", "--rate-limit", "5"]):
        with pytest.raises(SystemExit):
            run.check(ap, ap.parse_args(argv))
