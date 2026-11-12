# NOTES

Measurements, decisions and open questions, newest first.

## Repetition loops and vLLM's repetition detection (2026-11-12, x86_64 machine with 8 RTX A6000)

A VLM that loops writes the same few tokens until `max_tokens`, and the repair passes send it again at larger caps,
where it usually loops again: with `lightonocr-3-0.8b@3` (4096, then 8192, then 12,288) one looping page costs 24,576
tokens and about 85 s, holds up its task and leaves about 10,000 characters of repetition in its text. linecaster
cannot tell a loop from a dense table that needs more room: both end `length`.

Evidence from an evaluation outside linecaster, on printed book pages:

- 5,010 LightOnOCR-3-0.8B completions (2.06 M tokens): 15 stopped at the cap, all exact loops on one plate page; the
  other 4,995 finished. That page loops in about 3 of 4 runs whatever its pixels (15 of 20); when it loops, all three
  passes loop (85 s); the first repair rescued 2 of 9.
- vLLM's check (vLLM PR #35451, `v1/core/sched/utils.py` `check_sequence_repetition`) simulated exactly on the 5,010
  completions, with the model's tokenizer and the check after every token:

  | Pattern (tokens) | `min_count` | Finished completions stopped | Loops stopped | Tokens at the stop, median / max |
  |---|---|---|---|---|
  | 1-100 | 10 | 18 | 15/15 | 97 / 622 |
  | 2-100 | 6 | 4 | 15/15 | 85 / 374 |
  | 2-100 | 8 | 0 | 15/15 | 91 / 498 |
  | **4-100** | **10** | **0** | **15/15** | **127 / 622** |
  | 8-100 | 16 | 0 | 15/15 | 211 / 994 |
  | any-50 | any | - | 14/15 | - |

  The loose settings stop legitimate repetition: dot leaders of a table of contents (`. . . . .`), an asterism row
  (`* * * *`), tables of empty or elided cells (`<td></td>` six times, `<td>...</td>`). One loop's unit is longer
  than 50 tokens, so `max_pattern_size` 100.

Decision: the chat option `repetition_detection` passes vLLM's field through (defaults 4-100 tokens, 10 times; off
unless set), and nothing else: no client-side detector, no penalties or logits processors. The presets' own guards
(the n-gram processors of DeepSeek-OCR and Unlimited-OCR, MiniCPM-OCR's `no_repeat_ngram_size`, the repetition and
presence penalties of GLM-OCR, olmOCR 2, Nemotron Parse and Qwen3.5) stay: they are the model authors' settings and
make loops rarer, detection only ends a loop that happens anyway. vLLM before 0.17.0 (the first release with the PR)
and other servers ignore an unknown field without a word (vLLM logs it at debug level), so the option is refused
for them.

Not yet validated on a server (before a preset turns it on): the looping page ending within about 1,000 tokens in a
few seconds without repairs; no finished page of a 500-page run ending `repetition`, and text differences against an
`off` run no larger than between two `off` runs; throughput on and off within 2 % at full concurrency (the check runs
in Python in the scheduler after every token); the simulation over the other VLMs' evidence (dense and empty tables,
tables of contents, indexes; DeepSeek-OCR and Unlimited-OCR on table pages, since their processors exempt table tags
and vLLM's check has no exemptions).

## GPU page decoding in a transcription run (2026-11-12, x86_64 machine with 8 RTX A6000, 124 vCPUs)

The `squiddle` recipe (layout, lines, recognition, tables and formulas served by `linecaster serve`, one per task) on
Ray, 8 tasks with one GPU each, over 500 lossy JPEG 2000 page scans of 21 printed books (25 pages each), from a
local checkout of the `image-decode-gpu` branch (commit `0eda6d1`); wall time from the launch to the last task,
model warm-up included, and the model blocks' `model_seconds` summed over the pages:

| Input, `--image-decode` | Wall | layout | lines | recognition | Text differs from the first row |
|---|---|---|---|---|---|
| JPEG 2000, `cpu` (Pillow, as 0.5.13) | 110 s | 319 s | 300 s | 491 s | — |
| JPEG 2000, `auto` (nvJPEG2000) | 66 s | 80 s | 109 s | 179 s | 57 pages (11.4 %), similarity 0.994 |
| WebP q80 (`webp-lossy-q80@3`), `auto` (Pillow: no GPU decodes WebP) | 68 s | 97 s | 123 s | 197 s | 264 pages (52.8 %), similarity 0.963 |

- Every model step is served here, and the server decodes each request's image again (three decodes per page): keeping
  decoded pages in a process saves nothing across requests, the GPU decoding is the gain. The model seconds fall with
  it although they time the model call only, probably because the server's Pillow JPEG 2000 decodes hold the GIL in
  the threads beside the model's (not profiled).
- nvJPEG2000 refused 48 pages, 24 of each of two books (their encoding, not chance); those were decoded with Pillow, and
  their texts equal the first run's exactly. So the models give the same text for the same pixels, and the 57
  differences (of the 452 pages decoded on the GPU, 12.6 %) come from the GPU's pixels alone. Without ground truth this
  says how often the text changes, not whether it gets better or worse. Similarity: difflib's ratio between the two
  texts of a page, averaged over the pages that differ.
- The WebP copies change far more text than the GPU decoding (they are a second lossy encoding; their pixel difference
  was not measured here), and they are about as fast without any GPU decoder: libwebp decodes quickly.
- Served blocks did not yet count `gpu_decoded`/`cpu_decoded` (the server decodes); they now count them from the step's
  `decoder`.

## PNG level for VLM requests (2026-11-12, aarch64 GB10 machine)

8 page scans thumbnailed to 2,048 px (as `lightonocr-3-0.8b`'s requests), Pillow PNG encoding: level 6 (Pillow's
default) 637 ms/page and 3.01 MB, level 3 216 ms and 3.14 MB, level 1 147 ms and 3.30 MB, level 0 70 ms and 7.00 MB;
every level decodes to the same pixels. Requests now use level 1 (`PNG_LEVEL`): the PNG only travels to the server.

## libwebp's method in a whole conversion (2026-11-12, x86_64 machine with 8 RTX A6000, 124 vCPUs)

`convert.py --preset webp-lossy-q80 --set image.method=M` (linecaster 0.5.11) on the same sample of 10,000 lossy JPEG
2000 page scans in 668 books (`--sample 10000 --sample-per-item 16 --sample-seed 2026`), GPU decoding, libwebp 1.6.0
encoding on the CPU, input and output on a network mount. Whole-run pages/s, median file size, and the median PSNR
to the JPEG 2000 decoded by Pillow (100 pages):

| method | pages/s | median size | PSNR |
|---|---|---|---|
| 1 | 138 | 485 KB | 41.36 dB |
| 2 | 133 | 415 KB | 41.10 dB |
| 3 | 99 | 401 KB | 41.61 dB |
| 4 | 100 | 402 KB | 41.61 dB |
| 5 | 93 | 397 KB | 41.53 dB |
| 6 | 62 | 386 KB | 41.53 dB |

Method 0 had no clean run (it was resumed); on 40 pages, encoded with Pillow directly, it gave files 27 % larger than
method 4 (673 against 506 KB median) at the same PSNR. In a whole conversion method 4 costs about 30 % of the
throughput against methods 1 and 2, for files 17 to 25 % smaller and the best PSNR; methods 5 and 6 save 1 to 4 % more
at up to 1.6 times the time. Decided: `webp-lossy-q80@3` uses method 4 again (libwebp's and Pillow's default); the
earlier per-image measurement (below) had suggested a gain of speed that a whole run does not show.

## Image conversion on the GPU (2026-11-12, aarch64 machine with a GB10 GPU, 20 CPU cores)

626 page scans as lossy JPEG 2000 (about 470 KB each, median about 2,000 x 3,600 px) converted to WebP q80
(`webp-lossy-q80`), nvImageCodec 0.10.0, Pillow 13.0.0 with OpenJPEG 2.5.4 and libwebp 1.6.0:

- **Decoding, GPU against CPU**, same colour handling after both: nvJPEG2000 differs from OpenJPEG by at most 1 of
  255 in every image, in 0.0027 % of the channel values (median; at most 0.0033 %); no image is identical. Lossless
  JPEG 2000 decodes identically. nvJPEG against libjpeg-turbo on 6 colour JPEG scans: at most 3 of 255, in about
  1.7 % of the values (its own inverse DCT and colour conversion; fancy upsampling is already on, off gives up to 10).
- **Throughput, local disk**: 626 pages in 20 s with GPU decoding (about 31 pages/s), 2 min 2 s with CPU decoding
  (about 5 pages/s); the encoding is libwebp on the CPU either way.
- **The outputs**: no WebP of the two runs is byte-identical; decoded, they differ by 48.5 dB PSNR (median of 63
  pages, at worst 44.9 dB), against 40.3 dB between a WebP and its JPEG 2000 source: lossy WebP amplifies the
  decoders' one-step differences in a few blocks, far below its own loss. Published images that must not depend on
  the machine need `accel=cpu`.
- **Hub buckets**: input from one bucket and output to another. Written one by one, the Hub takes about 4 files a
  second however many threads upload (1 thread: 0.8/s, 16: 4.4/s; it answers with 429 beyond), while reading scales
  (1 thread: 4 files/s, 16: 35/s): 626 pages took 2 to 3 min. With the converter's four stages (fetch, decode,
  encode, write; the fetching and writing windows bounded apart from the CPUs) and the files going up in batches
  (`HfApi.batch_bucket_files`, up to 128 a call), 626 pages took 47 s (805 a minute), no 429.
- **Pillow's JPEG 2000 decoder holds Python's GIL**: 4.6 pages/s with one thread, 4.3 with eight (WebP encoding
  scales: 2.6 to 17.6). Pillow 13's source says why: the decoder pulls its input through Python (`pulls_fd = 1` in
  `decode.c`; OpenJPEG reads through `j2k_read` → `_imaging_read_pyFd`), and `decode.c` releases the GIL only for
  decoders that do not; it never calls `opj_codec_set_threads`, so OpenJPEG decodes on one thread (`OPJ_NUM_THREADS`
  changed nothing). Pillow's JPEG decoding scales partly (45 to 142 pages/s with 8 threads), its JPEG encoding with
  optimized Huffman tables not at all (90 to 70). With Pillow, processes are the parallelism for JPEG 2000; the
  converter decodes one at a time per process. The working copies stay at full resolution (the maintainer's decision):
  no `reduce`. A CPU conversion therefore runs one worker process per CPU; with GPU decoding one per GPU
  is enough (the GPU decodes and libwebp encodes in threads).
- **x86_64 machine with 8 RTX A6000 and 124 vCPUs (AMD EPYC 7513), the same conversion** of 2,000 lossy JPEG 2000
  page scans on a network mount (read once before, so every run reads from the page cache), output to the same mount:

  | Run | Workers, tasks | Time | Pages/s |
  |---|---|---|---|
  | Pillow + libwebp in a process pool (the simplest script) | 64 processes | 77 s | 26 |
  | the same | 124 processes | 63 s | 32 |
  | local, CPU decoding | 124, 124 | 66 s | 30 |
  | Ray, CPU decoding | 124, 124 | about 50 s | 40 |
  | local, GPU decoding | 8, 64 | 34 s | 58 |
  | local, GPU decoding | 8, 8 | 29 s | 69 |
  | Ray, GPU decoding | 8, 64 | about 57 s | 35 |
  | Ray, GPU decoding | 8, 8 | 28 s | 71 |

  One page on one idle core: 0.75 s to decode, 0.88 s to encode (1.6 s; on the GB10 machine 0.35 + 0.39 s). nvJPEG2000
  against OpenJPEG on 200 of these pages: at most 1 of 255, under 0.005 % of the values; 2 grayscale pages nvJPEG2000
  refused were decoded by Pillow. With GPU decoding the GPUs ran at 0 to 60 % and the CPUs about half idle: libwebp
  sets the pace. What made the difference: one worker per CPU when the CPU decodes (Pillow's JPEG 2000 decoder holds
  the GIL), no CUDA start in CPU runs (124 processes starting CUDA at once took about 40 s), windows kept between a
  worker's tasks, and few long tasks (on Ray every task is a new process, which starts its windows again).
- **libwebp's method at quality 80** (100 of the 626 pages, GB10 machine, one encode per process):

  | method | s/page | size against 4 | PSNR to the source |
  |---|---|---|---|
  | 0 | 0.086 | +15.5 % | 40.24 dB |
  | 1 | 0.110 | +13.0 % | 40.26 dB |
  | 2 | 0.148 | +3.1 % | 39.83 dB |
  | 3 | 0.375 | −0.2 % | 40.34 dB |
  | 4 | 0.376 | 0 | 40.34 dB |
  | 5 | 0.413 | −1.2 % | 40.20 dB |
  | 6 | 0.611 | −3.8 % | 40.17 dB |

  Methods 0 to 2 skip libwebp's search for the best encoding decisions. These are times for the encoding alone, one
  image per process: they do not carry over to a whole conversion, where decoding, I/O and the windows set much of
  the pace (the whole-run comparison below). `webp-lossy-q80@2` used method 0 on their strength; `@3` is method 4.
- **What nvJPEG2000 refuses**: 2 of 200 pages on the x86_64 machine (30 of 2,000 in the runs above), grayscale JPEG
  2000 files whose code blocks use the vertically causal context (code-block style 0x08 in COD; the accepted files
  use 0); nvJPEG2000 rejects the stream while parsing it ("Bad jpeg"), whatever the output layout. Pillow decodes
  them.
- Fixed on the way: nvImageCodec's decoder and encoder are not safe to call from two threads at once (a crash), and
  `HfFileSystem.exists` is not safe from many threads (its directory cache); the converter lists each output folder
  once and writes to object storage without a temporary name.

## Repair passes on by default for LightOnOCR-3 0.8B (2026-11-12)

`lightonocr-3-0.8b@3` repairs at 8192 tokens and then, if needed, at 12,288. On the 33-page trial of table and formula pages (one RTX A6000,
vLLM 0.30.0), 5 pages stopped at 4096; repaired at 8192, 4 finished and one (a dense table) hit 8192 again, while at
12,288 all 5 finished (the longest after 8,958 tokens). A third run, the repair over the existing first-pass records at
8192, finished 3 of 5: a page that had finished after 7,959 tokens hit 8192 at temperature 0.1. 12,288 leaves room for
both; with 18,000 tokens of context a repair of up to 13,840 tokens fits beside the largest page prompt. The pass
escalates in at most two repairs (three passes): 8192, then 12,288 (twice and three times the first 4096), each sent
only while the pass before stopped at its cap; a page keeps the first completion that finished, else its first. On
the trial's figures this gives 4 of the 5 pages at 8192 and the fifth at 12,288, without 12,288-token requests for
the pages that finish at 8192.

Checked on the same 33 pages with `@3` itself (linecaster 0602da6, one RTX A6000, 3 minutes with the server's start):
6 pages stopped at 4096 (the first pass samples at 0.2, and a sixth looped this time); 5 finished at 8192 (2,334 to
7,520 tokens; the looping page's repair ended its loop at 2,334) and the dense table hit 8192 again and finished at
12,288 after 8,958 tokens, keeping its third pass. Stats: `repair_sent` 7, `repair_stop` 6, `repair_length` 1,
`repair_kept` 6; every page written, no rejects.

## Recipe scripts (2026-11-11, aarch64 GB10)

Since 0.5.0 no pipeline script installed `linecaster-kraken`, so linecaster could not run its own `squiddle` recipe:
`uv run launch.py squiddle IMAGES OUT --on hf-jobs ...` stopped in the dry run with "preset kraken-ppocrv6-medium@1
needs engine 'kraken.recognition.v1', which is not installed"; `--backend served --endpoint` does not help on Jobs,
whose servers listen on loopback. `pipelines/transcribe_modular.py` (PaddleX and Tesseract) can run every preset its
slots accept but the three kraken recognizers (9 of 12 recognition presets, all of the other slots).

Decision: the recipes stay YAML in the catalog, and each gets a uv script of its own, `recipes/<id>.py`, as its
environment and entry point (the pattern of one script per recipe, run as `hf jobs uv run <script URL> IN OUT`
without a checkout, but holding no logic: everything stays in the package and the catalog).
`transcribe_modular.py` stays engine-generalist. The scripts take linecaster from its `main` branch on GitHub (git
sources): with path sources a script fetched from its raw URL fails, since uv resolves `path = ".."` against the
directory the command runs in (checked with `pipelines/bind.py` at v0.5.1:
"Failed to build `linecaster @ file:///...`: does not appear to be a Python project"). A tag would make the URL
reproducible but needs the tag in the script it tags; `main` was chosen. A run from a checkout uses the lock, whose
linecaster commit moves when it is relocked with `--upgrade-package` for linecaster's packages.

Locks (packages): `recipes/squiddle.py` 214 (the modular script's 181 minus linecaster-tesseract and tesserocr, plus
35: linecaster-kraken, the kraken fork, torch, torchvision, triton, lightning and the CUDA libraries only torch uses);
`recipes/item-texts.py` 124 (the same as `pipelines/bind.py`). torch stays 2.14.0: only through linecaster-kraken's pin,
in `recipes/squiddle.py.lock` and the engine test scripts; the modular script's lock has none. HF Jobs of a recipe
script (`jobs.dependencies`, no `--commit`): `linecaster`, `linecaster-kraken`, `linecaster-paddlex` from
`git+...@main`, the OpenCV stub and the kraken fork at their locked commits, and 190 constraints (torch 2.14.0,
torchvision 0.29.0, paddlex 3.7.2, onnxruntime-gpu 1.29.0, ...). One page (`iiif_page_8.jpg`) with `squiddle@1` from
a copy of the script with path sources (the branch did not have `run.recipe` on GitHub yet): 20 s, md and hOCR
written, the run record naming `squiddle@1` and its hash.

## Open items

- **Ray Serve is the model server of choice for the future (decided 2026-11-12, not to be built yet).** Today each
  task starts its own server (`ModelServer`, `ChatModelServer`) and holds a GPU for its whole duration, also while it
  works on the CPU. Ray Serve would make a cluster's GPUs one pool of model replicas that the tasks call, so GPUs that
  wait on CPU work could serve other tasks and pipelines; Ray is already in every pipeline script (`linecaster[ray]`),
  and its batching is opt-in (`@serve.batch`), so one page per request stays (the determinism rule). Not chosen:
  Triton (its gain is dynamic batching across requests, which would make a page's result depend on what else is in
  flight; kraken would run in its Python backend, as in `linecaster serve`), and LitServe, BentoML, TorchServe, KServe,
  Seldon (little beyond `linecaster serve`, or Kubernetes only). Worth building once a profile of a real multi-node
  run shows GPUs mostly waiting on CPU work; to settle then: the server outside the run (its versions and
  configuration in the run record), and HF Jobs (no Ray) keeping today's servers. A CTC recognizer gains nothing from
  vLLM (no autoregressive decoding, no KV cache): its speed comes from batching within a page and, if needed, an ONNX
  or TensorRT export inside its engine.
- A recipe of PaddleX and Tesseract presets for the engine-generalist modular script
  (`pipelines/transcribe_modular.py`, which has no kraken), once it is decided what "tested" means for a recipe now
  that evidence has left the catalog: for example a smoke test every recipe must pass (its pipeline built and run on
  a few generated pages, without failed pages) before it is released.

## Manifests and HTTP without an external package (2026-11-10, aarch64 GB10)

- Decided: linecaster depends on no external package for manifests or HTTP. `linecaster.formats.manifests` parses
  IIIF Presentation 2/3 (and one level of Collections) and METS/MODS (also inside OAI-PMH) with lxml;
  `linecaster.net.http` makes its own httpx clients and runs one retry loop for the direct path and the path through
  proxies, with linecaster's own sliding-window rate limiter (`linecaster.net.limits`). No retry library.
- Parity, manifests: a temporary test compared the new parser with the one used before on every manifest fixture
  of the test suite and on variants of each (a commit and its revert in the history): no difference in pages, image
  URLs, fallback URLs, OCR links, labels or metadata.
- Parity, HTTP, against one local server, the layer used before and the new one side by side (direct path): the
  same final result, trace entries (`tries`), attempt count and error for a plain 200, 503 twice then 200 (waits 2 s
  and 4 s), 520 once, 503 throughout, 403, the 404 fallback (to a 200, a 404, the same URL, a 503 throughout), a 429
  with `Retry-After` in seconds and as an HTTP-date (the pause), a 429 with `pause_on: []` (retried after its
  `Retry-After`), a 503 with `Retry-After` in seconds and as a date, `stop_on: [403]`, a response cut by the deadline
  per attempt, a refused connection, `max_retries: 0`; 12 requests at `3/1` and `5/2` took 4.1 s with both rate
  limiters. The only difference was the length of one pause after an HTTP-date `Retry-After` (1.3 s against 2.0 s:
  the date has whole seconds, so the wait depends on when in the second it was sent). The path through proxies:
  the existing proxy tests pass unchanged with both.
- Lock changes: the scripts with the old extra lose three packages (the manifest and HTTP package, its rate limiter
  and its retry library); `bind.py`, `launch.py` and the three test scripts gain h2, hpack, hyperframe and
  fake-useragent 2.2.0 (and httpx, httpcore where they were missing). torch is unchanged in every lock.

## Preparing 0.4.0: S3 in the core, reproducible Jobs (2026-11-10, aarch64 GB10)

- `s3://` is core: linecaster depends on `datatrove[io,s3]` (datatrove's `s3` extra is s3fs) and has no `s3fs` extra.
  Relocked with uv 0.13.6: torch unchanged in every lock (2.14.0 in `tests/test_engines_catalog.py`,
  `tests/test_page_engines_catalog.py`, `pipelines/transcribe_page.py`, `tools/cuda_probe.py`; none elsewhere). The
  four scripts that had the extra kept every version. `bind.py`, `launch.py` and the three test scripts gained s3fs
  (2026.7.0; 2026.6.0 in `tests/test_engines_catalog.py`), aiobotocore 3.10.0, botocore 1.43.117, aioitertools 0.13.0,
  jmespath 1.1.0 (and wrapt 2.5.2 where it was missing), and moved python-dateutil 4.0.0 → 2.9.0.post0 (botocore's
  `python-dateutil<3`).
- How a Job gets the lock's versions. datatrove's `JobsPipelineExecutor` (through `huggingface_hub.run_uv_job`) runs
  `uv run --with REQ ... --python 3.12 launch_pickled_pipeline.py PIK` and passes nothing else to uv. With uv 0.13.6,
  `uv run --with` ignored `UV_CONSTRAINT`, `UV_OVERRIDE` and the `constraint-dependencies` and
  `override-dependencies` of a `UV_CONFIG_FILE`; `--with-requirements` with a `-c` line inside applied constraints,
  but `run_uv_job` cannot pass it; a script's own `[tool.uv]` applied both. Pins as `--with name==version` would
  install packages a lock holds only for other platforms (the locks hold win32-only ones such as win32-setctime) and cannot
  override (surya-ocr's `pillow<11` against the lock's 12.3.0). Hence a launcher: a uv script named like datatrove's,
  its inline metadata the requirements, the lock's index packages as `constraint-dependencies` (which only bound
  what the requirements bring) and the script's `override-dependencies`, running datatrove's launcher.
- Checked without a Job, for every pipeline script: `uv pip compile` of the requirements (linecaster and its engine
  packages from the checkout in place of the archive), `-c` the constraints, `--override` the overrides, Python
  3.12, linux x86_64 and aarch64 (`aarch64-manylinux_2_34`: onnxruntime-gpu's aarch64 wheels need it): every
  resolved version is the lock's, nothing outside the lock. `transcribe_page.py` without the override does not
  resolve; without the constraints 27 of its packages resolve to other versions. The launchers of `bind.py` and
  `transcribe_page.py` ran with `uv run --python 3.12` (`--help`) and imported the lock's Pillow (13.0.0, 12.3.0)
  and torch (2.14.0).
- Not checked on HF Jobs: the launcher in a Job, the Jobs images' uv versions reading a script's `[tool.uv]`, and a
  script environment in place of `uv run --with`'s, which is layered over the image's Python (the servers the
  pipelines start come from the image's `PATH`, not from Python imports, so nothing should depend on the layering).
- `--commit` is required only where it is used: without a script, for a script in the linecaster checkout and for a
  source that points into the checkout. A derivative's script outside the checkout that takes linecaster from a git
  tag, branch or rev runs on Jobs without it.
- The six tests that failed on `main` (five in `test_allocate_proxies.py`, one in `test_tables.py`) patched
  `os.cpu_count`, but since 0.3.1 the worker count uses `available_cpus` (affinity and cgroup quota): on a machine
  with more CPUs than the test assumed the counts differed. The code was right; the tests now patch
  `available_cpus`. `tests/test_engines_catalog.py` failed on `pp-doclayoutv3@1`, released before
  `paddlex.layout.v1` had `reading_order`; the option is listed as added later, as kraken's `compile_backbone` is.

## linecaster as a generalist tool (2026-11-10)

- linecaster names no collection, site, institution, project or machine; project-specific code, defaults and names
  belong in derivatives. The recipe name `squiddle` is neutral and stays.
- `--namespace` is required with `--on hf-jobs` rather than taken from the logged-in account
  (`huggingface_hub.whoami`): a Job is billed to its namespace, and an account's token may reach both a personal and
  an organization's namespace, so an implicit choice could spend the wrong one silently. A required flag puts the
  namespace on the command line and in the run record, fails while the options are checked, before anything
  is launched and without a call to the Hub, and follows "no default presets": a run names what it ran.
- The User-Agent stays datatrove's `HF-Research/1.0`, deliberately: datatrove is integral to linecaster, and its
  `HTTPFetchReader` sends the same.
- The catalog's evidence records left (linecaster is not a data repository); the measurements stay in these notes.
  The evidence format and the tooling that produces evidence, evaluations and ground truth stay: the run record and
  the recipe stamps (what a measurement names), page records with per-step `measurements` and the traces (what it
  measures), `ManifestReader(existing_ocr=True)` and the `TranscriptionConverter` (reference transcriptions as
  `ocr_original` or `ground_truth`) and the writers (datasets). Scoring stays with the evaluation.
- `--naming squiddleocr` became `--naming flat --suffix .paddle`.

## Dependencies cleaned up; the modular script without kraken (2026-11-10, aarch64 GB10)

- `uv lock` (and `uv lock --script`, uv 0.13.6) applies the `[tool.uv.sources]` of path and git dependencies, not only a
  project's or script's own: a script with `linecaster[pybookget]` from a path or a git tag and no direct `pybookget`
  locked pybookget from linecaster's own source; a script with `linecaster-paddlex` from git and no direct
  `opencv-contrib-python` locked the stub as a git subdirectory at the same commit (a relative path source inside a
  git dependency), and listing it directly as well gave the same lock. The pip interface (`uv pip compile`,
  `uv run --with`) does not apply them: `linecaster[pybookget] @ <archive>` alone failed (pybookget is not on PyPI).
  Hence the sources in the packages that need them, and `jobs.dependencies` reading the rest from the script's lock.
- Relocking the scripts with their direct `pybookget`, `kraken`, `opencv-contrib-python` and `s3fs` removed, and the
  `s3fs` extra instead, kept every package and version in every lock; dropping `torch==2.14.0` from
  `transcribe_page.py`'s overrides kept torch 2.14.0 there (surya-ocr allows `>=2.7,<3`).
- `transcribe_modular.py` without `linecaster-kraken`: 219 → 184 packages, all removals (kraken, torch 2.14.0,
  torchvision, triton, Lightning, coremltools, the CUDA libraries only torch used, ...); nothing else moved.
- `uv run --script` does not remove what a script no longer lists from its cached environment: after the relock the
  modular script's environment still had kraken and ran the `squiddle` recipe in-process, until
  `uv sync --script pipelines/transcribe_modular.py` removed it (then the run stops with the `CatalogError`).
- The `squiddle` recipe against a server from `tests/test_engines_catalog.py`'s environment (kraken, PaddleX,
  Tesseract; `pipelines/transcribe_modular.py serve --recipe squiddle`) from the kraken-less script with
  `--backend served --endpoint`: one page of a folder of 17 mixed scans, no failed pages. Not compared with an
  in-process run.
- The runs recorded here with `pipelines/transcribe_modular.py --recipe squiddle` ran at the linecaster commits they
  name, when the script had kraken.

## The goldens retired (2026-11-10)

A derivative's goldens were the check that the modular pipeline reproduces that derivative line for line; they did
that through the migration (sample-60 1,560/1,560 lines, tables-7 651/651, in-process and served, on an aarch64 GB10
and an x86_64 RTX 4000 SFF Ada machine). With the migration done they are retired: no standing check replaces them,
and a change that moves numerics is judged when it is made. Removed: `tests/parity/` (`compare_goldens.py`,
`compare_exports.py`), the `parity` marker, and the `constraint-dependencies` list in every script, which held the
goldens' versions. Relocking without the list kept every third-party version (only the constraint entries left the
locks; the test scripts' locks also caught up with the local packages' versions). HF Jobs no longer pin those packages
in `uv run --with`.

The last comparison, on a cloud A40 (driver 535 with NVIDIA's CUDA 13 forward-compatibility library, x86_64, `--on
ray`, served, one task) against the goldens recorded on the aarch64 GB10 machine for sample-60: 1,560/1,560 lines
present, 1,552 line boxes equal (the other eight within 1 to 6 px), 1,513 lines equal in text and every word box,
32/60 pages exact; 14 character edits in 85,206 characters (CER 0.00016), all single uncertain glyphs (quote styles, a
space before a colon, ſ/s, ¬/-, â/á).

## Ray on Kubernetes: task reservations and threads (2026-11-10)

Planning a Ray cluster of one-GPU worker pods on a Kubernetes cluster, the first draft gave each worker 4 CPUs. With
the default `--cpus-per-task 12` no task would ever have been placed, and Ray gives no error for that. Hence the
launch check (`RayExecutor.check_cluster`), and `--mem-per-task-gb`, because lowering `--cpus-per-task` used to lower
the memory reservation with it. Tested with unit tests only, not yet on a cluster.

Thread pools: inside a pod `os.cpu_count()` is the node's CPU count (often over 100) while the pod's CPU limit is
12, so pools sized by it oversubscribe and the pod is throttled. Ray sets `OMP_NUM_THREADS` for a task; each task now
also sets MKL, OpenBLAS, numexpr and OpenCV (`OPENCV_FOR_THREADS_NUM`) and resizes already-loaded OpenCV and torch.
Not covered: ONNX Runtime's intra-op pool (its own pool, sized to the physical cores unless a session sets
`intra_op_num_threads`; linecaster creates no sessions itself, the engines' libraries do). Throughput with and
without the limits is not measured.

## Slurm: untested (2026-11-10)

The README says a pipeline (a list of blocks) runs on Slurm through datatrove's `SlurmPipelineExecutor`, from Python;
the pipeline scripts have no `--on slurm` (`run.ON`: local, ray, hf-jobs). Neither has run on a Slurm cluster: no
machine here has one. To validate on a cluster: the README's example (one GPU per task, `venv_path` with the engines),
then whether `--on slurm` is worth adding (the builder's stages as dependent array jobs, `depends=`).

## The pipeline shapes in the package (2026-11-10, aarch64 GB10)

Every pipeline script's code moved into `linecaster.pipelines` (`harvest`, `transcribe_modular`, `transcribe_vlm`,
`transcribe_page`, `bind`); each script is now its PEP 723 block, a docstring and `run.main` with its shape's names,
so a derivative's script can run a shape (a derivative's `squiddle.py` runs `transcribe_modular` with the squiddle
recipe and nothing else). Why a package of shapes and not a helper per pipeline: the glossary's "pipeline" is the list of blocks a
run builds, and the scripts were already "one per pipeline shape"; the term **pipeline shape** names the code, and the
package and file names follow the pipeline ids (`linecaster.pipelines.transcribe_modular`, `transcribe_modular.v1`).

- `pipeline_sha256` (describe mode) before and after the move, for 13 command lines over the five shapes (the
  modular pipeline with and without the squiddle recipe, with `--files`, `--item-texts --tasks 2`, served; bind with
  the item-texts recipe; harvest with manifests and resources; the VLM pipeline per page and per region; the page
  engine pipeline): all unchanged; `--recipe squiddle` stays `sha256:9ffdb240…3d31`. The help texts of all five,
  byte-identical. The generated docs: identical apart from the shape now named on each pipeline page.
  `linecaster catalog verify`: OK.
- The modular pipeline's `--files` then gained `PageFileWriter(skip_failed=True)` (the derivative's
  `FailedPagesDropped`, as a writer parameter: a block dropping failed pages in front of the files would also keep them
  from the item stage in one task, but not after the builder's cut, where the item stage reads the page records). Its
  hash with `--files` changes (`--recipe squiddle --files F`: `sha256:146a4bc5…0479` → `sha256:9e1893f6…833d`);
  without `--files`, not.
- The squiddle goldens with `pipelines/transcribe_modular.py --recipe squiddle` after both changes:
  sample-60 1,560 of 1,560 lines, 60 of 60 pages exact; tables-7 651 of 651, 7 of 7 exact.

## Many harvest workers writing to object storage (2026-11-09, a cloud VM, 250 proxies)

Observed on one harvest (`pipelines/harvest.py`, a proxy list of 250, OUT on S3-compatible object storage), not a
benchmark:
- One proxy per worker (`proxies_per_worker: 1`, then the default) with 250 workers: the workers hung. A stack dump
  (`kill -USR1`) showed the main thread waiting in `ExistingImages._list` → fsspec dirfs `ls` → `fsspec.asyn.sync`
  (the listing of `OUT/images/<item>/` that a resumed harvest does to reuse images), fsspec's IO thread idle in
  `select`. Only 28 of the 250 workers ever reached the broker; throughput fell to about 100–250 pages/min.
- 100 workers, one proxy each: 150 proxies idle, throughput lower than 64 workers sharing the proxies.
- `proxies_per_worker: share` with `--workers 64`: a clean start (slots 0–63 claimed at once, all 250 proxies held
  within minutes). The limit was the object storage, not the proxies.
- A relaunch within 3 minutes of stopping a run (before the old slot leases expired): the new workers started their
  slot search at their worker index inside the still-taken range and raced upward for the same slots.

Decisions: `share` is the default again; a run through proxies gets at most `OBJECT_STORAGE_WORKERS` (64) workers by
default with OUT on object storage; the reuse listing has a timeout (`LISTING_TIMEOUT`, 60 s); a worker with index k
takes the k-th free slot. The cause of the hung listing itself (botocore's own connect and read timeouts are 60 s by
default, yet it hung longer) is not known.

## XY-Cut++ reading order (2026-11-07, aarch64 GB10)

Layout models without a learned reading order (PP-DocLayout_plus-L) can now be ordered with XY-Cut++ instead of
plain XY-cut: `linecaster.data.geometry.xy_cut_plus_plus.xy_cut_plus_plus_order(boxes, labels, page_size)`, the
option `reading_order: xy-cut++` of `paddlex.layout.v1`, and the new edition `pp-doclayout-plus-l@2`.

Source: Liu, Li and Wei, "XY-Cut++: Advanced Layout Ordering via Hierarchical Mask Mechanism on a Novel Benchmark",
arXiv:2504.10258v3 (HTML and PDF). Implementations looked at before writing ours:
- The authors' code: `get_layout_ordering` and its helpers in `paddlex/inference/pipelines/layout_parsing/utils.py`
  of github.com/liushuai35/PaddleXrc, branch `eval_order`, commit 7873ab3 (a PaddleX fork, Apache-2.0, Copyright
  2024 PaddlePaddle Authors; SoMarkAI/OXR's NOTICE names it the authors' implementation). Followed where the paper is
  unclear, not copied: it is written around PaddleX's labels, sub-labels of its own (title text, vision footnotes)
  and pixel constants. Credited in the code's docstring. Its sibling repository liushuai35/XY-Cut_plus_plus
  (Apache-2.0) has only an evaluation script and says "code and data coming soon".
- PaddleX 3.7.2's `xycut_enhanced` (Apache-2.0), the product version: consulted for the page furniture (headers
  first, footers last).
- DocVortex (myhloli/DocVortex, MIT; MinerU's "shared XYCut++"), `analyzers/native/_shared/xycut.py`: geometry only
  (no labels, no matching; cross-column blocks merged back by bands), so not the paper's method; not used.
- home-still/xycut-plus-plus (Rust, GPL-3.0) and vquilon/xycut_ppy (no licence stated): not read further, not used.

Choices where the paper is ambiguous or inconsistent (each with what decided it):
- Label categories: `title`, `section_header` → title; `picture`, `chart`, `table`, `caption`, `seal` → vision;
  `footnote` → others (masked, matched last, as the authors' code does with its "other" blocks); every other label →
  text, cross-layout or not by geometry. `page_header` regions lead and `page_footer` regions close the page, top to
  bottom (PaddleX `xycut_enhanced`; the paper says nothing about furniture). Horizontal layouts only; the paper's
  vertical-title weights are unused.
- Cross-layout (Eq. 1-2): the median width of the page's text regions (paper: document-level); "overlap with at least
  2 other blocks" counted by the authors' sweep, which counts columns, not blocks stacked in one column. The code's
  extra rule (wider than 0.6 of the region) is left out.
- Isolated regions (Eq. 3): the paper's Euclidean distance to the page center would only pre-cut at regions near the
  middle of the page; a centered heading between two-column parts at a third of the height would not cut, and the
  masked heading then leaves the gutter free for a vertical cut through both parts. Taken from the code instead: the
  horizontal offset from the page's center line (≤ 0.2 of the page width, the paper's value), no other region but a
  visual one to the left or right at the same height; the cut at the region's top edge, regions assigned to bands by
  their top edge.
- Density (Eq. 4-5): τ_d once per band; > θ_v = 0.9 (paper; the code uses 1.0) cuts horizontally first, else
  vertically first, at all whitespace gaps of ≥ 1 px, the other axis when the first gives no cut. A band without
  single-layout text is cut as it is, nothing masked (the paper does not say).
- Matching (Eq. 7-13, Algorithm 1): the filter F of Eq. 7 taken literally would match no cross-layout region (nothing
  ranks above it); Algorithm 1 searches all of T, which is what is done. Term weights [M², M, 1, 1/M], M the larger
  page side (paper; the code fixes 10⁸, 10⁴, 1, 10⁻⁴). φ1: the code's directions (a visual region always horizontal,
  a candidate horizontal unless taller than three times its width) and projection overlap on the narrower region
  < τ_overlap = 0.3 (paper; the code 0.01). φ2: the code's edge gap, weighted by the side the pending region lies on
  (left, right, above, below the candidate), the sum of both axes when diagonal (Eq. 10). Eq. 14's rows by the
  paper's labels: title [1, 0.1, 0.1, 1], cross-layout [1, 1, 0.1, 1], vision and others [1, 1, 1, 0.1] (the code
  gives paragraph titles and visuals the cross-layout row). φ3 and φ4 as the paper writes them (the code also negates
  them below the candidate for titles and visuals). No early termination (same result). The first candidate in order
  wins a tie (Algorithm 1's strict `<`).
- Final sort (Algorithm 1, line 24): "label priority, then anchor index, then y1, x1" taken literally would put every
  cross-layout region before the page's text; sorted instead after each stage by anchor rank, then top, then left,
  as the code does; label priority orders the stages.
- `place_unordered` (the `LineAssigner`'s fallback when no region has an order, i.e. orphan rows alone on a page
  without layout regions) keeps plain XY-cut: on 5,000 synthetic orphan-row pages the two orders differed on 856, so
  switching would change released recipes' outputs (squiddle@1 reaches it).

Editions: an engine option whose default keeps the behavior is compatible (the engine id stays), changing the default
is not, so `reading_order` defaults to `xy-cut` and `pp-doclayout-plus-l@1` (which does not state it) keeps its hash
and its order. Edition 2 states `reading_order: xy-cut++`, released into the lock; `pp-doclayout-plus-l` without an
edition now means edition 2 (upgrade note). No other released preset or recipe has a model without learned order.

DocBench-100 (the paper's benchmark, 0.988 mean BLEU-4 for XY-Cut++, 0.797 for XY-cut) is not public: the authors'
repositories have the evaluation script with local paths only, and no copy was found on GitHub or Hugging Face. Not
scored.

Sample-60 (a 60-page sample of 19th-century scientific print), `--recipe squiddle --layout pp-doclayout-plus-l@1`
and `@2` (everything else from squiddle@1), in-process, one task, one run each; page Markdown (`--files md`,
furniture left out) scored the leaderboard's way with a fresh clone of the leaderboard's scoring harness
(consolidate → `normalize_outputs` postproc 3 as `kraken/PP-OCRv6-medium`, strip only → `score_dataset`).

| volume | CERread @1 (XY-cut) | CERread @2 (XY-Cut++) |
|---|---:|---:|
| book A | 0.0040 | 0.0040 |
| book B | 0.4712 | 0.2605 |
| book C | 0.0123 | 0.0123 |
| book D | 0.0058 | 0.0058 |
| book E | 0.1374 | 0.1374 |
| book F | 0.0065 | 0.0065 |
| all 60 pages: CERdip / CERread / recall | 0.1051 / 0.0924 / 0.9562 | 0.0730 / 0.0601 / 0.9563 |

- The order changed on 16 of 60 pages; the reading CER on 5, all in book B (two columns of species
  descriptions with centered section titles): page B1 0.5227 → 0.0089, B2 0.4362 → 0.0045, B3 0.3684 → 0.3565,
  B4 0.4715 → 0.4655, B5 (a plate page) 2.2329 → 2.2192. The other 11 changes are among page headers and page
  numbers (top to bottom, left to right now), which the Markdown leaves out: six pages of book A, four of book D,
  one of book F.
- The page text (`Transcription.text`, furniture kept) moves the same way: CERread 0.0939 → 0.0617.
- Book E and the remaining pages of book B stay far above PP-DocLayoutV3 with its learned order
  (CERread 0.0270 for all 60 pages in the same chain, "More line recognizers" below);
  whether that is PP-DocLayout_plus-L's regions or what is left of their order was not investigated.
- squiddle@1 after the change: `compare_goldens.py` 60 of 60 pages exact, 1,560 of 1,560 lines.
- Not measured: x86_64, tables-7, the full ground truth, other layouts (newspapers, many columns), DocBench-100,
  speed of the ordering alone (both runs 79 s for 60 pages with model loading).

## dots.mocr and LightOnOCR-3 on an RTX 4000 SFF Ada (2026-11-06)

The presets `dots-mocr@1` (leaderboard row 1), `lightonocr-3-4b@1` (row 4) and `lightonocr-3-0.8b@1` (row 11), first
runs through linecaster, on the 60-page sample, one after another on one RTX 4000 SFF Ada 20 GB (x86_64, compute
capability 8.9). One run each.

Setup:
- linecaster at 2b26d5d (a fresh clone), as the olmOCR-2 run of the same day: `pipelines/transcribe_vlm.py OUT
  --parquet <sample>/data --id-key PageID --recognition <preset>`, the vLLM venv's `bin` first on `PATH` (`vllm`,
  `ninja`).
  `ChatModelServer` started `vllm serve` on loopback with the preset's flags, the revision pinned; it stopped vLLM
  at the end of each run, before the next.
- dots.mocr: vLLM 0.26.0 (the leaderboard's), the venv of the olmOCR-2 run (`uv pip install --exclude-newer
  2026-07-26T00:00:00Z vllm==0.26.0`: torch 2.11.0+cu130, transformers 5.14.1). `--window 4 --initial-window 4
  --gpu-memory-utilization 0.6` and `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`: the leaderboard's scored run
  (`--max-window 4 --gpu-memory-utilization 0.6` on an L40S, the job's environment), not the driver's defaults (12
  and 0.9), which its docstring says ran out of memory in the vision encoder. The driver's transformers-v5 boot
  hazard did not occur (vLLM 0.26.0 itself needs transformers 5.5.3 or later).
- LightOnOCR-3-4B and -0.8B: vLLM 0.30.0 (the leaderboard's exception for these rows), a new venv made the same way
  (`--exclude-newer 2026-09-23T00:00:00Z vllm==0.30.0`, the day after the release: torch 2.13.0+cu130, transformers
  5.17.0, flashinfer-python 0.6.18.post1). `--window 12 --initial-window 4` (the driver's `Auto(initial=4,
  max_limit=12)`) and `--gpu-memory-utilization 0.8` (the driver's).
- Memory: no change to `--max-model-len`, and none to the memory share beyond the leaderboard's own. dots.mocr:
  weights 5.69 GiB, KV cache 5.86 GiB (219,536 tokens, 6.7 full contexts), but 15.6 of 20 GB in use at the peak, about
  3 GB above vLLM's 12 GB budget: the vision encoder's activations on full-size pages, which is why the leaderboard
  lowered the share. At the pipeline's default 0.8 (a 16 GB budget) that would have left well under 1 GB free.
  LightOnOCR-3-4B: weights 8.61 GiB, KV cache 4.56 GiB (132,476 tokens, 8.1 full contexts), 15.7 GB peak.
  LightOnOCR-3-0.8B: weights 1.72 GiB, KV cache 11.98 GiB, 15.6 GB peak.
- Kernels: FlashAttention 2 for the language model and the vision tower; LightOnOCR-3's linear-attention layers on
  the Triton/FLA GDN prefill kernel and the CUDA decode kernel.

Scored the leaderboard's way with the same clone of the leaderboard's scoring harness (consolidate →
`normalize_outputs` postproc 3 → `score_dataset`), next to the leaderboard's raw completions for the same pages
(`rows/<row>/raw.parquet`, column `raw_verbatim`) put through the same three steps. For these three rows the
leaderboard's published `normalized.parquet` scores the same as its raw completions re-normalized (both postproc 3,
after the front-matter fix).

| run | CER dip | CER reading | recall | loops |
|---|---:|---:|---:|---:|
| dots.mocr, linecaster, RTX 4000 SFF Ada | 0.0299 | 0.0178 | 0.9589 | 0 of 60 |
| dots.mocr, leaderboard, L40S, same 60 pages | 0.0264 | 0.0141 | 0.9633 | 0 of 60 |
| dots.mocr, leaderboard, 2,165 pages | 0.0503 | 0.0211 | 0.9836 | 0.88 % |
| LightOnOCR-3-4B, linecaster | 0.0324 | 0.0199 | 0.9553 | 0 of 60 |
| LightOnOCR-3-4B, leaderboard, A10G, same 60 pages | 0.0331 | 0.0207 | 0.9544 | 0 of 60 |
| LightOnOCR-3-4B, leaderboard, 2,165 pages | 0.0546 | 0.0247 | 0.9711 | 0.42 % |
| LightOnOCR-3-0.8B, linecaster | 0.0549 | 0.0307 | 0.9526 | 0 of 60 |
| LightOnOCR-3-0.8B, leaderboard, A10G, same 60 pages | 0.0633 | 0.0393 | 0.9521 | 0 of 60 |
| LightOnOCR-3-0.8B, leaderboard, 2,165 pages | 0.0896 | 0.0363 | 0.9659 | 0.88 % |

The 2,165-page rows: CER reading, recall and loop rate from RESULTS.md, CER diplomatic from the leaderboard page's
data (RESULTS.md gives the reading lane only).

- The request is the leaderboard's on every page: prompt tokens equal the leaderboard's on all 60 pages for all three
  models (dots.mocr 550,085 in all, the full-resolution passthrough; LightOnOCR-3 172,552, the 2048-px thumbnail).
  Byte-identical completions: dots.mocr 47 of 60, LightOnOCR-3-4B 34, LightOnOCR-3-0.8B 28 (sampling at temperature
  0.1 and 0.2, no seed, on the leaderboard as here).
- dots.mocr: the whole difference is one plate of book E, for which this run's completion is empty (one
  token, finish `stop`; the leaderboard's has the plate's captions, page CER 0.31). Without it, 0.0125 against 0.0125
  (reading) and 0.0247 against 0.0248 (diplomatic). Otherwise 4 pages worse and 4 better, all small.
- LightOnOCR-3-4B: better than the leaderboard's on 12 pages, worse on 6, all small (at most 0.018 page CER).
- LightOnOCR-3-0.8B: most of the difference is one text page of book B, where the leaderboard's completion
  moves one species' block (synonymy and description) to the end of the page (page CER 0.230 against 0.018 here).
  Without it, 0.0312 against 0.0312 (reading).
- No page reached its token cap (longest completions 1,320 of 16,384, 1,283 and 1,323 of 4,096), no errors, every
  finish reason `stop`, on the leaderboard's 60 as on these.
- Time (whole process: uv environment, vLLM's start, the pages; the pages alone from the first request to the
  last, with the window's pages in flight):

| model | process | before the first page | pages | s per page | leaderboard job, 2,165 pages |
|---|---:|---:|---:|---:|---:|
| dots.mocr (4 in flight) | 807 s | 75 s | 732 s | 12.2 | 8,406 s on an L40S, 3.9 s per page |
| LightOnOCR-3-4B (up to 12) | 433 s | 191 s | 242 s | 4.0 | 5,252 s on an A10G, 2.4 s per page |
| LightOnOCR-3-0.8B (up to 12) | 155 s | 106 s | 49 s | 0.82 | 2,302 s on an A10G, 1.1 s per page |

  The leaderboard's times include its jobs' start. dots.mocr is prefill-bound here (about 9,200 image tokens a page,
  some 880 prompt tokens per second). LightOnOCR-3's start includes vLLM's CUDA graph capture and the first Triton
  compile of the GDN kernels (148 s of engine init for the 4B).

Not checked: the leaderboard's images themselves (their vLLM builds, transformers, Pillow); a second run of each (no
run-to-run variation measured, so the empty dots.mocr page may or may not recur).

## Four more page readers: Surya OCR 2.5, Indra OCR, Falcon-OCR, OXR-1.0 (2026-11-06, aarch64 GB10 and x86_64 A6000)

A public OCR leaderboard's rows 10 (`datalab-to/surya-ocr-2.5`), 22 (`datalab-to/indra-ocr`), 25 (`SoMarkAI/OXR-1.0`)
and 26 (`tiiuae/Falcon-OCR`) as presets that run them the way the leaderboard's drivers do
(`drivers/{surya-ocr25,indra-ocr,oxr,falcon-ocr}-port.py` of the leaderboard's repository). None of them is a chat
model, so none fits `chat.v1`.

Decisions:

- **Page engines.** An engine whose unit is the page, run by `PageRecognizer` like any model block (`InProcess`, or
  `Served` behind `linecaster serve`), next to the `Chat` backend; its raw output verbatim in `extra["raw"]`, as for
  chat presets, and the leaderboard's post-processing left to the harness. One pipeline shape for all four:
  `pipelines/transcribe_page.py` (reader → `PageRecognizer` → writer → the service), a new script rather than
  `transcribe_vlm.py` because its environment differs (surya-ocr brings torch; `transcribe_vlm.py`'s lock stays as
  it was).
- **Engine packages**: `linecaster-indra` (`indra-ocr==1.1.2`), `linecaster-surya` (`surya-ocr==0.23.0`) and
  `linecaster-services` (Falcon-OCR's and OXR's clients, standard library HTTP, no dependency of their own). The
  vendor services' clients are in-process engines, not a new backend: one page per request, one request in flight
  per task (the leaderboard's drivers had up to 8 and 16 in flight). More tasks share one running service with
  `--recognition-endpoint`; the engine's `endpoint` is operational (left out of `pipeline_sha256`).
- **`ServiceServer`** starts what a page preset's `serve` block names: `vllm serve` on the fetched pin (Surya) or the
  vendor image's entrypoint (`serve.server: vendor`: `command`, `health`, `weights_dir`, new optional schema
  fields), without the pipeline's environment. The pipeline runs inside the vendor's image (on HF Jobs the preset's
  `serve.image`; here `docker run` of the same image digest, with uv mounted).
- **One environment for both packages**: surya-ocr pins OpenCV 4.11.0.86, indra-ocr takes any, so both get 4.11 (the
  leaderboard's Indra job resolved the newest of its day). surya-ocr declares `pillow<11`, linecaster `Pillow>=11`:
  the script overrides Pillow with the shared pin (12.3.0; the leaderboard's Surya run had 10.4.0) and keeps torch at
  the 2.14.0 build every other script has (surya-ocr would resolve 2.15.0; with the vLLM backend surya uses torch only
  to detect the device). No existing script or lock changed.
- **An engine may take the image file's bytes** (`image_input = "bytes"`): the leaderboard's Indra driver gave the
  package the dataset's own file. On the sample, Indra from the file reproduced the leaderboard's Markdown on 54 of 60
  pages; from a PNG of the decoded RGB pixels on 26 (CER reading 0.0486 against 0.0489; the aarch64 and the x86_64
  machine agreed on all 60 pages).
- **Falcon OCR is pinned at `177110bf`**, not the repository's head: every file of `/models/Falcon-OCR` in the
  leaderboard's image (`ghcr.io/tiiuae/falcon-ocr@sha256:2ec80252...`) has the git blob of that revision (2026-03-09),
  `model.safetensors` its sha256 (`6e7f73a5...`); head (Falcon OCR v1.5, 2026-09-11) has other weights.
- **OXR's form**: `output_formats` goes as one field per format, as httpx (the leaderboard's saturate 0.2.0) encodes a
  list. saturate 0.3.0's multipart sends `str(value)` (`"['markdown', 'json']"`), so OXR is not streamed through
  saturate. `OXR_API_HOST` is set to 127.0.0.1 (the entrypoint's vLLM and layout services bind loopback anyway);
  Falcon's entrypoint binds both its services to every address of the container and has no setting for it.
- **Surya's server flags** are the package launcher's for `VLLM_GPU_TYPE=a100-80` (the leaderboard's A100 80 GB),
  checked against the installed package (`linecaster_surya.package_flags`, a test); vLLM serves the fetched pin under
  the package's model name, and the package attaches through `SURYA_INFERENCE_URL`.

Runs on the 60-page sample, scored the leaderboard's way with a fresh clone of its scoring harness (consolidate →
`normalize_outputs` postproc 3 → `score_dataset`; the normalizer run from outside the project, as its run note
says), next to the leaderboard's own outputs for the same pages (its published `rows/<row>/normalized.parquet`). CER
reading:

| Model | Where | linecaster | leaderboard, same 60 pages | identical to the leaderboard | leaderboard, 2,165 pages |
|---|---|---|---|---|---|
| Surya OCR 2.5 | RTX A6000, vLLM 0.25.1 image | 0.0262 | 0.0251 | HTML of 52 pages, full-page completion of 30 | 0.0351 |
| Indra OCR | GB10 machine's CPU (aarch64), one task | 0.0489 | 0.0489 | 54 pages | 0.0621 |
| OXR-1.0 | RTX A6000, the leaderboard's image | 0.0380 | not published | - | 0.1104 |
| Falcon-OCR | RTX A6000, the vendor image | 0.0775 | 0.1301 | 47 pages | 0.1384 |

- Falcon-OCR: the gap is one plate page of book B on which the leaderboard's run looped (a numbered list from 101. to
  791., 5,466 characters, page CER 66.5) and this run did not (114 characters). Of the other 59 pages, 12 differ, by
  up to 0.07 page CER either way. The service reports no finish reason.
- OXR-1.0: the leaderboard's outputs for these pages are not published (its bucket has no OXR row), so there is no
  same-page comparison. Per volume here: book B 0.118 and book E 0.116, the other four 0.006 to 0.014; the
  leaderboard's full-benchmark number carries text read twice on book B's pages and runaway leader dots on three
  index pages of book F (the leaderboard's RESULTS.md).
- Surya: the blocks' confidences differ in the last digits on every page, so the raw JSON is never identical; no page
  fell back to block mode (the leaderboard's run: one).
- Time per page, one page in flight: Indra 0.3 s (one GB10 core), Falcon-OCR 2.3 s, Surya 4.8 s, OXR 2.6 s. The
  services took 68 s (Falcon-OCR), 336 s (vLLM for Surya, with torch.compile) and 185 s (OXR, the weights
  downloaded) to start.

Not verified: any of them on HF Jobs (the Falcon-OCR image has Python 3.10 and no uv, so the pipeline cannot run in it
there as it is); `GPUJobsExecutor` and Ray with these services (a vendor entrypoint's ports are fixed, so
`point_to_gpu` cannot move them); the page engines behind `linecaster serve`; on the x86_64 RTX 4000 SFF Ada machine.
The engines return text-only transcriptions; the geometry the vendors return (Surya's and Indra's blocks with boxes,
Falcon's regions, OXR's blocks) is kept in `extra`, not made into regions and lines.

Licenses: Surya OCR 2.5 and Indra OCR weights under modified OpenRAIL-M licenses (the "AI Pubs Open RAIL-M License
(Modified)": free for research and personal use and below USD 5 million (Surya) or 20 million (Indra) of revenue and
of funding, never for a competing product or service; the packages' code is Apache-2.0); OXR-1.0 under the "OXR
License" (Apache-2.0 with additional terms: commercial use without a separate license below USD 2 million of funding
and of revenue, never for a competing hosted API); Falcon OCR Apache-2.0.

## olmOCR-2-7B-1025-FP8 on native FP8 (2026-11-06, RTX 4000 SFF Ada)

The preset `olmocr-2-7b-1025-fp8@1` (leaderboard row 5) on the 60-page sample, on an RTX 4000 SFF Ada 20 GB (x86_64,
compute capability 8.9), which runs FP8 natively. The leaderboard's run was one HF Jobs `a10g-small` job (A10G,
Ampere: no FP8 tensor cores, so vLLM dequantizes the weights; the driver's docstring calls it the Marlin path).

Setup:
- linecaster at 2b26d5d (a fresh clone): `pipelines/transcribe_vlm.py OUT --parquet <sample>/data --id-key PageID
  --recognition olmocr-2-7b-1025-fp8@1 --window 12 --initial-window 4`. `ChatModelServer` started `vllm serve
  allenai/olmOCR-2-7B-1025-FP8 --revision 40bd720... --max-model-len 16384 --no-enable-prefix-caching
  --mm-processor-cache-gb 0 --limit-mm-per-prompt {"image": 1} --gpu-memory-utilization 0.8`, on loopback: the
  leaderboard driver's flags exactly. At most 12 pages in flight, 4 at the start, as the driver's saturate window
  (`Auto(initial=4, target_waiting=4, max_limit=12)`).
- vLLM 0.26.0 (the leaderboard's version) from PyPI in its own venv: `uv venv --python 3.12`, then `uv pip install
  --exclude-newer 2026-07-26T00:00:00Z vllm==0.26.0` (the day after the release, to approximate the image's
  resolve): torch 2.11.0+cu130, transformers 5.14.1, flashinfer-python 0.6.14, compressed-tensors 0.17.0. Its
  `bin` goes first on `PATH` (`vllm` and `ninja`). Not the leaderboard's image `vllm/vllm-openai:v0.26.0` (no Docker
  here), whose package versions were not compared. The venv of the MiniCPM-OCR run (a vLLM nightly, 0.32.1rc1, with
  a transformers dev build) was not used: it is not the leaderboard's version.
- vLLM picked `CutlassFP8ScaledMMLinearKernel` for the FP8 layers (W8A8) and FlashAttention 2.
- Memory: no change needed. Weights 9.56 GiB, KV cache 5.72 GiB (107,040 tokens, 6.5 times one full context),
  17.5 of 20 GB in use.

Scored the leaderboard's way with a fresh clone of the leaderboard's scoring harness (consolidate →
`normalize_outputs` postproc 3 → `score_dataset`), next to the leaderboard's raw completions for the same pages
(`rows/olmocr2/normalized.parquet`, column `raw_verbatim`) put through the same three steps:

| run | CER dip | CER reading | recall | loops |
|---|---:|---:|---:|---:|
| linecaster, RTX 4000 SFF Ada (FP8 W8A8) | 0.0350 | 0.0204 | 0.9431 | 0 of 60 |
| leaderboard, A10G, same 60 pages | 0.0345 | 0.0196 | 0.9436 | 0 of 60 |
| leaderboard, 2,165 pages (RESULTS.md) | 0.0576 | 0.0279 | 0.9573 | 0.55 % |

- The leaderboard's published `markdown` column for this row predates its front-matter fix of 2026-10-30 (made without a
  postproc bump): on 9 of these pages, all blank, it holds the YAML front matter alone, which scores 0.0461 / 0.0304
  / 0.9436. Compare against the raw completions re-normalized, not against that column.
- 34 of the 60 completions are byte-identical to the leaderboard's. linecaster's image encoding gives the driver's PNG
  bytes on all 60 pages (same Pillow), and the prompt tokens equal the leaderboard's (96,718 in all; 1,372 to 1,786 per
  page). Completion tokens 27,163 against 27,153.
- Page CER reading: worse than the leaderboard's on 16 pages, better on 5, equal on the rest. The largest difference is
  one plate of book B, where this run also read the two engraver lines (page CER 0.79 against 0.38);
  without that page 0.0198 against 0.0193. The others are small (at most 0.064 page CER, on a 61-character page), across all six volumes.
- No page reached its token cap (longest completion 1,325 of 8,192 tokens), no errors.
- Time: 291 s for the whole process (the uv environment, vLLM's start of 120 s with 19 s of torch.compile, then the
  pages); the 60 pages took 167 s, 2.8 s per page with up to 12 in flight. The leaderboard's job ran 3,527 s for 2,165
  pages on the A10G (1.6 s per page, its start included).
- Scoring: `normalize_outputs` needs `uv run --no-project --no-config <clone>/runners/normalize_outputs.py`; with uv
  0.13.6, `--no-project` alone still applied the clone's `exclude-newer` (2026-07-05), under which `docling-core>=2.89`
  does not resolve.

Not checked: the leaderboard's image itself (its own vLLM build, transformers and Pillow); a second run (sampling at
temperature 0.1, so run-to-run variation on these pages is not measured).

## The refactoring of November 2026 (2026-11-06)

Six phases, each merged into main after the suite and the goldens (sample-60, 60/60 pages exact): the decisions on
paper (glossary, conventions); renames, layout and the catalog format; tracing, contracts and the builder; rule-based
steps as catalog engines, recomposition and binding; backends and families (the chat backend, converters,
skeletons); docs; tests and engine hygiene. The plan and the per-phase designs were working documents under
`docs/plan/`, removed at `v0.1.0`; they are in the history at 9c7fe4e. Every rename is in `CHANGELOG.md` (0.1.0).

## Ray Data instead of an executor: a spike (2026-11-06, aarch64 GB10)

Could a pipeline's per-page blocks run as Ray Data `map_batches` stages (an actor per block, pages streaming
between them) instead of datatrove's executors? `tests/integration/ray_data_spike.py` builds the `squiddle@1`
pipeline as a normal run does (the script's `pipeline()`, the builder, one task) and runs its 11 per-page blocks
(LayoutDetector, LineDetector, LineAssigner, LineRecognizer, UnicodeNormalizer, TableRecognizer, FormulaRecognizer,
Typographer, Recomposer, Composer, RecipeStamper) as one `map_batches` stage each: `batch_size=1`, one actor per
block (`ActorPoolStrategy(size=1)`), each `warm_up()` once and then `block.run` per page; the five model blocks
`num_gpus=0.2` and 3 CPUs each, the rule blocks 0.5 CPU. A page travels between stages as a row (id, text, metadata
as JSON, the image media's fields as JSON, the image bytes); the round trip is exact for all 60 pages. Ray 2.59.0
from the `transcribe_modular.py` environment (extra `[ray]`), nothing installed, no lock changed, torch
2.14.0+cu130 before and after. Pages: sample-60, one run each, no warm-up run.

| | datatrove, local, 1 task | Ray Data |
|---|---|---|
| wall time, end to end | 84.4 s | 59.0 s |
| model loading | 16.1 s, one after another | in parallel, the longest 12.3 s (formulas) |
| after loading, to the last page | 65.4 s | 39.0 s |

- Outputs: the `ocr_new` transcription of all 60 pages is identical (every step's `seconds` and `datetime` left
  out); the whole rows of 59: the one page the normal run sampled for tracing has a `trace_id`.
- The gain is the blocks overlapping in separate processes: throughput is set by the recognition stage (44.9 s of
  the normal run's 65.4 s). Not measured: datatrove with two or more tasks on the one GPU, which overlaps the same way
  at the cost of each task loading its models.
- Blocks pickle into Ray actors with cloudpickle as they are (0.5 to 2 KB; `InProcess` leaves loaded models out).
  Five CUDA contexts instead of one; GPU memory not measured (the GB10 reports none). Ray sets `OMP_NUM_THREADS`
  to an actor's CPUs.
- Ray listens on every interface by default even with `_node_ip_address="127.0.0.1"`; with
  `RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER=0` set before `import ray`, every Ray process listened on loopback only (the
  script checks this while the actors run). Ray writes `~/.ray/auth_token` (token auth is on by default) and session
  folders under `/tmp/ray`.
- What the Ray Data path lacks: resume (no completion markers), `OUT/logs` and datatrove's stats (a block's
  `stat_update`s stay in its actor), stage cutting (item shards, `--until`, `--after`, `--tap-after`), the
  `RejectWriter` and the error budget (`run()` per page resets it), tracing, the run record, writers per rank.
  Back pressure was not exercised on 60 pages.

The same day, the two datatrove alternatives the comparison left out (same machine and pages, one run each, the GPU
otherwise idle; `uv run pipelines/transcribe_modular.py IMAGES OUT --recipe squiddle` plus the flags):

| | wall time, end to end | goldens (sample-60) |
|---|---|---|
| in-process, 1 task (above) | 84.4 s | — |
| `--backend served`, 1 task | 65.5 s (of it 15.3 s the server's warm-up) | 60/60 pages, 1560/1560 lines exact |
| in-process, `--tasks 2 --workers 2` | 64.4 s (the longer task 61.5 s) | 60/60 pages, 1560/1560 lines exact |
| Ray Data (above) | 59.0 s | `ocr_new` identical to the 1-task run |

Each closes most of the gap: 25.4 s of the 84.4 s with Ray Data, 18.9 s served, 20.0 s with two tasks. Served with
two tasks (a server per task) and larger `--window` values were not measured.

Recommendation: do not adopt it now. The outputs are the same and the time after loading is 1.7x shorter here, but
all of it comes from overlapping the blocks, and resume, logs, stats, rejects, tracing, the run record and stage
cutting would each have to be rebuilt on Ray. With served or two tasks per GPU, datatrove
gets within 6 s of it on these 60 pages; revisit only when one GPU per task is clearly underused on Jobs.

## Readable item texts from the item recomposition (2026-11-06, aarch64 GB10)

The six whole items of the 2,165-page ground-truth set, from the squiddle recipe's page records of the parity run
above (531a422). Before: `ItemTexts` (its own line flow, `join_lines`), recorded at ff3328f. After: `bind.py --recipe
item-texts` (`Binder` → `Recomposer(unit="item")` → `CharacterNormalizer` → `ItemTextWriter`).

| Item | Pages | Paragraphs before | after | Decisions before | after | Differ | Only before | Only after | CER before | after |
|---|---|---|---|---|---|---|---|---|---|---|
| book A | 341 | 1,392 | 1,521 | 287 | 268 | 54 | 19 | 0 | 0.0288 | 0.0287 |
| book B | 648 | 6,390 | 8,631 | 2,769 | 2,163 | 186 | 636 | 30 | 0.0705 | 0.0693 |
| book C | 84 | 492 | 600 | 314 | 299 | 1 | 15 | 0 | 0.0388 | 0.0388 |
| book D | 516 | 2,426 | 2,847 | 2,082 | 1,980 | 55 | 102 | 0 | 0.0475 | 0.0472 |
| book E | 60 | 144 | 206 | 438 | 414 | 1 | 26 | 2 | 0.1491 | 0.1494 |
| book F | 516 | 3,096 | 3,843 | 3,155 | 2,994 | 17 | 163 | 2 | 0.0828 | 0.0827 |
| all | 2,165 | 13,940 | 17,648 | 9,045 | 8,118 | 314 | 961 | 34 | 0.0615 | 0.0610 |

- Paragraphs: the readable texts' blocks other than tables (a paragraph continued across regions or pages counts
  once). Decisions: a line-end hyphen removed or kept, keyed by page and the line it ends (after: the last line of
  the row). CER: `readable_txt` against the ground truth's page texts of the item joined in page order, whitespace
  collapsed to single spaces, edit distance over the ground truth's length (3,220,317 characters). The ground truth
  is as laid out and full page (running heads, page numbers, line-end hyphens kept), so both CERs include those.
- Differ (314): 311 hyphens the old flow removed (a lower-case letter followed) are kept now because the item has
  the hyphenated form elsewhere (`attested`): `ear-coverts`, `under tail-coverts`, `blackish-purple`,
  `fusco-nigricante`, `au-dessous`, `Au-devant`, `lui¬|même` → `lui-même`, `semi¬|cercle` → `semi-cercle`; 3 the
  other way (`letter_follows`), marks at the foot of a page whose paragraph continues on the next page.
- Only before (961): 834 rows ending in a hyphen after which the recomposition starts a new paragraph at an indented
  row (hanging indents in species descriptions and references, most of them in book B:
  `anfractibus nunc per-|paucis`), so the mark stays at the paragraph's end; 82 region ends the recomposition does
  not continue (`olive to red-` at the end of a region); 37 lines the old flow joined side by side within a row
  (index entries, `Calcarius lapponicus-|130`); 8 row ends inside a paragraph without a decision.
- Only after (34): continuations across a region or page break the old flow did not join.
- verbatim_txt: identical for all six items. Item documents (md, txt, json) from `bind.py`'s blocks equal
  `BindItem`'s for all six in the project environment; `bind.py`'s own lock has docling-core 2.106.0 (the project
  2.105.0), whose JSON says `version` 1.11.0 instead of 1.10.0, md and txt identical.
- The squiddle recipe after the change: `compare_goldens.py` 60 of 60 pages exact, 1,560 of 1,560 lines.

## Rule-based steps on their engines: parity (2026-11-06, aarch64 GB10)

The squiddle recipe before (531a422) and after the rule-based steps moved onto their engines and presets
(`ratios@1`, `unicode-recomposition@1`, `docling-composition@1`), in-process:

- Page runs, sample-60 and tables-7, `--text reflow` and `lines`, with and without `--furniture`, formats md, txt,
  html, doclang, json, hocr, alto, page, transcription (2,412 files): md, txt, html, doclang and the Docling JSON
  byte-identical; hOCR, ALTO and PAGE identical apart from the step records (the typography step now named by its
  engine and preset, new recomposition and composition steps); transcription JSON and page records identical apart
  from the steps and, with `reflow`, the paragraphs the `Recomposer` adds. The documents replayed from the same page
  records with sections and dividers on and off: 5,360 files, all identical.
- `compare_goldens.py`: 60 of 60 pages exact, 1,560 of 1,560 lines.
- Item documents (`BindItem`, reflow) of the six whole items of the 2,165-page ground-truth set from the same page
  records: md, txt, html, doclang, json identical. Item texts (`--item-texts`) of two whole items run again: the
  text files identical; the JSONL rows differ only in their trace context.

## Four kraken changes measured one by one (#1, 2026-11-04, HF Jobs L4)

Each change alone against the same baseline, the 2,165-page ground-truth set, one `l4x1` Job
per variant (one server reads every page), `--recipe squiddle`. Branches: kraken fork `perf/line-prefetch`
(b4f651aa), `perf/early-seq-lens` (cf21c0cd), stock 3d235ee8; linecaster `perf/kraken-sort-by-width`,
`perf/kraken-compile`; each variant a `measure/...` branch whose only commit is the kraken pin.

| change | recognition, steady state | vs baseline | text changed | shortest body lines (width/height < 2) | CERdip | CERread | recall | furniture |
|---|---|---|---|---|---|---|---|---|
| baseline (stock 3d235ee8) | 0.802 s/page | | | | 0.0576 | 0.0419 | 0.9754 | 0.8491 |
| 1 line prefetch | 0.733 s/page | −8.5 % | none | none | = baseline | | | |
| 2 seq_lens before the forward pass | 0.786 s/page | −1.9 % | none | none | = baseline | | | |
| 3 batching by line width | 0.728 s/page | −9.2 % | 0.220 % | 8.25 % of their characters | 0.0577 | 0.0416 | 0.9752 | 0.8441 |
| 4 torch.compile of the backbone | 0.719 s/page | −10.3 % | 0.021 % | 0.05 % | 0.0576 | 0.0419 | 0.9754 | 0.8485 |

- Changes 1 and 2 are in main (fork 48eecb78, both together; −12 % measured earlier on 300 pages).
- Change 3 reads the shortest lines (single characters, page numbers, the last word of a paragraph) worse:
  in a batch of only narrow lines they get little padding. Not adopted; batching stays as kraken forms it.
- Change 4 keeps the CER and the short lines; its 163 s warm-up per server pays off from about 2,000 pages
  per server (0.083 s saved per page). Candidate for long runs, ideally with the compile cache kept between
  Jobs (`torch.compiler.save_cache_artifacts` / `load_cache_artifacts`).
- Earlier round of the same day with 4 Jobs per variant: queueing for free L4s made launch-to-finish times
  misleading; the Jobs' own runtime is what counts.

## Later: hardware acceleration across platforms (parked 2026-11-04)

Ideas, none measured:

- kraken stays on PyTorch: CUDA (with torch.compile and its cache), MPS on Macs, CPU elsewhere; one model
  file, kraken's own code. AOTInductor `.pt2` packages per GPU type would remove the warm-up.
- PaddleX models: every one in the chain has a `PaddlePaddle/<name>_safetensors` variant whose architecture
  transformers 5.12 implements (pp_doclayout_v3, pp_ocrv6_*_det, slanet, pp_lcnet, pp_formulanet); PaddleX's
  transformers engine would put the whole chain on torch and drop onnxruntime-gpu. Changes numerics (goldens
  were recorded on ONNX Runtime) and speed is unknown.
- ONNX Runtime execution providers (TensorRT, CoreML, OpenVINO, DirectML) for platforms without a usable
  PyTorch; costs an export path of our own for kraken.
- VLMs off NVIDIA: llama.cpp (`llama-server`, GGUF) or MLX-VLM behind the same OpenAI interface as `chat.v1`;
  GGUF files as `converted` / `quantized` model documents, each with its own evidence. GGUF does not suit
  kraken (no graph importer in ggml; a reimplementation).

## kraken: batching by line width and torch.compile (#1, 2026-11-04: aarch64 GB10, HF Jobs L4)

Changes 3 and 4 of that issue as options of `kraken.recognition.v1`, off by default: `sort_by_width` (a
page's lines go to kraken widest first, by box width / height, and come back in line order) and
`compile_backbone` (`torch.compile(dynamic=True)` of the PP-OCRv6 backbone). Measured with `--recipe squiddle
--set recognition....`, against the same commit without them (93bac25, kraken fork 48eecb78).

The 2,165-page ground-truth set, HF Jobs `l4x1`, 4 tasks of 541 pages each, served:

| | recognition, steady state | compile warm-up | characters changed | CERdip | CERread | recall | furniture |
|---|---|---|---|---|---|---|---|
| kraken-ppocrv6-medium@1 | 0.724 s/page | | | 0.0576 | 0.0419 | 0.9754 | 0.8491 |
| + sort_by_width | 0.650 s/page (−10 %) | | 0.220 % | 0.0577 | 0.0416 | 0.9752 | 0.8441 |
| + sort_by_width + compile_backbone | 0.529 s/page (−27 %) | about 167 s per server | 0.223 % | 0.0578 | 0.0416 | 0.9752 | 0.8437 |

- Scored with the leaderboard's frozen scoring harness (leaderboard lane). sample-60 and tables-7 move the same way
  (sample-60 CERread 0.0268 → 0.0265). On sample-60 locally (aarch64 GB10, in-process): 0.716 → 0.631 → 0.530 s/page,
  compile warm-up about 52 s.
- Characters change much more than on the single book of the issue (0.03 %): other batches pad differently, which
  flips CTC near-ties; word boxes move more often than text.
- The furniture drop is the typography step: it removes 70–72 page numbers as uncertain instead of 61, because
  short page-number lines come out with other text or confidence in other batches. Its rule was tuned on the
  old batching.
- Compiling pays off only for long-lived servers: about 167 s of warm-up against 0.12 s saved per page, so
  from about 1,400 pages per server. With 541 pages per task the compiled run used more GPU time in total
  than sorting alone.
- Neither option was adopted from this round: `sort_by_width` was dropped (it is not in linecaster), and
  `compile_backbone` is an option off by default (see the entry above for both measured on their own).

Where the characters change with `sort_by_width` (full ground truth, against kraken's own batching):

| region | line width / height | lines | lines changed | characters changed | mean confidence |
|---|---|---|---|---|---|
| body | < 2 (one or two characters) | 3,430 | 569 | 8.25 % | −0.119 |
| body | 2–5 | 2,961 | 242 | 1.76 % | −0.012 |
| body | 5–10 | 7,093 | 762 | 0.94 % | −0.001 |
| body | 10–20 | 26,590 | 1,831 | 0.21 % | ±0 |
| body | ≥ 20 | 27,229 | 1,087 | 0.07 % | ±0 |

Sorted widest first, a page's narrowest lines end up together in the last batch, only a few dozen pixels wide;
in kraken's order they share batches with full-width lines and are padded to them. Page numbers dropped only with
sorting (17; 6 the other way): `viii` (0.97) → `rii` (0.60), `vii` (0.99) → `ru` (0.69), `ii` (0.95) → empty,
`xj` (0.97) → empty, `IX` (0.99) → `IX` (0.74), `G3` (0.91) → `G3` (0.67). The typography rule (mean character
confidence below 0.75) only reveals it; lowering it would keep the wrong readings.


## kraken line prefetch (#1, 2026-11-04: aarch64 GB10, x86_64 RTX 4000 SFF Ada, HF Jobs L4)

Issue #1: kraken's recognition loop makes the CPU wait for the GPU on every line (the
empty-line check on a tensor built on the device) and once per batch (`seq_lens` copied after the backbone is
queued). Fork commit `48eecb78` (storytracer/kraken, `perf/recognition-prefetch`): lines are extracted,
transformed and checked on the CPU in a producer thread, `seq_lens` goes to the device before the forward pass,
and the last partial batch is recognized also when a page ends in empty lines (stock kraken flushed it only on an
append, so such lines were never recognized and the page failed `zip(strict=True)`). Batches are formed as
before, so the output is unchanged.

| machine | recognition, pinned `3d235ee8` | patched `48eecb78` | output |
|---|---|---|---|
| aarch64 GB10, sample-60 in-process | 0.73 s/page | 0.77 s/page (noise) | goldens 1,560/1,560 lines |
| x86_64 RTX 4000 SFF Ada, sample-60 in-process | 0.647 s/page (warm) | 0.61 s/page (−6 %) | goldens 1,560/1,560 lines |
| HF Jobs `l4x1`, the ground-truth set's first 300 pages, served | 0.903 s/page | 0.793 s/page (−12 %) | 300/300 pages, 7,276/7,276 lines identical |

The GB10 gains nothing: its CPU does not stall the GPU the way an L4 host does. On the L4 recognition sets the
pace (served wall 274 s → 242 s). Not done yet (they change 0.02–0.03 % of characters): batching by line width
and `torch.compile` of the backbone, changes 3 and 4 of the issue.

Same change set: TablesStep and FormulasStep send no image for a page without their regions (the engines still
record the step), a malformed served answer is that page's error, the readiness probe uses the step route, and
`HFImageDatasetReader` raises when a repository has no Parquet files (an image folder such as
the ground-truth set silently read 0 pages with `--dataset`; it is read as `hf://datasets/...` IMAGES).

## Specs are reference documents (2026-11-04)

`specs/` describes what is, without history. Moved here from them:

- The catalog's role models: HTRMoPo v1 and Hugging Face model cards (Markdown with YAML front matter),
  OCR-D (functional steps, declared resources, provenance per processing step), Docling (typed options per
  engine, one factory per stage), spaCy (versioned registry names that stay resolvable), Datalab's marker,
  surya and chandra (configuration declared once, evidence with its source), the uv-scripts
  `ocr/models.json` (one catalog, support levels), an evaluation tool's profiles (label mappings as data).
- WebP encoding effort, one measurement on an aarch64 GB10 machine, a 3996 × 5964 newspaper JPEG: decode 0.09 s;
  encode effort 0: 1.67 s / 17.2 MB, 25: 1.99 s / 17.1 MB, 80: 7.0 s / 16.6 MB, 100: 9.6 s / 16.4 MB. Effort 0 is 4×
  faster for 4 % more bytes; left at Pillow's default (80) until measured on a broader sample.
- The kraken source lesson (a source applies only to direct dependencies) is under "Lessons" below.

## launch.py: recipes and models by name (2026-11-04, aarch64 GB10)

`uv run launch.py squiddle IMAGES OUT` and `uv run launch.py chandra-ocr-2 IMAGES OUT`: a recipe names its
pipeline (`chain.v1`), a whole-page preset runs in `vlm.v1`; `launch.py` finds the script declaring that
`PIPELINE` (`catalog.code.pipelines`, ast) and execs `uv run --script pipelines/<script>.py ... --recipe NAME`
(or `--vlm NAME`), so the pipeline keeps its own environment and launch.py needs only linecaster's core.
Discussed and dropped: the kind of entry as first argument (`model`/`recipe`/`pipeline`), `server` and `cluster`
words, and names such as run.py (`uv run run.py`), recipe.py, transcribe.py, read.py, lc.py. Own combinations
use the pipeline scripts directly. Names stay unambiguous: the catalog already refuses an id used by a preset
and a recipe. A preset that is one step (a line recognizer, a region reader) gets a hint instead: which pipeline
and flag, and the recipes that use it. Checked: `--dry-run` builds the squiddle chain with its recipe record and
chandra-ocr-2's vLLM command at the pinned revision.

## One catalog (2026-11-04, aarch64 GB10)

The catalog is one folder, `src/linecaster/catalog/data/`: the engine packages' catalogs (kraken, PaddleX,
Tesseract: 21 models, 18 presets, their evidence) and the derivative's (the recipe `squiddle` and its 4 evidence
records) were moved into it, and the entry-point group `linecaster.catalog`, `--with-dir` and recipe file paths
went. Presets are grouped by step (`presets/<step>/<id>.md`, the folder checked against `step`). "kind" is gone: a
preset names its engine, `engine: kraken.recognition.v1`, with `options:` beside it; a recipe its pipeline,
`pipeline: chain.v1`; code ids end in `.v<n>` (were `/1`). The generated docs are grouped by kind
(`docs/catalog/{engines,models,presets/<step>,pipelines,recipes}`); engine and pipeline pages are read from the
source with `ast`, since no environment has every engine.

- The lock was re-released from scratch: the functional content changed shape (`engine` a string, `options` at
  the top), so every hash changed; the editions stayed (39 presets at edition 1, `slanet-plus` at 2; `squiddle@1`).
  `slanet-plus@1` was dropped from the lock; no run had recorded it. This is the last re-baselining before runs
  record editions in earnest; from now on a released edition changes only as a new edition.

## Pipelines and recipes (2026-11-03, aarch64 GB10)

"Recipes" were pipeline shapes with slots, and since the defaults went they chose nothing: renamed `pipelines/`
(`chain.py`, kind `chain/1`; `vlm.py`, `vlm/1`; `cuda_probe.py` to `tools/`; since 2026-11-05
`transcribe_chain.py` and `transcribe_vlm.py`, and the item stage `items.py` is `bind.py`). A **recipe** is now a catalog
document: a pipeline kind, a preset edition for each slot, options; edition, provenance, support level and evidence
like presets. Its hash covers its presets' hashes (and so their model pins), and it is released only on released
preset editions. `--recipe id[@edition]` or a recipe file fills the slots and options the command line leaves open;
what the command line gives instead goes into the run record as overrides. `RecipeStamp` (before the first writer)
puts the recipe edition and hash into every `ModelInfo`, so page rows and ALTO/PAGE/hOCR name it.

- The derivative ships `squiddle@1` (its catalog, entry point `linecaster.catalog`): pp-doclayoutv3@1,
  pp-ocrv6-medium-det@1, kraken-ppocrv6-medium@1, slanet-plus@2, pp-formulanet-plus-l@1, text reflow. Its evidence:
  the goldens reproduced (sample-60 1,560/1,560 lines and tables-7 651/651, in-process and served).
  `uv run pipelines/chain.py IMAGES OUT --recipe <the derivative's checkout>/catalog/recipes/squiddle.md` on
  sample-60: goldens 1,560/1,560, `squiddle@1` in every ALTO step and in `run.yaml`. The derivative's command stamps the
  recipe when its options are the recipe's.
- The recognizer comparison stays preset evidence (it varied one preset), with the rest of the pipeline as
  `context`.

## The catalog: models, presets, evidence (2026-11-03, aarch64 GB10)

`docs/reference/catalog.md` is the design; built in parallel by three agents (engines, VLMs, provenance) on top of the
foundation (`linecaster.catalog`). In the checkout: 39 models with their upstream cards copied verbatim, 39 presets
released as edition 1 (`slanet-plus` also edition 2), 39 evidence records.

- **PaddleX downloads** `PaddlePaddle/<name>_onnx` (ONNX Runtime) or `_safetensors` (transformers) from Hugging Face
  at `main`, without a revision (PaddleX 3.7.2, `official_models.py`), into `~/.paddlex/official_models/`. Those
  repositories are what is pinned now; the engines load the pinned snapshot with `create_predictor(model_dir=...)`.
  Identical outputs to PaddleX's own download on 3 pages (layout V3 and plus-L, lines, PaddleX small rec, SLANet_plus
  table HTML, PP-FormulaNet_plus-L LaTeX); tiny/small det, tiny/medium rec and PP-FormulaNet-L not compared.
- **kraken's PP-OCRv6 models** are trained from scratch on an architecture adapted from PP-OCRv6 (their card), not
  converted from PaddleOCR's weights: `derived_from` is only the Zenodo mirror relation.
- **Tables** need four models; `submodels` (by PaddleX name) pins the classifier and the two cell detectors next to
  SLANet_plus, so their file hashes are part of the edition (`slanet-plus@2`; `@1` held them as an option).
- **Hashes cover only what a document states** (`exclude_unset`): adding the server fields `revision_flag`,
  `pin_ignore`, `server_packages` and `draft` to `Serve` had changed every chat preset's hash through the defaults.
  The current editions were released again under that rule before the first push.
- **Chat presets**: requests, server commands and Jobs plans byte-identical to the former spec classes for all 20
  models, with two deliberate changes: LightOnOCR-3 (0.8B, 4B) now names `vllm/vllm-openai:v0.30.0`, the version the
  leaderboard validated them with (the old recipe used 0.26.0, with which LightOn says they loop); Unlimited-OCR-2's
  recorded `sglang_version` is now the wheel that runs (`0.5.20.dev10+g8d62f5fb9c`).
- **Licenses to check by hand** (as the cards state them): chandra "AI Pubs Open RAIL-M License (Modified)",
  Nemotron `OpenMDW-1.1`; SmolDocling's front matter says CDLA-Permissive-2.0, its text Apache-2.0.

Parity of `recipes/chain.py` through presets (pinned PaddleX snapshots, kraken from its pin) with the derivative's
goldens (recorded on the GB10 machine): sample-60 1,560/1,560 lines and 60/60 pages exact in-process (80 s), served
with the server in the task (71 s) and against `uv run recipes/chain.py serve` (47 s); tables-7 651/651 in-process and
served. Served pages carry preset, edition, hash and the step's start time in every `ModelInfo`.

## One recipe per pipeline (2026-11-03, aarch64 GB10)

The scripts had made the environments self-contained, but the pipelines were still copied once per machine: the
squiddle chain three times (`examples/`, `recipes/ray/`, `recipes/hf-jobs/`), its model list four times (with
`examples/squiddle_models.json`), the chat page and region pipelines twice each, the kraken + PaddleX metadata block
twice. Now:
- `recipes/chain.py`: layout → lines → assignment → kraken, PaddleX PP-OCRv6 or Tesseract (`--recognizer`) → NFC →
  tables → formulas → typography → document, with --files/--exports/--texts. One environment holds all three
  engines (torch + PaddleX + tesserocr resolve together), so the PaddleX + Tesseract combination needs no script of
  its own. The HF Jobs chain now runs NFC, typography and page composition too (it wrote raw page rows before).
- `recipes/vlm.py`: a chat VLM per page, or per PP-DocLayoutV3 region with `--regions` (MiniCPM-OCR is one model it
  takes; its DSpark draft comes from the spec, its image from the recipe's table of validated images).
- `linecaster.runtime.run` gives both the same command line: `--on local|ray|hf-jobs`, `--backend in-process|served`
  (default in-process here, served on Ray and Jobs), `--endpoint`, `serve` (`linecaster serve` with the recipe's
  models, picked by its options) and `ray ...` (Ray's CLI from the recipe's environment). Page rows go to
  `OUT/rows/${rank}.jsonl.gz`, logs to `OUT/logs`, on every machine.
- `ServeModels(script=...)` starts a recipe's `serve`; `jobs.dependencies(commit, script)` reads a recipe's metadata
  (`engines=False`: linecaster alone, for page VLMs in a vLLM image).
- `point_to_gpu` moves each server and loopback client up by the GPU index instead of setting all of them to
  `base_port + GPU`: with a layout server and vLLM in one task, the old rule put both on the same port.
  `base_port` is gone from `RayGPUExecutor` and `GPUJobsExecutor`.
- Dry runs (`--dry-run`) give the old recipes' plans: images, `--with` lists and server commands (MiniCPM: the
  same vLLM flags with the DSpark speculative config, `outside_venv`, 0.8 of the GPU).
- Both recipes carry `linecaster[ray]` for `--on ray`; `dependencies()` leaves the extra out of a Job's list. Adding
  Ray and Tesseract changed no version in the lock the goldens run used (packages added only).

Checked on the GB10 machine against the derivative's goldens and on Ray (3 pages, one task):

| run of `recipes/chain.py` | sample-60 lines (box + words) | tables-7 lines | wall, sample-60 |
|---|---:|---:|---:|
| in-process | 1,560/1,560, 60/60 pages exact | 651/651, 7/7 | 88 s |
| `--backend served` (the task starts `serve`) | 1,560/1,560, 60/60 pages exact | 651/651, 7/7 | 63 s |
| `--endpoint` against `uv run recipes/chain.py serve` | 1,560/1,560, 60/60 pages exact | | 47 s |
| `--on ray`, Ray started with `uv run recipes/chain.py ray start` | 3/3 pages written | | |

`recipes/vlm.py` on the GB10 machine (vLLM 0.21.0, started in the task, `--gpu-memory-utilization 0.3`), sample-60:
- page mode, LightOnOCR-2-1B: 60/60 pages in 232 s, CERread 0.0372 (CERdip 0.0738, 4 of 60 truncated), leaderboard lane.
  The old HF Jobs recipe's run of the same model scores 0.0403 with today's harness; sampling is at temperature 0.2.
- `--regions` (PP-DocLayoutV3 in-process + LightOnOCR-2-1B per region): 60/60 pages in 584 s, no errors, 418 regions
  read; 64 of them ran into the token limit (LightOnOCR's known looping on crops). Not scored.
- HF Jobs: a LightOnOCR page smoke was launched; MiniCPM regions was canceled while it waited for an L4.

## Self-contained uv scripts instead of environment folders (2026-11-03, aarch64 GB10)

`envs/kraken-paddlex` and `envs/paddlex-tesseract` are gone. Every example, recipe and server is a uv script
with inline metadata (PEP 723) and a `<script>.py.lock` next to it:
- `servers/kraken-paddlex.py`, `servers/paddlex-tesseract.py`: `linecaster serve` with one engine combination.
  `ServeModels(script=...)` starts one with `uv run --script`; `linecaster.runtime.jobs.dependencies(commit, engines)` reads
  its metadata for a Job's `--with` list (sources as URLs at the commit, pins for the packages its lock resolves), so
  the pins live in one place per combination instead of in `jobs.py`.
- `examples/squiddle_chain.py` carries the kraken-paddlex block (in-process needs the engines); the VLM examples and
  the HF Jobs launchers carry core linecaster only; `recipes/ray/squiddle_chain.py` carries linecaster with Ray and
  runs Ray's own CLI from its environment (`uv run recipes/ray/squiddle_chain.py ray start --head`), because Ray's
  `uv run` support (`RAY_ENABLE_UV_RUN_RUNTIME_ENV`) does not handle scripts: workers came up without Ray. It is
  switched off in the recipe. Checked on the GB10 machine: 3 pages, one task, server started from the script.
- Locking the scripts afresh moved seven packages the old env lock had older: the CUDA libraries (cuBLAS 13.8,
  NVRTC/runtime 13.4, cuFFT 12.4, cuRAND 10.4.4), cuDNN 9.27 (paddlex-tesseract) and scipy 1.16–1.18,
  scikit-image 0.26. All are pinned back to the goldens' versions in `constraint-dependencies`, the same list in
  every engine script; the kraken-paddlex lock then differs from the old env lock only in soupsieve, pyarrow and
  ujson.
- uv's `required-environments` is not accepted in script metadata. `tests/test_scripts.py` stands in: same pins and
  kraken source in every script, a lock per script, the pins resolved, and Linux wheels for aarch64 and x86_64 for
  every package with platform wheels. One allowed source build: coremltools (kraken's CoreML format, no aarch64
  wheel; built from source on aarch64 before as well; not on the recognition path).

Parity of the scripts with the derivative's goldens (recorded on the GB10 machine): `uv run
examples/squiddle_chain.py`, in-process and served through `uv run servers/kraken-paddlex.py`:

| run | sample-60 lines (box + words) | tables-7 lines | wall, sample-60 |
|---|---:|---:|---:|
| in-process | 1,560/1,560, 60/60 pages exact | 651/651, 7/7 | 89 s |
| served | 1,560/1,560, 60/60 pages exact | 651/651, 7/7 | 48 s |

## More line recognizers: PaddleX PP-OCRv6 and Tesseract (2026-11-03, aarch64 GB10)

Two more engines for `RecognitionStep`, next to kraken:
- `linecaster_paddlex:PaddleRecognitionModel`: PaddleOCR's own PP-OCRv6 recognizers (`PP-OCRv6_{tiny,small,medium}_rec`)
  on PaddleX's ONNX Runtime engine. Lines cut as PaddleX's OCR pipeline cuts them (minimum-area rectangle, warped upright),
  sorted by aspect ratio, `batch_size` 8. Words: the text split at whitespace (kraken's rule), placed along the line
  rectangle by the CTC columns of their characters (PaddleX's `return_word_box` mapping); no per-word confidence.
  PP-OCRv5 left out on purpose: PP-OCRv6 only.
- `linecaster_tesseract:TesseractRecognitionModel` (new package `linecaster-tesseract`): Tesseract 5.5.3 LSTM through
  tesserocr 2.12.0 (the wheels bundle Tesseract and Leptonica on Linux aarch64 and x86_64), page segmentation mode 7 on
  each line's bounding box, outside the polygon painted white, 4 px white padding. Words, boxes and confidences from
  Tesseract. Language data from tessdata_best (default) or tessdata_fast, pinned to a commit, cached in
  `~/.cache/linecaster/tessdata`. On the CPU, one line at a time.
- New engine combination PaddleX + Tesseract (no torch, so no PP-FormulaNet there); now the script
  `servers/paddlex-tesseract.py`.

Comparison on the 60-page sample: the same chain for every row (PP-DocLayoutV3 → PP-OCRv6 medium detection → line
assignment → *recognizer* → NFC → tables → typography → document → Markdown), in-process, one task, scored as-is
(no postproc) with the leaderboard's frozen scoring harness (`score_dataset`). Wall includes model loading.

| recognizer | CERdip | CERread | recall | wall, 60 pages |
|---|---:|---:|---:|---:|
| kraken PP-OCRv6 medium (bf16) | 0.0341 | 0.0270 | 0.9508 | 72 s |
| PaddleX PP-OCRv6 medium | 0.0387 | 0.0315 | 0.9343 | 49 s |
| PaddleX PP-OCRv6 small | 0.0375 | 0.0300 | 0.9351 | 44 s |
| PaddleX PP-OCRv6 tiny | 0.0446 | 0.0376 | 0.9123 | 33 s |
| Tesseract best, `script/Latin` | 0.0430 | 0.0364 | 0.9131 | 132 s |
| Tesseract best, `eng` | 0.0595 | 0.0516 | 0.8570 | 110 s |

- kraken's port reads better than PaddleX's own runtime of the same model family on every volume but one (book D); the
  likely difference is the line image (kraken's polygon-based extraction against PaddleX's rectangle warp). Not
  investigated further.
- PaddleX small is as good as medium here (0.0300 vs 0.0315): a 60-page sample, no conclusion about defaults.
- Tesseract with the Latin script model is close to PP-OCRv6 tiny; `eng` alone loses on the German, French, Latin and
  Russian volumes. Tesseract is the slowest (CPU, single process); more tasks would spread it over cores.
- No default changed.

## A derivative's features in linecaster (2026-11-03, aarch64 GB10)

Every feature and option of the derivative's 0.3 paddle pipeline (its legacy command with the paddle pipeline), where it
lives now. eynollah and kraken's blla pipeline are out of scope (they stay in the derivative's legacy command).

| 0.3 feature or option | status | where |
|---|---|---|
| PP-DocLayoutV3 layout, learned reading order | already in linecaster | `LayoutStep` + `PaddleLayoutModel` |
| `--layout-model PP-DocLayout_plus-L` (XY-cut order) | already in linecaster | `PaddleLayoutModel(model_name=...)` |
| `--layout none` (the page is one text region) | missing, built | `SingleRegionLayout` (`blocks/layout/single_region.py`) |
| PP-OCRv6 detection, `--det-model`, `--unclip-ratio` | already in linecaster | `LinesStep` + `PaddleLineModel(model_name, unclip_ratio)` |
| lines into regions, orphan rows, pictures skipped | already in linecaster | `AssignLinesToRegions` (`formulas_separately=False` without formulas) |
| kraken recognition, `-m tiny/small/medium/path`, `--batch-size`, `--precision` | already in linecaster | `RecognitionStep` + `KrakenRecognitionModel` |
| `--device` | already in linecaster | `device` of every engine (in-process; the server's otherwise) |
| `--rtl` | already in linecaster | `KrakenRecognitionModel(text_direction=...)`, `ComposePage(rtl=)`, `BindItem(rtl=)` |
| `--tables` | already in linecaster | `TablesStep` + `PaddleTableModel` |
| `--formulas`, `--formula-model` | already in linecaster | `FormulasStep` + `PaddleFormulaModel` (29/29 formulas identical, 82e2e7b) |
| `--typography` (heading levels, demotion, headline split, drop capitals, uncertain page numbers) | already in linecaster | `Typography` |
| NFC of the as-written text | linecaster's choice (0.3 kept kraken's decomposed text) | `NormalizeUnicode` |
| `--text reflow/lines` | already in linecaster | `ComposePage(text=)`, `BindItem(text=)` |
| `--sections` | per item already; per page missing, built | `BindItem(sections=)`; `ComposePage(sections=)` |
| `--dividers` | per item already; per page missing, built | `ComposePage` keeps the item → region map (`extra["docling_region_of"]`); `dividers` on `PageFilesWriter` / `PageExportsWriter` |
| `--furniture` | already in linecaster | `furniture` on the export writers (the items always sit in Docling's furniture layer) |
| `--per-document` | already in linecaster | `BindItem` + `ItemExportsWriter`; `ImageFolderReader(item_id=, sequence=)` (built) puts a run's pages into one item in name order |
| `-f md, txt, json` | already in linecaster | `PageFilesWriter`, `PageExportsWriter`, `ItemExportsWriter`; JSON now formatted as docling's `save_as_json` |
| `-f html, doclang` | missing, built | `linecaster.formats.docling.export` / `to_html` / `to_doclang` in all three writers |
| `-f hocr, alto, page` | already in linecaster | linecaster's lxml serializers (not kraken's, by design) |
| `--detail word` | already in linecaster | the serializers' default (words are the finest level) |
| `--detail line` | missing, built | `PageFilesWriter(detail="line")` (a word-less copy to the serializers) |
| `--detail glyph` (0.3's default) | not in linecaster, by design | no glyph level in the data model; the derivative's default becomes `word` |
| `--plots` | missing, built | `linecaster.images.plots.plot_layout`, `PageFilesWriter` format `plot` (`<page>.layout.jpg`) |
| processing settings in ALTO | already in linecaster | `ModelInfo` per step → ALTO `Processing` |
| output naming `<name>.<suffix>.<ext>`, next to the image unless `-o`; per-document stem (folder name, file stem or `document`); `--suffix`; format `auto` = md | derivative-specific | the derivative's `cli.py` (writer `suffix=`, a `PageFilesWriter` subclass for "next to the image") |
| status lines (typography and reflow counts), failed pages listed at the end | derivative-specific | datatrove's stats instead; an in-process exception stops the task (served errors are recorded per page) |

**Parity.** A derivative's command (its 0.4, now built from these blocks) against its legacy command on the same
machine and environment: sample-60 + tables-7 (67 pages), a folder of 17 mixed scans, a folder of 12 formula
pages, each in 7 configurations (defaults with every format and plots; `--text lines --furniture --sections
--dividers --detail line`; `--no-typography --no-tables --no-formulas`; `--layout none`;
`--layout-model PP-DocLayout_plus-L`; reflow with `--dividers --furniture`; `-m small --det-model
PP-OCRv6_small_det --unclip-ratio 2.0 --batch-size 4` on scans and formulas), and the 6 books × 10 pages per
document in 4 combinations. Each run twice: as shipped, and with NFC switched off (`--no-nfc`, hidden, for
parity only). Scripts and outputs outside the repository.

- **Without NFC every document format and the plots are byte-exact** in every configuration on every page:
  md, txt, html, doclang, json, layout.jpg (96 pages × 7 configurations, c7 on 29 pages), with `--furniture` aside
  (below).
- **As shipped (NFC):** md, txt, html and doclang are byte-exact or exact after NFC of 0.3's text on every page,
  except where NFC changes reflow decisions: 10 division marks on 9 sample-60 pages (`mâ-`/`choire`,
  `géné-`/`ral`, `exté¬`/`rieur`, ...), removed now because the character before the mark is a letter after
  NFC and a combining accent (Mn) in 0.3's decomposed text. The same cause as on the books (above). JSON:
  the same plus charspans (lengths of NFC strings).
- **`--furniture` in json and doclang:** 0.3 moved page headers and footers into the body layer; linecaster keeps
  them in Docling's furniture layer and the export chooses. JSON differs in `content_layer` of those items,
  DocLang by the `<layer value="furniture"/>` marker; md, txt and html are exact. Kept by decision.
- **JSON provenance clamping:** docling-core clamps provenance boxes to the page whenever it validates a
  document; 0.3's JSON had them clamped only when Markdown or text was exported before JSON in the same run
  (`-f json` alone kept a picture box at y = −3). `DocumentBuilder.build` now validates (clamped always); 4
  sample-60 pages with picture boxes past the edge are exact since.
- **JSON charspans and DocLang:** docling-core's DocLang export rewrites the provenance charspans of the document
  it serializes; 0.3 saved its JSON from that same document, so with `doclang` before `json` in `-f` 0.3's
  charspans changed (reflow paragraphs: every row's span restarted at 0). linecaster writes JSON from the
  stored document and `to_doclang` works on a copy, so the order of formats does not matter; the parity runs
  list json before doclang.
- **hocr, alto, page** are linecaster's serializers, so the files differ by design; read back with linecaster's
  readers, every line on every page has the same text, line box and word boxes (words: NFC text and box),
  with three conventions of kraken's serializer set aside: kraken writes whitespace runs as words of their
  own (hOCR, PAGE), collapses double spaces between ALTO Strings, and clips line boxes to width − 1 / height − 1
  (one `--layout none` page whose line reaches the right edge). At `--detail line` kraken's ALTO has one
  box-less String per line, linecaster's one String with the line's box: same text and line boxes.
- **Served** (`linecaster serve` with the derivative's models config, defaults, 96 pages and the 6 books): identical to
  in-process.
- **Per document** (6 books, reflow / lines + sections + dividers / reflow + dividers + furniture / lines +
  furniture): without NFC md, txt, html, doclang and json identical for all 24 (furniture layer aside); with NFC
  the lines combinations exact after NFC, reflow 4/6 books (book D, book F: the NFC
  division marks, as above).

- `--rtl` and `--device cpu` on one page (iiif_page_8, left to right): exact without NFC (kraken on the CPU at
  32-true, the PaddleX models on ONNX Runtime's CPU provider).

Not exercised here: a right-to-left page, `--device tensorrt` / `coreml`, `-m` with a model file path,
PP-FormulaNet-L, x86_64.

## Unlimited-OCR, Unlimited-OCR-2, PaddleOCR-VL-1.6, GLM-OCR specs; SGLang in ServeChatModel (2026-11-03, not yet run)

- Four page specs from the leaderboard drivers: `models/unlimited_ocr.py` (`UnlimitedOCR` on vLLM 0.26.0,
  `UnlimitedOCR2` on SGLang), `models/paddleocr_vl.py`, `models/glm_ocr.py`. Checkpoints pinned to the
  leaderboard's; completions verbatim, the leaderboard's post-processing (grounding strip, Baidu's Markdown
  converter, strip) left to the harness.
- PaddleOCR-VL-1.6 is run as the leaderboard runs it: the VLM alone on the whole page with `OCR:`, the
  recipe's client-side `smart_resize`; not PaddleOCR-VL's PP-DocLayout + VLM pipeline.
- `ServeChatModel` starts SGLang for a spec with `server = "sglang"`: `python -m sglang.launch_server
  --model-path ... --enable-metrics`, the spec's `server_env` through `env`, its `server_packages`
  installed into the server's Python with `uv pip install --python` first, and `gpu_memory_utilization`
  passed as `--mem-fraction-static`. `recipes/hf-jobs/chat_page.py` runs SGLang specs with
  `outside_venv` (the image's `/opt/sglang/bin/python3`).
- Unlimited-OCR-2 cannot take `--revision` (Baidu's SGLang then skips its tokenizer fix-up). The leaderboard
  refused to start unless the default branch was the pinned commit. Since then the default branch has
  moved, with README and wheel changes only. So `revision_flag = False` makes the serve block compare
  git blob ids between the default branch and the pin, ignoring README, `.gitattributes`, `wheel/` and
  PDFs. Baidu's dev10 wheel is still read from the pinned revision (on main it is replaced by dev13).
- `lmsysorg/sglang:v0.5.20-cu130` (amd64) from its image config: SGLang in `/opt/sglang` (Python 3.12),
  first on PATH. The leaderboard's own Job ran `hf jobs uv run` on it, so uv is there.
- Not checked: any of the four on a GPU, and Unlimited-OCR-2 on an L4. The leaderboard ran it on an RTX PRO
  6000 with the card's flags for an 80 GB A800 (`--mem-fraction-static 0.7`, CUDA graphs up to 16384
  prefill tokens).

## Qwen3.5-9B, Qianfan-OCR, DeepSeek-OCR and DeepSeek-OCR-2 specs for ChatPageStep (2026-11-03, not yet run)

- `models/qwen35.py`, `models/qianfan_ocr.py`, `models/deepseek_ocr.py` reproduce the leaderboard drivers; each
  module's docstring lists request, image handling, sampling and serve flags. Checkpoints pinned; vLLM 0.26.0.
- Qwen3.5-9B is the leaderboard's "greedy + card penalties" row: `neutral` prompt, temperature 0.0 with
  presence_penalty 1.5 and repetition_penalty 1.0, JPEG q95 capped at 2048 x 1024 px of area.
- Qianfan-OCR and DeepSeek-OCR send the page at full resolution. Qianfan gets the image bytes as received
  (the sample-60 lossless WebP decodes to the same pixels the leaderboard's dataset bytes did); DeepSeek gets
  RGB PNG/JPEG as is and anything else as RGB PNG.
- DeepSeek: vLLM's default resolution (Gundam), grounding prompt, `skip_special_tokens` false; the card's
  n-gram guard is registered at boot (`--logits_processors`, kept last on the command line) and set per
  request (`vllm_xargs`). v2 uses v1's processor and `<td>`/`</td>` whitelist, as the v2 vLLM recipe does;
  that the ids are the same tokens in v2's tokenizer is not verified.
- Completions are kept verbatim. The leaderboard's post-processing stays in the harness: `unwrap_fence` (Qwen),
  the `</think>` strip (Qianfan), `deepseek_strip_grounding` (both DeepSeeks, postproc 3).
  `qwen35.unwrap_fence` and `deepseek_ocr.strip_grounding` apply the same rules for other consumers.
- Memory: Qwen3.5-9B has 18.0 GiB of bf16 weights. The leaderboard ran it on an L40S at 0.9. On a 24 GB card
  (L4, A10G) about 2 GiB would be left at 0.9 for activations, the vision encoder and the KV cache. That
  fit has not been tested. The other three need 6 to 9 GiB of weights and ran on an A10G.

## SmolDocling and Nemotron 3.5 Parse specs; three leaderboard rows that are not chat models (2026-11-03, not yet run)

`SmolDocling` (`ds4sd/SmolDocling-256M-preview`) and `NemotronParse35` (`nvidia/Nemotron-3.5-Parse`) follow the
leaderboard's drivers (module docstrings). Not checked on a GPU yet.
- SmolDocling answers in DocTags. The completion is kept verbatim; `parse` also stores the leaderboard's conversion
  (docling-core, body + furniture, no image placeholder) in `extra["markdown"]`. The leaderboard converted with
  docling-core 2.89; the lock has a newer one, so a scorer that wants the leaderboard's exact text should compare
  both.
- Nemotron 3.5 Parse needs NVIDIA's vLLM plugin from the model repo. `ChatModel.serve_setup()` is a bash script that
  `ServeChatModel` runs before `vllm serve`. For this model it installs the plugin into the Python that runs `vllm`,
  the way the leaderboard's install script does. The card's flags include FlashAttention 3, a Hopper kernel: the
  leaderboard ran on an H200, and the flags as they are will not run on an L4. The leaderboard's Markdown rendering
  imports code from the model repo, so `parse` does not call it; `to_markdown` reproduces it.
- Not chat models, so no spec. They do not fit `ChatPageStep`:
  - `datalab-to/indra-ocr`: the leaderboard ran it in-process on CPU (the `indra-ocr` package: ONNX Runtime detector,
    orientation, script classifier, line recognizers, layout and reading order). It would need an engine package
    `backends/indra/` (`linecaster-indra`, pinning `indra-ocr==1.1.2` and the model tag `v1.1.0`). Its engine model
    would call `indra_ocr.load(mode="auto", furniture=False, math=False, dpi=200, threads=1)` and `Converter.convert(path)`
    on the page file, and return `page.markdown` (and the package's lines, if it exposes geometry). A page the package
    marks `source == "error"` would be an error.
  - `SoMarkAI/OXR-1.0` and `tiiuae/Falcon-OCR`: vendor page pipelines inside their own images: a layout model, a VLM
    behind the image's internal vLLM reading the regions, and the vendor's own Markdown assembly. The leaderboard
    posts the whole page to the vendor API: OXR `POST /v1/parse/sync` (multipart, `output_formats` markdown + json),
    Falcon `POST /falconocr/parse` (`{"images": [data URI], "skip_layout": false}`). Neither answers chat completions
    with a page transcription. They would need a served step with a per-model route and request (JSON or multipart)
    and a serve block that starts the image's entrypoint and waits for its health URLs (OXR: weights downloaded to
    `/models/oxr-model` first, then `/docs`; Falcon: vLLM `/health` and pipeline `/health`). Falcon's image is not
    known to have uv or Python 3.12, which `JobsPipelineExecutor` needs. The other way is to run the VLM through
    `ChatRegionStep` behind linecaster's own layout step, as for MiniCPM-OCR, but that is not the leaderboard's run.

## olmOCR-2-7B-1025-FP8 spec for ChatPageStep (2026-11-03, not yet run)

- `models/olmocr2.py` reproduces the leaderboard driver: no-anchoring v4 YAML prompt as a text part before
  the image, PNG with the longest side forced to 1288 px (LANCZOS), temperature 0.1, max_tokens 8192,
  repetition_penalty 1.05, stop `<|im_end|>`/`<|endoftext|>`; `--max-model-len 16384`, no prefix
  caching, no mm processor cache, one image per prompt; checkpoint pinned; vLLM 0.26.0 (the leaderboard's;
  the uv-scripts recipe has since moved to 0.29.0).
- The completion is kept verbatim; the YAML front matter is parsed into `extra["front_matter"]`.
  Dropping it from the scored text is the leaderboard's post-processing (`drop_front_matter`), left to the
  harness; `olmocr2.body()` does the same split.

## chandra-ocr-2, dots.ocr, OvisOCR2, OvisOCR3 specs for ChatPageStep (2026-11-03, not yet run)

- `models/chandra_ocr2.py`, `models/dots_ocr.py`, `models/ovis_ocr.py` reproduce the leaderboard drivers; request
  bodies (image bytes included) were checked equal to the drivers' `to_request` on JPEG/PNG/WebP, RGB and gray
  pages, and the serve flags equal the drivers' `SERVING` flags. Checkpoints pinned; vLLM 0.26.0 for all four.
- Completions verbatim. The leaderboard converts chandra's HTML layout blocks to Markdown
  (`chandra_html_to_markdown`) and drops Ovis's `<img src="images/bbox_…">` blocks (`drop_bbox_blocks`) in the
  harness's `normalize_outputs`, not in the drivers, so both stay in the harness.
- chandra: one attempt per page (the vendor client's loop retries at raised temperature are not run, as on the
  leaderboard).
- dots.ocr: the scored row ran with `--gpu-memory-utilization 0.6`, at most 4 pages in flight and
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (`chat_page.py --env`); 0.8 / 12 ran out of memory.
- OvisOCR3 ran on an A100 on the leaderboard; on an L4 vLLM may pick another default GDN prefill backend
  (Qwen3.5 base), which can move numerics: compare at CER level.

## MiniCPM-OCR 1.0 through ChatRegionStep (2026-11-03, x86_64 RTX 4000 SFF Ada)

Setup: `ImageFolderReader` → `LayoutStep` (`linecaster serve`, PP-DocLayoutV3 ONNX) → `ChatRegionStep(MiniCPMOCR)` →
page rows, then the SDK's own assembly (`linecaster.adapters.minicpm_ocr.assemble_markdown`, keep footnote and aside_text
as the leaderboard's row did) and the leaderboard lane (consolidate → normalize postproc 3 → score_dataset).
- vLLM nightly 5d35ce3 (`0.32.1rc1.dev602+g5d35ce393`, cu130 wheel from the per-commit index, torch 2.14 cu130) with
  transformers at OpenBMB's pin, in its own venv on an x86_64 machine with an RTX 4000 SFF Ada 20 GB; `ninja` must be
  on PATH (the venv's bin) or the engine fails at startup. Serve flags from the SDK tutorial,
  `--gpu-memory-utilization 0.85`, DSpark speculative decoding with the matching draft model (mean acceptance length
  about 7).
- Reference: OpenBMB's SDK itself (minicpm-ocr 1.0.1 with PaddlePaddle GPU 3.3.0 and the PP-DocLayoutV3 Paddle model, the
  leaderboard image's lock) against the same server on the same pages.

| run | sample-60 CERdip / CERread / recall | tables-7 CERdip / CERread / recall | loops | wall, sample-60 |
|---|---|---|---:|---:|
| linecaster | 0.0361 / 0.0243 / 0.9379 | 0.8893 / 0.5622 / 0.9850 | 0 of 460 regions | 73 s |
| SDK | 0.0360 / 0.0241 / 0.9390 | 0.8885 / 0.5615 / 0.9843 | 0 | 77 s |

- Per book the two agree within 0.002 CERread; 39 of 60 pages give byte-identical Markdown.
- Layout: the region label sequence is the same on 52 of 60 pages, boxes within 3 px on 37. Differences come from the
  ONNX export vs PaddlePaddle, linecaster's containment suppression vs PaddleX's `filter_overlap_boxes`, and the SDK's
  `merge_blocks` (aligned text blocks merged into one composite crop), none of which is ported.
- Where a region's box matches within 1 px, the completion is identical for 320 of 339 regions; the rest differ by crop
  pixels (rounding, the polygon mask drawn by Pillow vs OpenCV) or decoding.
- No region hit its token cap (LightOnOCR-2, a page model, looped on 16 % of region crops).
- One sample-60 plate page has a single `image` region covering the page in linecaster's layout: nothing is read there.
- tables-7: the 5 content pages score CERread 0.209 (recall 0.985); the aggregate 0.562 comes from the 2 sparse pages of
  book F, where both linecaster and the SDK read about 470 characters the GT does not transcribe (CER 74 on those pages).

## NFC step and item-level documents (2026-11-03, aarch64 GB10)

**NFC (`NormalizeUnicode`, after recognition).** The chain with the step against the derivative's goldens
(recorded on the GB10 machine), goldens NFC-normalized (the parity scripts' new default; `--no-nfc` for raw):

| set | lines (box + words) | txt | md | raw, without NFC on the goldens |
|---|---:|---:|---:|---:|
| sample-60 | 1,560/1,560 | 60/60 | 60/60 | words 978/1,560, txt/md 27/60 |
| tables-7 | 651/651 | 7/7 | 7/7 | words 556/651, txt/md 1/7 |

Table padding in txt is unchanged by NFC: tabulate measures with `wcwidth` (a core dependency since the
post-recognition merge), which gives `a` + U+0308 and `ä` the same display width, so NFC(golden) and
linecaster's NFC output pad identically. (Without `wcwidth`, `len()` would count the combining mark and
the decomposed golden would pad one space less per such character.)

**Item-level documents (`BindItem`, `ItemExportsWriter`).** Goldens made with the derivative
itself on the 6 books of sample-60 (10 pages each, in `seq` order): a script (the derivative's own
`build_pipeline` with its command's defaults, then its `--per-document` branch) for four
combinations; cross-checked against the derivative's command (`BOOK --per-document --text lines
--sections --dividers -f md,txt,json`) for all 6 books: 18/18 files byte-identical.

| combination | from the same page rows without NFC (md / txt / JSON) | from the chain with NFC (md / txt) |
|---|---:|---:|
| reflow | 6/6 / 6/6 / 6/6 | 4/6 / 4/6 |
| reflow, dividers, furniture | 6/6 / 6/6 / 6/6 | 4/6 / 4/6 |
| lines, furniture | 6/6 / 6/6 / 6/6 | 6/6 / 6/6 |
| lines, sections, dividers | 6/6 / 6/6 / 6/6 | 6/6 / 6/6 |

- The port is exact: from the same rows, md, txt and docling JSON (structure; furniture layer and version
  normalized) are identical for every book and combination, and the derivative's own `DocumentBuilder` fed
  with the NFC'd rows gives linecaster's NFC output exactly (24/24).
- With NFC, reflow differs on 2 books, for a reason, not by accident: the derivative's `ends_with_mark`
  requires a letter before the hyphen, and in kraken's decomposed text that character is the combining
  accent (category Mn), so `mâ-`/`choire`, `sé-`/`pare`, `exté¬`/`rieur` kept their division marks.
  After NFC they are removed (11 decisions: 9 in book D, 2 in book F; one
  then continues a paragraph that the golden had broken). NFC before reflow is the consistent choice and
  the better text; it stays. The item JSON also differs after NFC in charspans (lengths of NFC strings).
- The derivative crashes on `--text reflow --sections` when a page has a title (confirmed with the
  command on book A: "Document hierarchy is inconsistent"): its reflow path re-parents
  the title into a new section without detaching it. linecaster opens the section first and puts the
  title inside, as the lines mode does (a test covers it); this combination has no golden.
- Docling renders a heading inside a section one `#` deeper (`### ` for level 2); the derivative's goldens
  show the same.

## Post-recognition blocks: retyper and page composition (2026-11-03, aarch64 GB10)

`Typography` (the derivative's retyper) and `ComposePage` (the derivative's `DocumentBuilder`, `--text lines`)
after the in-process squiddle chain (layout, lines, assign, recognition, tables), exported with
`PageExportsWriter(suffix=".paddle", furniture=True)`, compared byte for byte with the derivative's goldens
(recorded on the GB10 machine, `--text lines --furniture`; `tests/parity/compare_exports.py`):

| set | txt | md | docling JSON (furniture layer and version field normalized) |
|---|---:|---:|---:|
| sample-60 | 60/60 | 60/60 | 60/60 |
| tables-7 | 7/7 | 7/7 | 7/7 |

- Without the retyper: md 40/60 and 4/7 (headings demoted 34 times on sample-60, page numbers dropped 3
  times on tables-7). Headline splits and drop capitals do not occur on these pages; a differential check
  against the derivative's own `retype_page` + `DocumentBuilder` on 2,000 random synthetic pages (470 splits,
  442 drop capitals, 578 page numbers dropped, 678 demotions) gave identical md, txt and region ids,
  labels, levels and order on all of them.
- `wcwidth` is now a core dependency: tabulate (docling's text export of tables) pads with `wcwidth` when
  installed and `len()` otherwise, and kraken writes `ä` as `a` + U+0308, so 3 table pages' txt depended
  on whether the environment happened to have `wcwidth`. (The combining marks also mean the as-written
  text is not NFC yet; normalizing it is a separate, recorded transform, not done here.)
- Recomposition (`ComposePage(text="reflow")`, the derivative's default document mode; `linecaster.text.recomposition`
  is the derivative's `reflow.py` verbatim, `uniseg` now a core dependency): no reflow goldens exist, so it was
  checked against the derivative's own `DocumentBuilder(text="reflow")` fed with the same retyped regions and lines:
  md, txt and docling JSON identical on all 67 pages (446 + 33 paragraphs, 234 division marks removed, 1 kept, 4
  continuations across regions), and on the 1,000 reflow pages of the random check.
- Not ported: formula recognition (the derivative reads formula regions as LaTeX by default; no formula
  regions on these 67 pages; `ComposePage` takes `region.extra["formula"]` when a formula step
  provides it), paragraphs continued across pages (needs an item-level document), sections, Markdown
  dividers.

## Chat VLMs: LightOnOCR-2-1B through ChatPageStep (2026-11-03, aarch64 GB10)

Setup:
- Pipeline: `ImageFolderReader` → `ChatPageStep(LightOnOCR2, Served(..., max_window=48, initial_window=8), prepare_workers=4)` → `PageJsonlWriter`, run with `examples/chat_page.py`.
- Server: vLLM 0.21.0 (torch 2.11 cu130) on the same machine.
  - Flags: the spec's serve flags plus `--gpu-memory-utilization 0.22`, because the GPU was shared with `linecaster serve` and kraken-paddlex jobs.
  - The leaderboard pins vLLM 0.26.0. That version was not tested here.

Scoring: the rows were converted to the harness's input shape (id, raw, finish_reason) and scored with the
leaderboard's frozen scoring harness along the leaderboard's path (consolidation, output normalization, scoring).

| run | CERdip | CERread | recall µ | loops |
|---|---:|---:|---:|---:|
| sample-60, ChatPageStep | 0.0614 | 0.0285 | 0.9717 | 5/60 |
| sample-60, bare saturate `pump()` (same request/parse) | 0.0661 | 0.0292 | 0.9669 | 4/60 |
| sample-60, leaderboard's own outputs (vLLM 0.26.0, A10G), same pages | 0.0656 | 0.0321 | 0.9666 | 4/60 |
| tables-7, ChatPageStep | 0.9453 | 0.5539 | 0.9884 | 0/7 |
| tables-7, bare `pump()` | 0.9532 | 0.5662 | 0.9904 | 0/7 |
| tables-7, leaderboard outputs | 0.9701 | 0.5792 | 0.9877 | 0/7 |

- Prompt tokens are identical to the leaderboard's on every page, so the image geometry is identical.
- 29 of the 60 completions are byte-identical to the `pump()` run, and 24 to the leaderboard's. Sampling is at
  temperature 0.2.
- Run-to-run variance of `pump()` on sample-60 was CERread 0.026–0.030 on the common pages. The ChatPageStep result falls inside that range.
- All the looped pages (`finish_reason=length`, 4,096 tokens) are in book E, on every stack.

Throughput, on the same 310 pages (every 7th of the 2,165 ground-truth images), run back to back against the same
server while kraken-paddlex jobs shared the GPU:

| client | wall | pages/s |
|---|---:|---:|
| ChatPageStep pipeline | 1066 s | 0.29 |
| bare `pump()`, `Auto(8,48)`, 4 prep threads | 1251 s | 0.25 |
| (earlier, less contended: bare `pump()`, same settings) | 630 s | 0.49 |

The pipeline adds no measurable overhead. Contention from other GPU jobs dominates these numbers.
Client RSS was about 1.0 GB for the pipeline and 0.7 GB for `pump()`.

**vLLM on the GB10 (unified memory).**
- `--gpu-memory-utilization` is taken against the free memory at start. The same 0.22 gave a 12.3 GiB KV cache in one start and 22.7 GiB in another; EngineCore used 16 GB and 27 GB respectively.
- One start failed with vLLM's profiling assertion ("Initial free memory ... current free memory ..."): another process released memory while vLLM was profiling. Restarting fixed it.

**ServeChatModel** was checked on the GB10 machine with `examples/chat_page.py --serve --port 8133
--gpu-memory-utilization 0.15 --limit 6`. vLLM booted in-task in 143 s, 6 pages ran, and the server was stopped at the
end.

## HF Jobs recipe for MiniCPM-OCR 1.0 regions (not yet run on Jobs)

`recipes/hf-jobs/minicpm_regions.py`: PP-DocLayoutV3 (`ServeModels`, `linecaster serve`) → `ChatRegionStep(MiniCPMOCR)`
(`ServeChatModel`, vLLM) → page rows, both servers in each Job on one GPU.
- Image: the leaderboard's MiniCPM-OCR image (vLLM nightly 5d35ce3 on `vllm/vllm-openai`, transformers at OpenBMB's pin;
  uv and Python 3.12 from the vLLM base). Its SDK venv and Paddle layout model are not used.
- vLLM runs in the image's Python; `ServeChatModel(outside_venv=True)` starts it with `VIRTUAL_ENV` unset and the uv
  environment's `bin` off `PATH`, as the leaderboard recipe does. Draft model pinned through the speculative config's
  `revision` (vLLM passes it to the draft's `ModelConfig`).
- The pipeline and the layout server run in the uv environment from `dependencies(commit, kraken=False)`: linecaster +
  linecaster-paddlex + the OpenCV stub, no kraken (the image has no git) and no lightning.
- Memory: the last block boots first, so vLLM (`--gpu-memory-utilization 0.8` by default) profiles before the layout
  server loads into the rest of the L4.
- Checked locally: `--dry-run` (plan and dill pickle of the pipeline). Not checked: the Job itself, ONNX Runtime's CUDA 13
  wheels next to the image's CUDA, DSpark draft pulled by revision rather than from a local directory.

## HF Jobs image for ChatPageStep (not yet run on Jobs)

`vllm/vllm-openai:v0.26.0` (amd64) qualifies for `JobsPipelineExecutor`. From the image config:
- Python 3.12 (`PYTHON_VERSION=3.12`).
- uv, from `python3 -m pip install uv`, with `UV_PYTHON_INSTALL_DIR` and `UV_CACHE_DIR` set.
- The entrypoint is `vllm serve`, so `vllm` is on PATH.

How the Job is arranged:
- The executor builds the pipeline's uv environment, `--with linecaster @ git+...@<sha>` on Python 3.12.
- `ServeChatModel` starts the image's own `vllm` as a subprocess.
- vLLM never enters linecaster's environment.
- The image sets `UV_INDEX_STRATEGY=unsafe-best-match`, which also applies to that resolve.

## First build (2026-11-03)

### What exists

- Data model (`linecaster.data`, `linecaster.data.page`): `Transcription` (regions, lines,
  words, docling, model, source), `Page`, `PageImage`, `Item`, `Text`. Decisions in
  `docs/reference/data-model.md`.
- ALTO 4.4 / PAGE 2019 / hOCR 1.2 writers and readers on lxml, schema-validated
  (`docs/reference/serialization.md`); image conversion functions (`linecaster.images.convert`: lossless WebP at full
  resolution, combined size limit).
- Blocks on datatrove: readers (image folder, HF image dataset, page rows), model steps (layout,
  lines, recognition) with an in-process or a served backend, line assignment, page writers,
  `ServeModels`.
- `linecaster serve`: a stateless model server (aiohttp) hosting several engines; blocks reach it
  through saturate.
- Engines: `backends/paddlex` (PP-DocLayoutV3 layout, PP-OCRv6 detection), `backends/kraken` (kraken's
  PP-OCRv6 recognizer), moved from the derivative with their history; `envs/kraken-paddlex` is the
  environment that installs both.
- Recipes: `recipes/hf-jobs/squiddle_chain.py` (datatrove `JobsPipelineExecutor`, one
  `linecaster serve` per Job), `recipes/hf-jobs/cuda_probe.py`.

### Parity with the derivative's pipeline

The squiddle combination built from blocks (layout → lines → assign lines → recognition) reproduces the derivative's
outputs (its default paddle pipeline, batch 8, bf16-mixed on CUDA) line for line on sample-60, a 60-page sample of
19th-century scientific print from the ground-truth set: 1,560/1,560 lines identical in line box, text and every word
box.

| machine | in-process | served (datatrove + saturate + `linecaster serve`) |
|---|---|---|
| GB10, aarch64 | 60/60 pages exact | 60/60 pages exact |
| RTX 4000 SFF Ada, x86_64 | 60/60 pages exact | 60/60 pages exact |

Goldens are per machine: the derivative itself gives 50/67 byte-identical text files between the GB10 and the RTX 4000
SFF Ada machine (36 differing word tokens in 17 files), the usual GPU numerics. The derivative is run-to-run
deterministic on one machine (rerun: 60/60 identical). On the 7 table pages the recognized lines are identical too;
one extra line in linecaster's output is one that the derivative's typography step (retyper, after recognition, not
yet ported) removes.

On HF Jobs (L4) the served chain gives the same harness scores as on the GB10 machine to four decimals on the
60-page sample (CERdip 0.0338, CERread 0.0268, recall 0.9526 vs 0.9528); line geometry identical on
1,552/1,560 lines (different GPU numerics).

### Throughput (squiddle combination, per page, model time)

| machine | layout | lines | recognition | wall, 60 pages, served (models overlap) | wall, in-process |
|---|---|---|---|---|---|
| RTX 4000 SFF Ada, x86_64 | | | | 42 s (0.70 s/page) | 65 s |
| HF Jobs L4 | 0.21 s | 0.18 s | 0.74 s | | |
| GB10, aarch64 (GPU shared with other work) | 0.16 s | 0.13 s | 0.71 s | 98 s | 194 s |

Served is faster than in-process because the three models work on different pages at the same time
(one worker per model, saturate keeps several pages in flight).

### Full ground truth (2,165 pages, HF Jobs, 4 × L4)

The chain through datatrove + saturate on HF Jobs scores CERdip 0.0551, CERread 0.0451, recall 0.9754 with the
leaderboard's frozen scoring harness (the derivative's reference on the x86_64 RTX 4000 SFF Ada machine: 0.0587 /
0.0432 / 0.9756). Most pages score identically; the CERread gap sits in index pages that are tables (book B): the
derivative's PaddleX table step writes them row by row, matching the ground truth's line structure, while linecaster
has no table step yet and writes each cell as its own line. The table step is the next block to port.

### GPUs compared (full ground truth, complete chain incl. tables, 4 tasks on HF Jobs)

Model seconds per page (datatrove stats); recognition sets the pace because the models work on
different pages at the same time. Scores are identical on all three (CER reading 0.0419–0.0420).

| GPU | layout | lines | recognition | tables |
|---|---|---|---|---|
| L4 | 0.21 | 0.18 | 0.76 | – |
| A10G | 0.21 | 0.20 | 0.72 | 0.03 |
| L40S | 0.13 | 0.12 | 0.44 | 0.02 |
| RTX 4000 SFF Ada | 0.17 | 0.12 | 0.69 | – |

With one worker per model the L40S finishes about twice as fast as an L4.

### Replicas: several copies of the recognition model on one GPU (measured, then removed)

**Decision: `linecaster serve` keeps one worker per model.** A `--replicas NAME=N` option (N copies of
a model, each with its own worker thread on the model's queue; commit 3303cd3, reverted) was measured
and removed: the gain is small, depends on the current batching, and the option suggests a scaling path
that does not exist. Measurement: Full ground truth, complete chain, 4 tasks on HF Jobs; seconds per page = the sum of the
tasks' recognition-block wall time / 2,165 (the chain runs at the pace of recognition). Lines, words and
tables are identical for every N (2,165/2,165 pages).

| GPU | 1 replica | 2 replicas | 3 replicas |
|---|---|---|---|
| L4 | 0.819 | 0.756 (−7.6 %) | – |
| L40S | 0.452 | 0.416 (−7.9 %) | 0.405 (−10.4 %) |
| RTX 4000 SFF Ada (310 pages) | 0.714 | 0.686 (−4 %) | 0.671 (−6 %) |

(L4 1 and 2 replicas from the same commit; L40S 1 replica from the earlier run of the same chain.)
Recognition is GPU-bound, not GIL-bound: per-request time roughly doubles with two replicas (L4 0.81 →
1.49 s), and on the RTX 4000 SFF Ada kraken in two separate processes reaches the same total throughput as one (80
pages in 52 s alone; 2 × 80 pages in 102 s side by side). Replicas only fill the gaps between a page's
batches. The lever left is the recognizer's GPU efficiency (8 lines per forward pass in bf16), which
changes numerics if the batching changes.
Revisit only with a server that runs model copies on separate CUDA streams or processes, or after a
change that makes recognition much faster (then layout, at about 0.2 s/page, sets the pace).

### Region recognition with a page model

`ChatRegionStep` with PP-DocLayoutV3 regions and LightOnOCR-2-1B (a page-trained VLM): the model loops
to its token limit on 68 of 418 region crops of the 60-page sample (page headers 30, footers 15,
footnotes 15); with those regions left empty the reading CER is 0.0402 against 0.0285 for the same
model on whole pages. The block works; region reading wants a region-trained model or tighter
per-region limits.

### Lessons

- `[tool.uv.sources]` applies only to a project's own dependencies: the kraken fork came in
  transitively and uv resolved upstream kraken 7.1.1 (inert `--precision`), so the first run was fp32.
  The engine environment lists kraken directly and pins the numerically relevant versions with
  `constraint-dependencies`.
- PaddleX pins `opencv-contrib-python` (GUI build, needs libGL, missing in the HF Jobs image):
  `stubs/opencv-contrib-python` satisfies the pin with the headless build of the same version; one
  `cv2` in the environment; parity unchanged.
- `ServeModels` must be the last block: datatrove chains generators, and only the last one lives until
  every page is written.
- `[tool.uv]`/`uv run --with` in Jobs: git dependencies are spelled out as direct URLs (fork, stub,
  subdirectories).

### Open

- Port the derivative's post-recognition steps (retyper, reflow, page composition into `docling`, tables,
  formulas) as blocks.
- `/v1/chat/completions` preset route for OpenAI clients.
- Deterministic algorithms flag: not set (the derivative does not set it and is run-to-run deterministic);
  cuDNN autotuning is off explicitly.

## Per-page files and item texts in one run (2026-11-03, aarch64 GB10)

`examples/squiddle_chain.py BOOKS OUT --item-from-parent --files OUT/files --texts OUT/texts`
in-process on sample-60 (images grouped by book in subfolders, 6 books): 1 m 45 s; page rows, 360
per-page files (`<item>/<page>.hocr|.alto.xml|.page.xml|.txt|.md|.json`) and 18 item texts.

- All 60 ALTO and 60 PAGE files validate against the schemas in `tests/schemas/`; the 60 hOCR files
  read back with `from_hocr` (1,560 lines, as recognized).
- readable variants: ſ folded (`proſtrati` → `prostrati` on book E), the as-written ſ kept
  in verbatim_txt; line-end hyphens resolved (`Verbin-/dung`, `Meso-/pleurit`, `Differen-/zierung`
  → joined, on book C); page headers and numbers (`— 38 —`) gone from readable, kept in
  verbatim; pages separated by form feeds in verbatim only.
- tables-7 (2 books): table regions appear as HTML tables in readable_md (cells span) and as
  tab-separated rows in readable_txt.
- The test pages are not consecutive within a book, so the joins across page breaks seen here are
  between unrelated pages; on a whole book they are the intended paragraph continuations.
- Item page order: `ItemTexts` sorts by `sequence`; `ImageFolderReader` sets none, so pages fall back
  to their ids (the source's page ids ascend with the sequence on these books).

## Chat presets: validation on the 60-page sample (2026-11-03)

Each spec ran through `recipes/hf-jobs/chat_page.py` (ChatPageStep + ServeChatModel in one HF Job) on the
sample-60 pages, and was scored the leaderboard's way (consolidate → `normalize_outputs` postproc 3 →
`score_dataset`) next to the leaderboard's own outputs for the same 60 pages (the leaderboard's consolidated rows).
CER reading, linecaster vs leaderboard:

| Model | GPU | linecaster | leaderboard |
|---|---|---|---|
| rednote-hilab/dots.ocr | L4 | 0.0170 | 0.0170 |
| datalab-to/chandra-ocr-2 | L4 | 0.0190 | 0.0197 |
| baidu/Unlimited-OCR-2 (SGLang) | L4 | 0.0251 | 0.0262 |
| ATH-MaaS/OvisOCR2 | L4 | 0.0276 | 0.0274 |
| ATH-MaaS/OvisOCR3 | L4 | 0.0299 | 0.0325 |
| PaddlePaddle/PaddleOCR-VL-1.6 | L4 | 0.0309 | 0.0309 |
| Qwen/Qwen3.5-9B | L40S | 0.0358 | 0.0356 |
| zai-org/GLM-OCR | L4 | 0.0368 | 0.0360 |
| nvidia/Nemotron-3.5-Parse | H200 | 0.0403 | 0.0454 |
| baidu/Unlimited-OCR | L4 | 0.0429 | 0.0449 |
| baidu/Qianfan-OCR | L4 | 0.0482 | 0.0491 |
| deepseek-ai/DeepSeek-OCR | L4 | 0.0551 | 0.0543 |
| deepseek-ai/DeepSeek-OCR-2 | L4 | 0.0576 | 0.0628 |
| ds4sd/SmolDocling-256M-preview | L4 | 0.0643 | 0.0556 |

- Greedy decoding with identical requests reproduces the leaderboard exactly (PaddleOCR-VL-1.6, dots.ocr); the
  others differ within sampling and GPU variation (CIs on 60 pages are about ±0.02).
- SmolDocling is the largest gap (3 vs 5 truncated pages); the leaderboard copy compared against may not be the
  scored run (see the SmolDocling section above). Worth a second look.
- Not ported: indra-ocr (in-process ONNX package, not a server), OXR-1.0 and Falcon-OCR (vendor parse
  APIs, not chat completions).

## Manifests through pybookget: IIIF (2026-11-04) and METS (2026-11-05), aarch64 GB10

`ManifestReader` (before 2026-11-05 `IIIFManifestReader`) and `pipelines/harvest.py` checked against public
servers with linecaster's user agent, 2 requests per second, 3 pages per item:

- Wellcome Collection (`presentation/v3/b18035723`): a Presentation 3 manifest whose image service is Image
  API 2, so the request is `full/full` (not `max`); 36 canvases. Its canvases link ALTO (`seeAlso`), read as
  `ocr_original` (35 and 5 lines; none on the cover). Canvas files skip a number (`_0001`, `_0003`, `_0004`):
  pages count canvases, and each page's image and ALTO come from the same canvas. On 2026-11-04 a harvest of 3
  pages, then the squiddle recipe on `--rows`.
- Bodleian (a Presentation 2 manifest, 84 canvases): first image fetched at full size; the manifest has no
  `license`, so `rights` is empty.
- Heidelberg University Library (`diglitData/mets/cpg389.xml`, a manuscript, 694 pages): METS with `MAX`,
  `DEFAULT`, `DEFAULTPLUS`, `MIN`, `THUMBS`, `INTROIMAGE` groups; `MAX` taken; page labels from the METS
  ("Vorderdeckel", "Vorderspiegel 1"); no `FULLTEXT`. Title and rights (Public Domain Mark) from MODS.
- SLUB Dresden (OAI-PMH `GetRecord`, `metadataPrefix=mets`, a print of 472 pages): `ORIGINAL` taken, the
  full-size JPEGs (2848 × 4288); no `FULLTEXT` in this record.

Open: the per-task rate limit is the only limit (datatrove keeps no state between tasks); a run against one
server sets `--workers` × `--rate-limit` to what that server accepts.

## Tracing: overhead and storage (2026-11-05, aarch64 GB10)

The squiddle recipe on the 60-page sample, one task, in-process and served (`--backend served`: the task starts
`linecaster serve`), each configuration twice. Untraced is the commit before tracing (`e4b8d1d`); traced at
`--trace-sample` 0, 0.01 and 1. Seconds per page from the reader's first file to datatrove's "Processing done"
(warm-ups and server start left out):

| | untraced | sample 0 | sample 0.01 | sample 1 |
|---|---|---|---|---|
| in-process | 1.092, 1.088 | 1.092, 1.084 | 1.087, 1.078 | 1.091, 1.087, 1.091 |
| served | 0.811, 0.810 | 0.812, 0.811 | 0.815, 0.817 | 0.814, 0.818, 0.812 |

- The differences are within the run-to-run variation. The cost alone, on CPU: the modular pipeline with fake
  engines (ten blocks with the rejects writer) on 2,000 small pages, best of three: 0.526 ms per page untraced,
  +0.20 ms at sample 0 and 0.01 (every page's spans are recorded and held until it is done), +0.50 ms at sample 1.
- Storage (gzipped OTLP JSON lines): the task spans take about 1.05 KB per task in-process, 1.25 KB served; a traced
  page about 0.5 KB in-process (31,340 bytes for 60 pages at sample 1) and 1.7 KB served, pipeline and server
  together (102,518 bytes). Per 1,000 pages: sample 0, only the task spans (and 0.5 KB per failed page); sample
  0.01, about 5 KB in-process and 17 KB served; sample 1, about 0.5 MB in-process and 1.7 MB served.
- Memory of the buffer for unsampled pages: 3.3 KB per held span (tracemalloc), 39 KB for a page of twelve blocks.
- `linecaster serve` lost its last spans at first: saturate's `Engine` signals the server's process group and
  `uv run` passes the signal on, so the server got SIGTERM twice and the second cut its graceful end short; and
  PaddlePaddle puts its own SIGTERM handler in place at its first operation ("FatalError: Termination signal"),
  which ends the process at once. The server now ends on the first signal only and sets its handlers again after
  the engines load and after each model's first call; with that every request of the served run has its
  `linecaster.serve.*` spans (60 of 60 per model).
- vLLM 0.20.0 continues a `traceparent` from request headers when started with `--otlp-traces-endpoint`
  (protocol from `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL`, default gRPC); saturate 0.3.0 sends the same headers with
  every request, so a chat request carries no page context and vLLM's spans are traces of their own. Not run
  against vLLM or an OTLP collector here.
- Parity: the squiddle recipe in-process (sample 0.01) and served (sample 1) reproduce the goldens (60 of 60 pages
  exact).
