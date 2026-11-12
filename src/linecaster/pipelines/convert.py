r"""Image conversion: page images (any format Pillow reads) converted to JPEG, JPEG 2000, PNG or WebP at full resolution
by an image preset (``--preset``, ``ImageConverter``), decoded and encoded on the machine's NVIDIA GPUs where it has
them and they support the format (``linecaster[nvimgcodec]``), else on the CPU. Images in OUT/images/<item>/<page>.<ext>, page
records (each image's size, hashes, decoder and encoder) in OUT/pages, failed pages in OUT/rejects.

    uv run pipelines/convert.py IMAGES OUT --preset webp-lossy-q80 --item-from-parent
    uv run pipelines/convert.py IMAGES OUT --preset jpeg-q90 --set image.quality=85
    uv run pipelines/convert.py OUT --pages OUT1/pages --preset jp2-lossless           # an earlier run's pages
    uv run pipelines/convert.py OUT --parquet pages.parquet --image-key path --item-key item --id-key page \
        --preset webp-lossy-q80                                  # a table of source paths and the ids they get
    ... --set image.accel=cpu                                    # never the GPU; =gpu: an error where it cannot

The presets (``linecaster models``, step ``image``): ``webp-lossy-q80``, ``jpeg-q90``, ``jp2-lossless``, ``png``,
``working-image`` (lossless WebP); ``--set image.OPTION=VALUE`` over a preset's options (``format``, ``quality``,
``lossless``, ``psnr``, ``method``, ``compress_level``, ``accel``). A page goes through two stages, decoding and
encoding, each with a window saturate's controller adapts to the throughput and the machine's memory (``--window``
fixes it); a GPU batches the decodes that arrive together. One worker process per GPU, or without a GPU (or with
image.accel=cpu) one per 16 CPUs, unless --workers says otherwise; with --on ray each task reserves its worker's share
of the CPUs (--cpus-per-task) and, where GPUs decode, one GPU; the image files are read in the stages, many at once, not by the reader. A run into the same
OUT resumes: finished tasks are skipped, and within a task an image whose file is there already is not converted
again (``--overwrite`` converts it again). Files are written under a temporary name and renamed when complete.
"""
from ..blocks.conversion.images import ImageConverter
from ..errors import PipelineConfigError
from ..runtime import run


def options(ap):
    ap.add_argument("--preset", help="the image preset: what to convert to (e.g. webp-lossy-q80; needed)")
    ap.add_argument("--set", action="append", default=[], metavar="STEP.OPTION=VALUE",
                    help="an engine option over the preset's, e.g. image.quality=85; repeatable")
    ap.add_argument("--overwrite", action="store_true", help="convert images whose file is there already again")
    ap.add_argument("--window", type=int, default=None, help="pages in flight per stage, fixed (default: adapted)")
    ap.add_argument("--max-window", type=int, default=None,
                    help="decoding and encoding: the adapted windows' upper bound per worker (default: twice the CPUs, "
                         "shared by the workers)")
    ap.add_argument("--max-io-window", type=int, default=256,
                    help="fetching and writing: the adapted windows' upper bound per worker (they wait on storage)")


def models(a) -> list[dict]:
    return []


def pipeline(a, script: str):
    from ..images.accel import cuda_devices, gpu_available
    from ..runtime.cpus import available_cpus

    if not a.preset:
        raise PipelineConfigError("convert: pick --preset (an image preset, e.g. webp-lossy-q80; `linecaster models`)")
    over = run.overrides(a.set, steps=["image"])
    out = a.out.rstrip("/")
    convert = ImageConverter(f"{out}/images", a.preset, options=over.get("image"), skip_existing=not a.overwrite,
                             window=a.window, max_window=a.max_window, max_io_window=a.max_io_window)
    gpus = cuda_devices() if gpu_available() and convert.backend.kwargs.get("accel", "auto") != "cpu" else 0
    a.gpu_tasks = gpus > 0                   # on Ray: one GPU per task (RayGPUExecutor), else Ray hides the GPUs
    if a.workers is None:                    # one worker per GPU (each uses one), else one per CPUS_PER_WORKER
        a.workers = gpus or max(1, available_cpus() // CPUS_PER_WORKER)
    if a.on == "ray" and a.cpus_per_task is None:               # a worker's share of this machine's CPUs per task
        a.cpus_per_task = max(1, available_cpus() // a.workers)
    return [run.reader(a, read_images=False), convert, run.pages(a)], {"engines": False}


#: CPUs per worker process when no GPU decodes: several processes, so Python's GIL does not hold back the threads
CPUS_PER_WORKER = 16


#: what a recipe for this pipeline names (``linecaster.catalog.schema.RecipeDoc.pipeline``) and its slots
PIPELINE = "convert.v1"
SLOTS = {"image": "preset"}
