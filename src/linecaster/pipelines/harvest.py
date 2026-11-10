r"""The harvest stage: items' page images (and, with --existing-ocr, the library's own OCR) from their manifests
(IIIF or METS; a folder, a list of links, or item tables with --manifest-key), or from http(s) image URLs in a page
table (--parquet), downloaded once into item folders, with page records that keep where everything came from. No
engine or GPU is needed; the transcribe stage then reads the page records without waiting on the libraries' servers.
With --items it fetches items' other remote files (resources: catalogue records, API JSON, manifests) as served,
from URL templates (--resource KIND=URL with {item}) or a resource table, into OUT/<kind>/<item>/<name>.<ext> with a
record each in OUT/resources/<rank>.jsonl.gz; --http-policy gives settings for every host and overrides per host
(rate limits, proxies or direct, retries, statuses that stop the run).

    uv run pipelines/harvest.py --manifests items.parquet --manifest-key manifest_url --item-key item_id OUT \
        --rate-limit 5/1 --existing-ocr
    uv run pipelines/harvest.py --items pages.parquet --item-key lccn OUT --http-policy http-policy.yaml \
        --resource marcxml=https://catalog.example.org/{item}/marcxml
    uv run pipelines/harvest.py --parquet pages.parquet --item-key book --sequence-key page --image-key url OUT \
        --rate-limit 150/60 --rate-limit 3/1
    uv run pipelines/harvest.py ... SMOKE --rate-limit 150/60 --rate-limit 3/1 --max-pages 2000     # a smoke test
    uv run pipelines/transcribe_modular.py --pages OUT/pages OUT2 --recipe ...                 # keeps the metadata
    uv run pipelines/transcribe_modular.py OUT/images OUT2 --item-from-parent --recipe ...   # or the plain folder

OUT/images/<item>/<page>.<ext> as the server sent them; with --existing-ocr OUT/ocr/<item>/<page>.xml|.html; the
manifests as fetched in OUT/manifests/<item>.json|.xml; page records in OUT/pages/<rank>.jsonl.gz (``image.uri`` the
copy, ``image.extra.source_uri`` the source, ``metadata.manifest`` the item's and page's manifest data, the
transcription ``ocr_original`` with the existing OCR).

Nothing needs sizing: --rate-limit holds per worker, and with it one worker runs the tasks (the run states what a
server sees before it starts). Each item is a task (a --parquet page table with --item-key: a run of rows with the
same item, whatever the files; --manifests: a manifest or a row of an item table; without --item-key tasks of about
1,000 pages), so an item is whole in its task and a rerun into the same OUT repeats at most the item each worker was
in (datatrove's resume is per task); with --reuse, its pages whose images are already in OUT/images are read from
there instead of fetched again (one listing of the item's folder; their records are complete and say
``image.extra.reused``); without it (the default) they are fetched again and their files overwritten. The
worker's requests ahead (manifests' pages and http(s) images alike) grow until the rate limits are kept busy, and the limits hold across its tasks. --tasks and --workers still override; with
--workers N a server sees N times --rate-limit, so give each worker its part. With --proxies the limits hold per
proxy instead, and the workers (of this run, and of other runs given the same --broker) share the proxies through the
broker (default OUT/logs/broker), each proxy used by one worker at a time and left out where it was blocked; each
worker holds a fair share of them (an HTTP policy's proxies: {per_worker: 1} for one each, or N). The run's workers
follow the available proxies (those not blocked and not held by another run): one per proxy up to one per CPU, with
1 or N one per proxy divided by N (not capped by the CPUs: the workers wait on the network), at most one per task
and at most 64 with OUT on object storage (s3://, gs://, hf://, ...), which it states before it starts. --max-pages N runs the first N pages of
the input in the same automatic tasks, a smoke test of the real setup (--limit counts per task, as in datatrove).
An outage of the server pauses the requests until it answers again; a book that fails anyway runs again on the next
launch, and --retry-failed also runs the finished books with failed pages again: with --reuse only their failed
pages are fetched (the others are read from OUT/images), without it every page of those books is fetched again.
``linecaster.runtime.run`` has the options every pipeline shares.
"""
from ..blocks.conversion import TranscriptionConverter
from ..blocks.writers.images import ImageFilesWriter
from ..blocks.writers.resources import ResourceFilesWriter, ResourceRecordWriter
from ..errors import PipelineConfigError
from ..runtime import run


def options(ap):
    ap.add_argument("--reuse", action="store_true",
                    help="before fetching an item, list its folder in OUT and read the files an earlier launch wrote "
                         "instead of fetching them again (one listing per item; off by default, since on some object "
                         "storage a listing is slow even for an empty folder)")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str) -> list:
    if a.images or a.pages:
        raise PipelineConfigError("harvest.py downloads: give --manifests, --parquet (with http(s) image URLs) or "
                                  "--items (resources)")
    out = a.out.rstrip("/")
    if a.items:                     # items' remote files as served: OUT/<kind>/<item>/<name>.<ext>, OUT/resources
        return [
            run.reader(a, reuse_folder=out if a.reuse else None),
            ResourceFilesWriter(out),
            ResourceRecordWriter(f"{out}/resources"),
        ]
    ocr = bool(a.manifests and a.existing_ocr)
    return [
        # one item per task: an item is whole in its task, and a task that fails costs one item; with --reuse,
        # images an earlier launch wrote are not fetched again (one listing of the item's folder per task)
        run.reader(a, manifest_folder=f"{out}/manifests" if a.manifests else None, task_per_item=True,
                   reuse_folder=f"{out}/images" if a.reuse else None),
        # the library's OCR file (a document media) read into ocr_original
        *([TranscriptionConverter()] if ocr else []),
        ImageFilesWriter(f"{out}/images", ocr_folder=f"{out}/ocr" if ocr else None),
        run.pages(a),
    ]


#: the pipeline's id (its docs page; ``launch.py`` finds scripts by it); no slots, so no recipes
PIPELINE = "harvest.v1"
