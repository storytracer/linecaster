"""Manifests (IIIF and METS) and http(s) images, against a small server
on loopback: manifests are reader entries distributed over tasks in turn (an item's pages in one task), images at full
size with the fallback on 404, failures counted, ``limit``/``skip`` before downloading; METS (plain and inside OAI-PMH)
with its image file groups and existing ALTO; item tables; METS packages with local files; the harvest stage's image,
OCR and manifest files and rows; ``http(s)://`` paths and derived page ids in the other readers."""
import io
import json
import pickle
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from linecaster.blocks.base.page import image_bytes, page_of
from linecaster.blocks.conversion import TranscriptionConverter
from linecaster.blocks.readers.images import ImageFolderReader, ImageParquetReader
from linecaster.blocks.readers.manifests import OCR_ORIGINAL, ManifestReader, manifest_item_id
from linecaster.blocks.readers.records import PageRecordReader
from linecaster.blocks.writers.images import ImageFilesWriter
from linecaster.blocks.writers.records import PageJsonlWriter
from linecaster.errors import PipelineConfigError

FAST = {"retry_wait_min": 0, "retry_wait_max": 0, "max_retries": 2, "trust_env": False}  # no proxy from the environment


ALTO = """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#"><Description><MeasurementUnit>pixel</MeasurementUnit>
</Description><Layout><Page ID="p1" WIDTH="6" HEIGHT="4" PHYSICAL_IMG_NR="1"><PrintSpace>
<TextBlock ID="b1" HPOS="0" VPOS="0" WIDTH="6" HEIGHT="4"><TextLine ID="l1" HPOS="0" VPOS="0" WIDTH="6" HEIGHT="2">
<String ID="s1" CONTENT="Flora" HPOS="0" VPOS="0" WIDTH="6" HEIGHT="2" WC="0.9"/></TextLine></TextBlock>
</PrintSpace></Page></Layout></alto>"""


def mets(base, pages, groups=("MAX", "DEFAULT"), href=None):
    """A DFG-style METS with MODS; ``pages`` are names in reading order (ORDER), written in reverse order."""
    href = href or (lambda group, n: f"{base}/{'max' if group == 'MAX' else 'direct'}/{n}.png")
    files = "".join(
        f'<mets:fileGrp USE="{g}">' + "".join(
            f'<mets:file ID="{g}_{n}" MIMETYPE="image/png"><mets:FLocat LOCTYPE="URL" xlink:href="{href(g, n)}"/>'
            f"</mets:file>" for n in pages) + "</mets:fileGrp>" for g in groups)
    files += '<mets:fileGrp USE="FULLTEXT">' + "".join(
        f'<mets:file ID="FT_{n}" MIMETYPE="text/xml"><mets:FLocat LOCTYPE="URL" xlink:href="{base}/ocr/{n}.xml"/>'
        "</mets:file>" for n in pages) + "</mets:fileGrp>"
    divs = "".join(
        f'<mets:div ID="phys_{n}" TYPE="page" ORDER="{i}" ORDERLABEL="[{i}]">'
        + "".join(f'<mets:fptr FILEID="{g}_{n}"/>' for g in (*groups, "FT")) + "</mets:div>"
        for i, n in reversed(list(enumerate(pages, 1))))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/" xmlns:mods="http://www.loc.gov/mods/v3"
  xmlns:xlink="http://www.w3.org/1999/xlink" OBJID="obj-1">
<mets:dmdSec ID="dmd1"><mets:mdWrap MDTYPE="MODS"><mets:xmlData><mods:mods>
<mods:titleInfo><mods:title>Flora der Schweiz</mods:title></mods:titleInfo>
<mods:originInfo><mods:dateIssued keyDate="yes">1840</mods:dateIssued></mods:originInfo>
<mods:identifier type="urn">urn:nbn:ch:test-1</mods:identifier>
<mods:recordInfo><mods:recordIdentifier>rec-1</mods:recordIdentifier></mods:recordInfo>
<mods:accessCondition type="use and reproduction">Public Domain Mark 1.0</mods:accessCondition>
</mods:mods></mets:xmlData></mets:mdWrap></mets:dmdSec>
<mets:fileSec>{files}</mets:fileSec>
<mets:structMap TYPE="LOGICAL"><mets:div ID="log1" TYPE="monograph" DMDID="dmd1"/></mets:structMap>
<mets:structMap TYPE="PHYSICAL"><mets:div ID="phys0" TYPE="physSequence">{divs}</mets:div></mets:structMap>
</mets:mets>"""


def oai(record: str) -> str:
    body = record.split("?>", 1)[1]
    return ('<?xml version="1.0" encoding="UTF-8"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
            "<GetRecord><record><header><identifier>oai:test:1</identifier></header>"
            f"<metadata>{body}</metadata></record></GetRecord></OAI-PMH>")


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
                m = state["manifests"][path]
                body, ctype = ((m.encode(), "application/xml") if isinstance(m, str)
                               else (json.dumps(m).encode(), "application/json"))
            elif parts[0] == "max" and parts[1] != "gone.png":
                body = png("red")
            elif parts[0] == "ocr" and parts[1] != "lost.xml":
                body, ctype = ALTO.encode(), "application/xml"
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
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    state["base"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()


def publish(server, item, manifest):
    server["manifests"][f"/{item}/manifest"] = manifest
    return f"{server['base']}/{item}/manifest"


def pages(reader, rank=0, world_size=1):
    return [page_of(d) for d in reader.run(rank=rank, world_size=world_size)]


@pytest.mark.parametrize("entry, item", [
    ("https://www.library.test/item/ltf90007547/manifest.json", "ltf90007547"),
    ("https://iiif.library.test/presentation/v3/b18035723", "b18035723"),
    ("https://www.example.org/i3f/v20/12345/manifest", "12345"),
    ("https://iiif.example.org/manifests/drs:427015", "drs_427015"),
    ("https://images.library.test/iiif/manifest/e32a277e.json?x=1", "e32a277e"),
    ("manifests/flora-1.json", "flora-1"),
])
def test_item_ids_from_manifest_entries(entry, item):
    assert manifest_item_id(entry) == item


def test_item_id_pattern():
    assert manifest_item_id("https://example.org/ark:/12148/bpt6k1/manifest.json", r"ark:/\d+/(\w+)") == "bpt6k1"
    with pytest.raises(PipelineConfigError, match="does not match"):
        manifest_item_id("https://example.org/x", r"ark:/(\w+)")


def test_manifests_are_entries_with_whole_items_per_task(server, tmp_path):
    base = server["base"]
    urls = [publish(server, "a", v2(base, "a", [("a1", True), ("gone", True), ("a3", False)])),
            publish(server, "b", v3(base, "b", ["b1", "b2"])),
            publish(server, "c", v2(base, "c", [("c1", True), ("lost", True), ("html", False)])),
            f"{base}/missing/manifest"]
    (tmp_path / "manifests.txt").write_text("\n".join(urls) + "\n")
    reader = lambda: ManifestReader(paths_file=str(tmp_path / "manifests.txt"),  # noqa: E731
                                        http={**FAST, "iiif_format": "png"})
    # pages go on as their images arrive: compared in page order
    task0, task1 = (sorted(pages(reader(), r, 2), key=lambda p: p.page_id) for r in (0, 1))
    assert [(p.item_id, p.page_id, p.sequence) for p in task0] == [
        ("a", "a_0001", 1), ("a", "a_0002", 2), ("a", "a_0003", 3), ("c", "c_0001", 1)]   # c: "lost" failed,
    #                                                                                     "html" is no image
    assert [p.page_id for p in task1] == ["b_0001", "b_0002"]                             # "missing" failed
    a1, gone, a3 = task0[:3]
    assert a1.image.uri.endswith("/iiif/a1/full/full/0/default.png")      # the image service, full size
    assert gone.image.uri == f"{base}/direct/gone.png"                      # the fallback after a 404
    assert a3.image.uri == f"{base}/direct/a3.png"                          # no service: its own URL
    assert task1[0].image.uri.endswith("/iiif/b1/full/max/0/default.png")   # Image API 3: max
    assert a1.metadata["manifest"] == {
        "format": "iiif", "url": urls[0], "id": f"{base}/a/manifest", "label": "Item a",
        "rights": "http://creativecommons.org/publicdomain/mark/1.0/", "required_statement": None,
        "identifiers": {}, "metadata": {}, "page_id": f"{base}/a/canvas/a1", "page_label": "p. a1",
        "request": f"{base}/iiif/a1/full/full/0/default.png"}
    assert a1.image.width == 6 and a1.image.format == "png"


@pytest.fixture
def png_format():
    return {**FAST, "iiif_format": "png"}


def test_limit_and_skip_count_pages_before_downloading(server, tmp_path, png_format):
    base = server["base"]
    urls = [publish(server, "a", v3(base, "a", ["a1", "a2", "a3"])), publish(server, "b", v3(base, "b", ["b1"]))]
    (tmp_path / "m.txt").write_text("\n".join(urls))
    got = pages(ManifestReader(paths_file=str(tmp_path / "m.txt"), skip=1, limit=2, http=png_format))
    assert sorted(p.page_id for p in got) == ["a_0002", "a_0003"]               # in the order they arrive
    images = sorted(r for r in server["requests"] if r.startswith("/iiif/"))   # fetched at once: any order
    assert images == ["/iiif/a2/full/max/0/default.png", "/iiif/a3/full/max/0/default.png"]


def test_manifest_files_in_a_folder(server, tmp_path, png_format):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "flora-1.json").write_text(json.dumps(v3(server["base"], "flora-1", ["f1"])))
    [page] = pages(ManifestReader(str(tmp_path / "m"), http=png_format))
    assert (page.item_id, page.page_id) == ("flora-1", "flora-1_0001")
    assert page.metadata["manifest"]["url"].endswith("m/flora-1.json")
    with pytest.raises(PipelineConfigError, match="No manifests"):
        list(ManifestReader(str(tmp_path / "empty-or-missing"), http=png_format).run())


def test_harvest_writes_item_folders_and_rows_that_point_at_the_copies(server, tmp_path, png_format):
    url = publish(server, "a", v3(server["base"], "a", ["a1", "a2"]))
    (tmp_path / "m.txt").write_text(url)
    docs = ManifestReader(paths_file=str(tmp_path / "m.txt"), http=png_format).run()
    with PageJsonlWriter(str(tmp_path / "pages")) as w:
        for doc in ImageFilesWriter(str(tmp_path / "images")).run(docs):
            w.write(doc, 0)
    assert sorted(p.name for p in (tmp_path / "images" / "a").iterdir()) == ["a_0001.png", "a_0002.png"]
    rows = [page_of(d) for d in PageRecordReader(str(tmp_path / "pages")).run()]
    assert rows[0].image.uri == str(tmp_path / "images" / "a" / "a_0001.png")
    assert rows[0].image.extra["source_uri"].endswith("/iiif/a1/full/max/0/default.png")
    assert rows[0].metadata["manifest"]["url"] == url
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
    from linecaster.runtime import run

    ap = run.parser(None)
    a = run.check(ap, ap.parse_args(["--manifests", f"{tmp_path}/m.txt", "OUT", "--rate-limit", "5/1",
                                      "--rate-limit", "200/60", "--iiif-format", "png"]))
    assert a.rate_limits == [(5, 1.0), (200, 60.0)]
    r = run.reader(a)
    assert isinstance(r, ManifestReader) and r.paths_file == f"{tmp_path}/m.txt"
    t = run.reader(run.check(ap, ap.parse_args(["--manifests", f"{tmp_path}/items.parquet", "OUT", "--manifest-key",
                                                "url", "--item-key", "id", "--existing-ocr"])))
    assert (t.glob_pattern, t.manifest_key, t.item_key, t.existing_ocr) == ("items.parquet", "url", "id", True)
    assert run.reader(run.check(ap, ap.parse_args(["--manifests", "m.txt.gz", "OUT"]))).paths_file == "m.txt.gz"
    assert r.http == {"iiif_format": "png", "rate_limits": [(5, 1.0), (200, 60.0)]}
    assert isinstance(run.reader(run.check(ap, ap.parse_args(["--pages", str(tmp_path), "OUT"]))), PageRecordReader)
    for argv in (["IMAGES", "--manifests", "m.txt", "OUT"], ["--manifests", "m.txt", "OUT", "--item-from-parent"],
                 ["--pages", "R", "OUT", "--limit", "3"], ["--manifests", "m.txt", "OUT", "--rate-limit", "5"],
                 ["IMAGES", "OUT", "--existing-ocr"], ["--manifests", "m.txt", "OUT", "--item-key", "id"]):
        with pytest.raises(SystemExit):
            run.check(ap, ap.parse_args(argv))


def test_mets_pages_in_order_with_file_groups_and_existing_alto(server, tmp_path):
    base = server["base"]
    url = publish(server, "flora", mets(base, ["f1", "gone", "lost"]))
    (tmp_path / "m.txt").write_text(url)
    reader = ManifestReader(paths_file=str(tmp_path / "m.txt"), existing_ocr=True, http=FAST)
    docs = list(reader.run())
    assert [m.metadata for d in docs for m in d.media[1:]] == [{"format": "alto"}, {"format": "alto"}]
    assert all(OCR_ORIGINAL not in page_of(d).transcriptions for d in docs)       # the reader only fetches the file
    got = [page_of(d) for d in TranscriptionConverter().run(iter(docs))]
    assert [(p.page_id, p.sequence) for p in got] == [("flora_0001", 1), ("flora_0002", 2), ("flora_0003", 3)]
    f1, gone, lost = got
    assert f1.image.uri == f"{base}/max/f1.png"                     # MAX first
    assert gone.image.uri == f"{base}/direct/gone.png"              # DEFAULT after MAX's 404
    meta = f1.metadata["manifest"]
    assert (meta["format"], meta["id"], meta["label"], meta["rights"]) == (
        "mets", "rec-1", "Flora der Schweiz", "Public Domain Mark 1.0")
    assert meta["identifiers"]["urn"] == "urn:nbn:ch:test-1" and meta["metadata"]["date"] == "1840"
    assert (meta["page_id"], meta["page_label"]) == ("phys_f1", "[1]")
    t = f1.transcriptions[OCR_ORIGINAL]
    assert t.text == "Flora" and (t.source.kind, t.source.format) == ("converted", "alto")
    assert t.source.uri == f"{base}/ocr/f1.xml" and t.source.image_sha256 == f1.image.sha256
    assert OCR_ORIGINAL not in lost.transcriptions                  # its ALTO failed; the page stays


def collection(base, name, members):
    return {"@context": "http://iiif.io/api/presentation/3/context.json", "id": f"{base}/{name}/manifest",
            "type": "Collection", "label": {"en": [name]},
            "items": [{"id": url, "type": kind, "label": {"none": [url]}} for kind, url in members]}


def test_a_iiif_collection_is_read_as_its_manifests(server, tmp_path):
    base = server["base"]
    a, b = publish(server, "a1", v3(base, "a1", ["f1"])), publish(server, "b2", v3(base, "b2", ["f1", "f2"]))
    top = publish(server, "flora", collection(base, "flora", [("Manifest", a), ("Manifest", b)]))
    (tmp_path / "m.txt").write_text(top)
    reader = ManifestReader(paths_file=str(tmp_path / "m.txt"), http={**FAST, "iiif_format": "png"},
                            manifest_folder=str(tmp_path / "manifests"))
    got = sorted(pages(reader), key=lambda p: p.page_id)                  # in the order they arrive
    assert [(p.item_id, p.page_id) for p in got] == [("a1", "a1_0001"), ("b2", "b2_0001"), ("b2", "b2_0002")]
    assert got[1].metadata["manifest"]["url"] == b and reader.stats["collections"].total == 1
    assert sorted(f.name for f in (tmp_path / "manifests").iterdir()) == ["a1.json", "b2.json"]


@pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="one level of IIIF Collections so far")
def test_a_collection_of_collections_is_read_as_their_manifests(server, tmp_path):
    base = server["base"]
    a = publish(server, "a1", v3(base, "a1", ["f1"]))
    sub = publish(server, "sub", collection(base, "sub", [("Manifest", a)]))
    top = publish(server, "top", collection(base, "top", [("Collection", sub)]))
    (tmp_path / "m.txt").write_text(top)
    assert [p.item_id for p in pages(ManifestReader(paths_file=str(tmp_path / "m.txt"), http=FAST))] == ["a1"]


def test_mets_inside_oai_pmh_and_a_forced_format(server, tmp_path):
    url = publish(server, "rec", oai(mets(server["base"], ["f1"], groups=("DEFAULT",))))
    (tmp_path / "m.txt").write_text(url)
    [page] = pages(ManifestReader(paths_file=str(tmp_path / "m.txt"), manifest_format="mets", http=FAST))
    assert page.image.uri.endswith("/direct/f1.png") and page.metadata["manifest"]["format"] == "mets"
    with pytest.raises(PipelineConfigError, match="iiif or mets"):
        ManifestReader(paths_file=str(tmp_path / "m.txt"), manifest_format="alto")


def test_item_tables_name_items_and_carry_their_columns(server, tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    base = server["base"]
    urls = [publish(server, "x1", v3(base, "x1", ["a"])), publish(server, "x2", mets(base, ["b"]))]
    (tmp_path / "items").mkdir()
    pq.write_table(pa.table({"item_id": ["book/1", "book 2", "book-3"], "manifest_url": [*urls, None],
                             "title": ["Flora", "Fauna", "None"], "year": [1840, 1841, 1842]}),
                   tmp_path / "items" / "part-0.parquet")
    got = sorted(pages(ManifestReader(str(tmp_path / "items"), manifest_key="manifest_url", item_key="item_id",
                                      http={**FAST, "iiif_format": "png"})), key=lambda p: p.page_id)
    assert [(p.item_id, p.page_id) for p in got] == [("book_1", "book_1_0001"), ("book_2", "book_2_0001")]
    assert (got[0].metadata["title"], got[0].metadata["year"]) == ("Flora", 1840)
    assert [p.metadata["manifest"]["format"] for p in got] == ["iiif", "mets"]
    with pytest.raises(PipelineConfigError, match="manifest_key"):
        ManifestReader(str(tmp_path / "items"), item_key="item_id")


def test_one_item_table_is_divided_over_tasks_by_rows_with_whole_items(server, tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    base = server["base"]
    names = ["i1", "i2", "i3", "i4", "i5"]
    urls = [publish(server, n, v3(base, n, [f"{n}a", f"{n}b"])) for n in names]
    (tmp_path / "items").mkdir()
    pq.write_table(pa.table({"item_id": names, "manifest_url": urls}), tmp_path / "items" / "part-0.parquet",
                   row_group_size=2)
    reader = lambda: ManifestReader(str(tmp_path / "items"), manifest_key="manifest_url",  # noqa: E731
                                    item_key="item_id", http={**FAST, "iiif_format": "png"})
    tasks = [sorted(p.page_id for p in pages(reader(), r, 2)) for r in range(2)]        # in the order they arrive
    assert tasks == [["i1_0001", "i1_0002", "i2_0001", "i2_0002"],
                     ["i3_0001", "i3_0002", "i4_0001", "i4_0002", "i5_0001", "i5_0002"]]
    assert reader().auto_tasks() == 1                                      # 5 items: ITEMS_PER_TASK
    one_each = ManifestReader(str(tmp_path / "items"), manifest_key="manifest_url", item_key="item_id",
                              task_per_item=True)
    assert one_each.auto_tasks() == 5                                     # harvest.py: one item per task


def test_a_manifests_images_already_written_are_reused(server, tmp_path):
    from linecaster.blocks.readers.existing import is_reused

    base = server["base"]
    url = publish(server, "r", v3(base, "r", ["r1", "r2"]))
    (tmp_path / "manifests.txt").write_text(url + "\n")
    (tmp_path / "images" / "r").mkdir(parents=True)
    from linecaster.testing import sample_png

    (tmp_path / "images" / "r" / "r_0001.png").write_bytes(sample_png())
    reader = ManifestReader(paths_file=str(tmp_path / "manifests.txt"), http={**FAST, "iiif_format": "png"},
                            reuse_folder=str(tmp_path / "images"))
    docs = sorted(reader.run(), key=lambda d: d.id)
    assert [(d.id, is_reused(d)) for d in docs] == [("r_0001", True), ("r_0002", False)]
    assert page_of(docs[0]).metadata["manifest"]["page_label"] is not None      # the manifest's data, as fetched
    assert page_of(docs[0]).image.sha256 is not None                          # read back: a complete record
    assert ManifestReader(paths_file=str(tmp_path / "manifests.txt"), existing_ocr=True,
                          reuse_folder=str(tmp_path / "images"))._existing is None   # its OCR would be missing


def test_a_mets_package_with_local_files(tmp_path):
    """Files next to the METS document, linked by relative paths: read from the folder, no HTTP."""
    pkg = tmp_path / "pkg" / "b1"
    (pkg / "img").mkdir(parents=True)
    (pkg / "img" / "p1.png").write_bytes(png("green"))
    (pkg / "mets.xml").write_text(mets("unused", ["p1"], groups=("DEFAULT",),
                                       href=lambda g, n: f"img/{n}.png"))
    [page] = pages(ManifestReader(str(tmp_path / "pkg"), glob_pattern="**/mets.xml", http=FAST))
    assert (page.item_id, page.image.uri) == ("b1", str(pkg / "img" / "p1.png"))


def test_harvest_saves_manifests_and_ocr_files(server, tmp_path):
    url = publish(server, "flora", mets(server["base"], ["f1"]))
    (tmp_path / "m.txt").write_text(url)
    docs = TranscriptionConverter().run(ManifestReader(paths_file=str(tmp_path / "m.txt"), existing_ocr=True,
                                                       manifest_folder=str(tmp_path / "manifests"), http=FAST).run())
    [doc] = list(ImageFilesWriter(str(tmp_path / "images"), ocr_folder=str(tmp_path / "ocr")).run(docs))
    assert (tmp_path / "manifests" / "flora.xml").read_text().startswith("<?xml")
    assert (tmp_path / "ocr" / "flora" / "flora_0001.xml").read_text() == ALTO
    t = page_of(doc).transcriptions[OCR_ORIGINAL]
    assert t.source.extra["file"] == str(tmp_path / "ocr" / "flora" / "flora_0001.xml")
    assert t.source.uri.endswith("/ocr/f1.xml")


def test_page_tables_without_page_ids(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    (tmp_path / "data").mkdir()
    pq.write_table(pa.table({"item": ["b1", "b1"], "page": [2, 1], "image": [png("red"), png("blue")]}),
                   tmp_path / "data" / "part-0.parquet")
    got = [page_of(d) for d in ImageParquetReader(str(tmp_path / "data"), item_key="item", sequence_key="page").run()]
    assert [(p.page_id, p.sequence) for p in got] == [("b1_0002", 2), ("b1_0001", 1)]
    with pytest.raises(PipelineConfigError, match="no page id column"):
        list(ImageParquetReader(str(tmp_path / "data"), item_key="item").run())


# ---------------------------------------------------------------------------- --reuse-from: earlier harvests' folders

def harvest_into(reader, out):
    """A page harvest as ``harvest.py`` runs it: the images into ``out/images``, the page records into ``out/pages``."""
    docs = list(ImageFilesWriter(str(out / "images")).run(reader.run()))
    with PageJsonlWriter(str(out / "pages")) as w:
        for doc in docs:
            w.write(doc, 0)
    return docs


def page_table(folder, rows):
    """A page table: (id, item, image URL) per row."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    folder.mkdir(parents=True)
    ids, items, urls = (list(c) for c in zip(*rows))
    pq.write_table(pa.table({"id": ids, "item": items, "image": urls}), folder / "p.parquet")
    return str(folder)


def test_a_page_table_reads_earlier_harvests_copies_by_url(server, tmp_path):
    """An image URL the earlier harvest fetched is read from its copy there (under its new item and page id), its
    sha256 checked, and written into the new folder with ``reused_from``; the rest is fetched."""
    from linecaster.blocks.readers.earlier import INDEX, build_index

    base = server["base"]
    first = page_table(tmp_path / "t1", [("p1", "A", f"{base}/direct/p1.png"), ("p2", "A", f"{base}/direct/p2.png")])
    harvest_into(ImageParquetReader(first, item_key="item", http=FAST), tmp_path / "v1")
    server["requests"].clear()
    second = page_table(tmp_path / "t2", [("q1", "B", f"{base}/direct/p1.png"), ("q3", "B", f"{base}/direct/p3.png")])
    out = tmp_path / "v2"
    assert build_index([str(tmp_path / "v1")], str(out / INDEX)) == 2
    reader = ImageParquetReader(second, item_key="item", http=FAST, reuse_index=str(out / INDEX))
    docs = harvest_into(reader, out)
    assert server["requests"] == ["/direct/p3.png"]
    assert (out / "images" / "B" / "q1.png").read_bytes() == (tmp_path / "v1" / "images" / "A" / "p1.png").read_bytes()
    extra = page_of(next(d for d in docs if d.id == "q1")).image.extra
    assert extra["reused_from"] == str(tmp_path / "v1") and extra["reused_from_uri"].endswith("v1/images/A/p1.png")
    assert extra["source_uri"] == f"{base}/direct/p1.png" and "reused" not in extra
    assert "reused_from" not in page_of(next(d for d in docs if d.id == "q3")).image.extra
    assert reader.stats["reused_from"].total == 1


def test_a_manifest_harvest_reads_earlier_harvests_copies_by_url(server, tmp_path, png_format):
    from linecaster.blocks.readers.earlier import INDEX, build_index

    base = server["base"]
    (tmp_path / "m1.txt").write_text(publish(server, "a", v3(base, "a", ["a1", "a2"])))
    harvest_into(ManifestReader(paths_file=str(tmp_path / "m1.txt"), http=png_format), tmp_path / "v1")
    server["requests"].clear()
    (tmp_path / "m2.txt").write_text(publish(server, "b", v3(base, "b", ["a1", "b3"])))   # a1's image, a new one
    out = tmp_path / "v2"
    build_index([str(tmp_path / "v1")], str(out / INDEX))
    docs = harvest_into(ManifestReader(paths_file=str(tmp_path / "m2.txt"), http=png_format,
                                       reuse_index=str(out / INDEX)), out)
    images = [r for r in server["requests"] if not r.endswith("/manifest")]
    assert images == ["/iiif/b3/full/max/0/default.png"]
    assert page_of(next(d for d in docs if d.id == "b_0001")).image.extra["reused_from"] == str(tmp_path / "v1")
    assert (out / "images" / "b" / "b_0001.png").exists() and (out / "images" / "b" / "b_0002.png").exists()


def test_the_newest_earlier_folder_wins_and_a_copy_that_differs_is_fetched(server, tmp_path):
    from linecaster.blocks.readers.earlier import INDEX, build_index

    base = server["base"]
    url = f"{base}/direct/x.png"
    for name, created in (("old", "2026-10-01T00:00:00Z"), ("new", "2026-11-01T00:00:00Z")):
        harvest_into(ImageParquetReader(page_table(tmp_path / f"t-{name}", [("x", "I", url)]), item_key="item",
                                        http=FAST), tmp_path / name)
        (tmp_path / name / "run.yaml").write_text(f"created: '{created}'\n")
    (tmp_path / "new" / "images" / "I" / "x.png").write_bytes(png("green"))     # no longer what new's record says
    out = tmp_path / "out"
    build_index([str(tmp_path / "new"), str(tmp_path / "old")], str(out / INDEX))
    server["requests"].clear()
    reader = ImageParquetReader(page_table(tmp_path / "t", [("x", "I", url)]), item_key="item", http=FAST,
                                reuse_index=str(out / INDEX))
    harvest_into(reader, out)
    assert server["requests"] == [url.split(base)[1]] and reader.stats["reuse_from_mismatch"].total == 1
    (tmp_path / "new" / "images" / "I" / "x.png").write_bytes((tmp_path / "old" / "images" / "I" / "x.png").read_bytes())
    server["requests"].clear()
    reader = ImageParquetReader(page_table(tmp_path / "t3", [("x", "I", url)]), item_key="item", http=FAST,
                                reuse_index=str(out / INDEX))
    [doc] = harvest_into(reader, tmp_path / "out3")
    assert server["requests"] == [] and page_of(doc).image.extra["reused_from"] == str(tmp_path / "new")


def test_reuse_and_reuse_from_together_for_page_images(server, tmp_path):
    """OUT's own copy first (not written again), then an earlier folder's (written), then a fetch."""
    from linecaster.blocks.readers.earlier import INDEX, build_index
    from linecaster.blocks.readers.existing import is_reused

    base = server["base"]
    rows = [("r1", "R", f"{base}/direct/r1.png"), ("r2", "R", f"{base}/direct/r2.png"),
            ("r3", "R", f"{base}/direct/r3.png")]
    harvest_into(ImageParquetReader(page_table(tmp_path / "t1", rows[:2]), item_key="item", http=FAST),
                 tmp_path / "v1")
    out = tmp_path / "out"
    (out / "images" / "R").mkdir(parents=True)
    (out / "images" / "R" / "r1.png").write_bytes(png("red"))
    stamp = (out / "images" / "R" / "r1.png").stat().st_mtime_ns
    build_index([str(tmp_path / "v1")], str(out / INDEX))
    server["requests"].clear()
    docs = harvest_into(ImageParquetReader(page_table(tmp_path / "t2", rows), item_key="item", http=FAST,
                                           reuse_folder=str(out / "images"), reuse_index=str(out / INDEX)), out)
    by = {d.id: d for d in docs}
    assert is_reused(by["r1"]) and (out / "images" / "R" / "r1.png").stat().st_mtime_ns == stamp
    assert page_of(by["r2"]).image.extra["reused_from"] == str(tmp_path / "v1")
    assert server["requests"] == ["/direct/r3.png"]


def test_a_tasks_lookup_reads_only_the_index_row_groups_its_urls_fall_in(tmp_path, monkeypatch):
    import pyarrow.parquet as pq

    from linecaster.blocks.readers import earlier

    folder = tmp_path / "v1"
    (folder / "pages").mkdir(parents=True)
    lines = [json.dumps({"id": f"p{i:03d}", "page": {"page_id": f"p{i:03d}", "item_id": "I", "image": {
        "uri": f"/elsewhere/v1/images/I/p{i:03d}.png", "sha256": f"{i:064x}",
        "extra": {"source_uri": f"https://images.library.test/{i:03d}.png"}}}}) for i in range(100)]
    lines.append(json.dumps({"id": "bad", "errors": [{"error": "x"}], "page": {"page_id": "bad", "image": {
        "uri": "/x/bad.png", "sha256": "0" * 64, "extra": {"source_uri": "https://images.library.test/bad.png"}}}}))
    import gzip

    with gzip.open(folder / "pages" / "00000.jsonl.gz", "wt") as f:
        f.write("\n".join(lines) + "\n")
    monkeypatch.setattr(earlier, "ROW_GROUP", 10)
    index = str(tmp_path / "index.parquet")
    assert earlier.build_index([str(folder)], index) == 100                      # the failed page is left out
    read = []
    original = pq.ParquetFile.read_row_group
    monkeypatch.setattr(pq.ParquetFile, "read_row_group", lambda self, i, **kw: read.append(i) or original(self, i, **kw))
    found = earlier.EarlierImages(index)
    assert found.lookup([f"https://images.library.test/{i:03d}.png" for i in (41, 43, 47)]) == 3
    assert read == [4]                                                       # one row group of ten
    assert found._found["https://images.library.test/043.png"] == (str(folder), "I/p043.png", f"{43:064x}")
