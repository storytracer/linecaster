# Pipelines: contracts and the builder

A pipeline is a list of blocks (datatrove `PipelineStep`s) and composites. Before it runs, the builder
(`linecaster.runtime.builder`) checks the blocks' contracts, expands the composites, and cuts the pipeline into
stages. Every pipeline script goes through it (`linecaster.runtime.run`). Terms are the [glossary](glossary.md)'s.

## Contracts

Every block returns its contract from `contract()` (`linecaster.blocks.base.contract`):

```python
@dataclass(frozen=True)
class Part:
    name: str                  # a name of PARTS, or "*" (every part)
    transcription: str | None  # ocr_new, ocr_original, ...; None: page-level (image, metadata, transcription_file)
                               # or the item record's

@dataclass(frozen=True)
class Contract:
    unit: str                  # "page", "item" (what the input stream carries) or "any" (servers)
    unit_out: str | None       # set when the block changes the stream's unit (binder: page -> item, splitter: back)
    reads: frozenset[Part]
    adds: frozenset[Part]
    replaces: frozenset[Part]
    removes: frozenset[Part]   # parts the block does not pass on (gone for every later block)
    role: str                  # reader, writer, server, model, transform, binder, splitter, validator, composite
```

- **The vocabulary** is `PARTS` in `linecaster.catalog.schema`: `image`, `metadata` and `transcription_file` (a
  library's own transcription delivered with the page, as a document media) (page-level), what presets produce (`PRODUCES`: `regions`, `reading_order`, `lines`, `baselines`, `text`, `words`, `word_confidences`,
  `line_confidences`, `tables`, `formulas`, `markdown`, `html`, `doctags`, `layout_json`, `latex`), and
  `line_regions`, `hierarchy`, `nfc`, `document`. A part is written `transcription:name` (`ocr_new:lines`);
  `ocr_original:*` is every part of a transcription.
- **Simple blocks** declare class attributes (`unit`, `role`, `parts_read`, `parts_added`, `parts_replaced`,
  `parts_removed`) that
  the default `contract()` of `Contracted` reads; page-level names stay page-level, the others belong to the
  block's `transcription`. Blocks whose parts depend on their options compute `contract()`.
- **Model blocks** read the page image (recognition also `lines`, tables and formulas `regions`) and add their
  preset's `capabilities.produces`: the preset of the `InProcess` backend (`preset`), of the `Served` backend
  (`preset`, set by `runtime.run.engines`) or of the `Chat` backend; without a preset the engine class's
  `capabilities` (read from its source in the repository, else from the class); without either the step's default.
  The chat recognizers add `text` too, `RegionRecognizer` also `lines` (and replaces `lines` and `text`: the
  transcription's earlier lines are replaced).
- **Readers** add `image` and `metadata`; `ManifestReader(existing_ocr=True)` also `transcription_file`, which the
  `TranscriptionConverter` reads (adding `ocr_original:*`);
  `PageRecordReader` what `provides=` declares (`["ocr_new:lines", ...]`), or anything (`*`, reads after it are
  not checked) when it declares nothing. With `fetch_images=False` it brings no `image`.
- **Writers** read what they write and add nothing (`ImageFilesWriter` replaces `metadata`: the image's URI then
  names its copy; `PageFileWriter`: `lines` for hOCR, ALTO and PAGE, `text` for
  md and txt, `document` for HTML, DocLang and JSON, `image` for plots). **Servers** have role `server` and unit
  `any`.
- **The `Binder`** changes the unit from pages to items, the **`Splitter`** back: an item record holds its page
  records, so what the pages carried stays available across either (the checks carry the parts over), apart from
  the page image's bytes (`image`: an item record has none) at the binder and the item's `document` at the splitter.
- **Item-unit blocks** (`Recomposer(unit="item")`, `CharacterNormalizer(unit="item")`, `Composer(unit="item")`)
  read item records: one datatrove document per item, `doc.metadata["item"]` holding the item id and its page records
  in order (`linecaster.blocks.base.item`); they read and add the parts of the pages' transcriptions, the item
  `Composer` adds the item's `document` next to the record. **Item writers**: `ItemTextWriter` reads `lines` for
  `verbatim_txt` and `paragraphs` and `normalized` for the readable variants, `ItemDocumentWriter` the `document`.
  `RecipeStamper` has unit `any`: before an item writer it stamps the pages of each item record.
- A step without a contract (a plain datatrove step) passes pages and touches no part.

| Block | Reads | Adds | Replaces, removes |
|---|---|---|---|
| `LineAssigner` | `lines`, `regions` | `line_regions` | `regions`, `reading_order`, `lines` |
| `UnicodeNormalizer` | `text` | `nfc` | `text` |
| `CharacterNormalizer` | `text` | `normalized` | |
| `Typographer` | `regions`, `lines` | `hierarchy` | `regions`, `lines` |
| `Recomposer` | `regions`, `lines` | `paragraphs` | `paragraphs` (made anew where they exist) |
| `Composer` | `regions`, `lines` (and `paragraphs` when there are) | `document` | |
| `ImageFetcher` | `metadata` | | `image` |
| `ImageConverter` | `metadata` | | `metadata` (with `keep_bytes` also `image`; without it removes `image`) |
| `TranscriptionConverter` | `metadata`, `transcription_file` (with `source="media"`) | `<transcription>:*` | |
| `RecipeStamper` | | | |

## Block shapes

- **Per-unit transform** (`shape = "unit"`): `process_page(doc, page) -> page | None`; `PageBlock` owns the loop
  and the stats. In-process model blocks have this shape.
- **Stream transform** (`shape = "stream"`): overrides `run(data)` and yields each page when it is done, possibly
  out of order (served model blocks, `PageRecognizer`, `RegionRecognizer`). It reports what happens to each page
  inside it with `notify(doc, event)`: `prepare` when a request is built, `done` when its result came back. The
  served model blocks share one streaming loop (`ModelBlock`): a block names its requests (`_rows`: one per page, one
  per region for `RegionRecognizer`), builds and parses each (`_request`, `_parse`) and says which pages a finished
  one completes (`_done`).
- Only readers and writers see `rank`, `world_size` and files (a test walks every block class, with no exceptions):
  a block that rejects a page records why on the page, and the `RejectWriter` names the task's file.

## Backends

A model block's backend (`linecaster.backends`) says where its engine runs:

- `InProcess("pkg:Class", **options)` (or `InProcess.from_preset(ref)`; a model block given a preset ref,
  `LayoutDetector("single-region@1")`, builds one): the engine loads in the worker;
- `Served(endpoint, model=name, ...)`: `linecaster serve` (or a server speaking its routes) hosts it, reached through
  saturate on `/v1/linecaster/{step}`;
- `Chat(preset, endpoint=None, served_name=None, max_window=32, initial_window=4, read_timeout=600.0, api_key=None,
  headers=None, prefer="page")`: a chat preset's VLM behind an OpenAI-compatible server (vLLM, SGLang, a hosted
  endpoint) on `/v1/chat/completions`; `preset` is a preset ref, a model's Hugging Face id (its preset with unit
  `prefer`) or a configured adapter (`chat_model`); without an endpoint, the task's `ChatModelServer` on port 8000.
  `PageRecognizer(backend)` and `RegionRecognizer(backend, labels=..., pad=None)` (`pad`: the adapter's `region_pad`, else 8) take it (or a chat preset's ref).
  `PageRecognizer` also takes a page engine's `InProcess` or `Served` backend (or its preset's ref): a stream
  transform served, a per-unit transform in-process; it reads the page image and adds `text` and what the preset
  produces. A page engine's `endpoint` option (where its service is) is operational.

The built-in engines (`layout.single-region.v1` and the rule-based steps') run in the pipeline's process only:
`runtime.run.engines` keeps a preset of one in-process when the other models are served, and `linecaster serve`
refuses them.

## The builder

```python
plan = build(blocks, tasks=8, until=None, after=None, taps={"LineAssigner": "OUT/taps/lines"},
             run_folder="OUT", recipe=("squiddle@1", "sha256:..."))
plan.check()          # PipelineConfigError listing every problem
plan.stages           # [Stage(name, tasks, blocks, pipeline)]: one datatrove pipeline each, run in order
plan.graph            # nodes (blocks; composites expanded, their group kept), edges (part -> the block reading it)
plan.mermaid()        # the graph as a Mermaid flowchart: stages and composites as subgraphs
plan.describe()       # stages with each block's contract, the edges, the problems
```

**Checks**, all collected: a stage starts with a reader; every part a block reads is added earlier in its stage
(or by the stage's reader) and not removed since (`removes`, even after a reader that provides anything); a part
is added by one block only, unless a later block declares it in `replaces`;
units fit (a page block cannot follow an item stream, an item block needs a binder before it); the parts carry
across a binder and a splitter (apart from `image` and the item's `document`); server blocks go last; a served model
block whose endpoint is a server block of its stage (same loopback port) finds its model in that server's list; the alternatives of a group add the same parts, sit next to each other, each with a condition,
`OTHERWISE` last; names given to `until`, `after` and `taps` fit exactly one block.

**Order** is the given one; the builder checks it and does not reorder. It inserts a `TranscriptionConverter` (into
`ocr_original`) right after a block that adds `transcription_file` when no later block reads it, the
`RecipeStamper` before the first writer when the run follows a recipe, a `RejectWriter` into
`<run_folder>/rejects` before the first writer (or binder) when there is a run folder and the pipeline has none, and moves the server blocks at the end into the
stage of the model blocks when it cuts. `build(..., max_page_errors=SHARE)` sets every page block's error budget.

**Branches**: `branch(block, when=Condition, group=None)` gives a block a condition, a picklable predicate on the
page record with a `describe()` (`MetadataEquals(key, value)`, `OTHERWISE`). The block processes the pages the
condition accepts; the others pass unchanged. Blocks with the same `group` are alternatives: each page goes through
the first one whose condition accepts it. A per-unit block gets its pages one by one; any other block one stream of
them, the pages it does not take passed on as it yields.

**Composites**: `Composite(name, blocks, contract=None)` expands into its blocks (nested composites too); its
outward contract is derived (what its blocks read that none of them adds, what they add and replace) unless given.
`ModularTranscriber(lines, recognition, layout, formulas_separately=False, transcription="ocr_new")` is layout
(`"single-region@1"`: the page as one region) → lines → line assignment → line recognition; each step a block, a
backend or a preset.

**Stages**: with `tasks > 1`, the first binder (a block whose stream changes from pages to items) cuts the
pipeline, unless the reader already gives each task whole items (`ManifestReader`, `PageRecordReader(item_shards=
True)`). The first stage writes its page records in item shards into `<run_folder>/pages/` (the pipeline's own
`PageJsonlWriter` there, now with `item_shards=N`, N = `tasks` unless it set its own); the second starts with
`PageRecordReader(item_shards=True, fetch_images=False)` declaring the parts the first stage added, runs the binder
and what follows, as N tasks. A `Splitter` after the binder needs no cut of its own: the items are whole in the
task, so its pages are too. One stage logs to `OUT/logs/`, two to `OUT/logs/pages/` and `OUT/logs/items/`; the run
record lists the stages. Each stage gets its own executor, and the later one `depends=` on the earlier one:

| `--on` | Executors | Stages |
|---|---|---|
| `local` | `LocalPipelineExecutor` | the second starts when the first is complete |
| `ray` | `RayGPUExecutor` for stages with servers, `RayExecutor` for the item stage and pipelines without engines (CPUs only) | the same, through `depends=` |
| `hf-jobs` | `JobsExecutor` (datatrove's `JobsPipelineExecutor` with JSON-lines logs; `GPUJobsExecutor` for multi-GPU flavors on stages with servers) | consecutive launches: the second launches when the first's Jobs are complete; both on `--flavor` |

**Partial runs** (blocks named by their datatrove `name`, their class name, or a composite's name for its last
block):

- `until=BLOCK` (`--until`): the blocks up to and including BLOCK, then a `PageJsonlWriter` into
  `<run_folder>/pages` (and the server blocks);
- `after=BLOCK` (`--after`, with `--pages DIR`): the pipeline's `PageRecordReader`, then the blocks after BLOCK;
  the reader declares the parts the blocks up to BLOCK add;
- `taps={BLOCK: DIR}` (`--tap-after BLOCK DIR`, repeatable): a `Tap` observer writes every page record as it
  leaves BLOCK into `DIR/<rank>.jsonl.gz`.

**In this process**: `run_pages(blocks, docs)` checks the blocks and runs them on `docs` (datatrove documents) as
task 0 of 1, without an executor (a leading reader reads its own input after them); `run_plan(plan)` runs a plan's
stages that way. A pipeline script's `--page IMAGE OUT` runs its pipeline on one image like that, and `linecaster
page IMAGE OUT [--recipe R | --pipeline ID] [pipeline options]` finds the script (the recipe's pipeline, else
`transcribe_modular.v1`) and runs it so.

`--dry-run` prints the plan (`describe()` under `plan`, with the run record) and the Mermaid graph, and fails like
a run would when there are problems; a run with problems exits with code 2 before it writes anything.

## Observers

`linecaster.runtime.observers.Observer` has `on_task_start(rank, world_size)`, `on_warm_up(block, seconds)`,
`on_enter(block, doc)`, `on_exit(block, doc, error=None)`, `on_unit(block, doc, event, **attributes)` (from stream
blocks' `notify`: `prepare` and `request` in saturate's prepare threads, `request` with a `carrier` dict for the
trace context, `done` with `error`, tokens and `finish_reason`; `region` for a request per region),
`on_task_event(block, event, start_ns, end_ns, **attributes)` (from `Block.report`: a reader's `file`, a writer's
`flush`), `on_leave(doc)` (a page leaves the stage's last block), `on_task_end(error=None)` (also when the task
fails) and `environment()` (variables for a server a block starts in the task). When a stage has observers
(`build(..., observers=[...])`, taps, tracing), the builder puts a `Boundary` after every block: the boundary
between block *i* and *i + 1* calls `on_exit(i)` and `on_enter(i + 1)` for each page, so a block's time per page
includes waiting in a served window; `error` is the entry the block added to `doc.metadata["errors"]`. Boundaries
are plain callables, not datatrove steps, so they add no stats; a stage without observers has none.

Every stage with a run folder (or an OTLP endpoint) is traced: the builder adds a `linecaster.tracing.Tracing`
observer (`build(..., trace_sample=SHARE)`, `--trace-sample`; [tracing](tracing.md)).

## Warm-up

Every block has `warm_up()` (idempotent): engines load there (`InProcess.warm_up()`), servers start there
(`ModelServer`, `ChatModelServer`), a served backend reads its secrets there; blocks with nothing to load keep the
no-op. A block's `__call__`, which datatrove's executors call, warms it up before its `run` starts: blocks warm up
as the stream reaches them, the last one first (the servers before the blocks that call them). The time is the
block's own stat, `warm_up_seconds` (per task), and goes to the observers (`on_warm_up(block, seconds)`); a page's
measured `seconds` never include loading. An error in a warm-up fails the task (a server that does not start: a
`ServerError`).

## Failures

- **Per page.** An exception in a per-unit transform's `process_page` (other than a `PipelineConfigError`,
  `CatalogError` or `ServerError`, which fail the task) becomes an entry in the page's `doc.metadata["errors"]`:
  `{"block": class, "step": a model block's step, "preset": its edition or null, "type": the exception's class,
  "error": the message}`; a failed request of a served block is the same with type `ServerError`; checks
  (`PageValidator`, `ImageConverter`) add `field` and `raw_value`. The page goes on as it was.
- **Later model blocks pass it by** (`skip_on_error`, the default for model blocks; stat `skipped_after_error`), at
  once: in-process the page leaves the block before the next one enters, served it is put straight onto the
  block's results (it never waits for the window, nor for the end of the input).
- **Rejects.** The `RejectWriter` writes every page that carries errors to `OUT/rejects/<rank>.jsonl`, one line
  per error (`key`, `field`, `error`, `raw_value`, and the entry's `block`, `step`, `preset`, `type`), and passes
  it on: the page records keep failed pages with their errors, so a later pipeline reading them passes them by too.
- **The error budget.** A block may fail on `max_page_errors` of a task's pages (`--max-page-errors`, default
  0.01), judged from the 100th page on: from then, more errors than `share × pages` fail the task with a
  `PageError` (with the default: two failures in the first 100 pages, three in 300). Fewer pages are too few to
  judge. datatrove reruns a failed task whole.
- **Errors** (`linecaster.errors`): library code raises `PipelineConfigError` (a pipeline, option or input that
  cannot work; `problems` lists them), `CatalogError`, `PageError(page_id, block)` and `ServerError`, all
  `LinecasterError`s, never `SystemExit`; the `linecaster` command and a pipeline script's `main` turn them into
  exit codes (2: nothing was launched).

## The run record

`OUT/run.yaml` (schema `linecaster.run-record/1`, the pydantic model `linecaster.runtime.record.RunRecord`, JSON
Schema `catalog/schemas/run-record-1.json`) records the script, the recipe, the command line, the options, where it
ran and the software, and:

- `pipeline`: per stage its name, tasks and blocks in order, each block as its `to_dict()` (below) with its
  `contract`, composite, group and condition;
- `pipeline_sha256`: the hash of the pipeline's **functional** parameters.

**`to_dict()`** gives a block as it was built: `{"block": class name, "class": "module:Class", "params": {...}}`,
every constructor parameter with the value it was given or its default (`**kwargs` flattened), JSON-compatible:
backends as `{"backend": "in-process", "engine", "options", "preset", "preset_sha256"}`, `{"backend": "served",
"endpoint", "model", "max_window", ..., "preset", "engine"}` or `{"backend": "chat", "adapter", "preset",
"preset_sha256", "model", "revision", "served_name", "endpoint", "max_window", ...}` (a chat adapter's dict plus where
its server is), nested blocks as their dicts, secrets as `{"env": NAME}`, folders as paths, callables as `module:name`. A block
keeps the arguments it was constructed with; `live_params` names those the builder may change afterwards (a page
record reader's `provides`). A composite's dict is its group: its parameters and its blocks' dicts.

**Functional and operational parameters.** A parameter is *functional* when changing it can change what a run
writes for a page or an item (its page records, files and texts) or how they are partitioned (`item_shards`); it is
*operational* when it only changes where things are read and written, how the work is spread and paced, or how a
server is reached. `pipeline_sha256` covers the functional ones (`provenance.functional_pipeline`):

| Operational (left out) | Why |
|---|---|
| folders and file names: `data_folder`, `output_folder`, `output_filename`, `image_folder`, `manifest_folder`, `ocr_folder`, `folder`, `suffix`, `bucket_by_item`, `prefix` | where things are |
| which input files a task reads and how: `paths_file`, `glob_pattern`, `recursive`, `limit`, `skip`, `shuffle_files`, `batch_size` (a reader's), `http` (rate limits, the IIIF format asked for), `uri_map`, progress bars | the pages themselves are recorded per page |
| servers and clients: `port`, `host`, `python`, `script`, `vllm`, `outside_venv`, `boot_timeout`, `max_queue`, `prepare_workers`, `gpu_memory_utilization`, `extra_args`; an in-process engine's `endpoint` and `timeout` (`ENGINE_OPERATIONAL`: where its service is); a served backend's `endpoint`, `model` (the name it is hosted under, unless nothing else names its engine), `max_window`, `initial_window`, `read_timeout`, `api_key`, `headers`; a chat backend's `served_name` and the same (it counts by its adapter, preset edition and hash, model and revision) | how a server is started and reached |
| `name` (datatrove's display name), `compression`, `max_file_size`, `ImageConverter.keep_bytes` | presentation, file handling, memory |
| server blocks (`ModelServer`, `ChatModelServer`, `ServiceServer`) as a whole | their models count through the blocks they serve |
| the backend (in-process or served) | a model block counts by its engine, the engine's options and the preset edition with its hash, wherever it runs |

Everything else is functional: block classes and their order, transcription names, engine options, presets and
their hashes, the recipe stamp, conditions and groups, writers' formats and options, `item_shards`. The base list
is `OPERATIONAL` in `linecaster.blocks.base.block`; a block class adds its own in `operational`. So a resumed run,
a run on another executor or backend, or into another folder has the same hash; another preset, option or block
has another.

**Resume.** A run into an OUT that holds a run record is checked against its newest record (`run.yaml`, or a later
`run-<time>.yaml`): another `pipeline_sha256` is refused with a `PipelineConfigError` (finished tasks would be
skipped and the folder would mix two pipelines' outputs) unless `--new-pipeline` (the new record is written next
to the earlier one and is the one the next resume is checked against); another `--tasks` is always refused (each
task would read other input). The same hash and tasks: a resume, as datatrove's completion markers make it.
`--dry-run` reports the same problems.

**Describe mode.** `linecaster.runtime.run.describe_script(script, argv)` builds a pipeline script's plan in the
current process without its engines: the script is loaded as a module, its options parsed, presets resolved
without checking that their engines are installed, nothing loaded or started. `describe_recipe(ref)` describes a
recipe edition that way (its pipeline script by the recipe's pipeline id, `--recipe REF`, placeholder folders):
what `linecaster catalog release` records in the lock and `verify` compares ([catalog](catalog.md)).

## Tasks, workers and rate limits

`--tasks` and `--workers` are chosen when the command line leaves them open (`linecaster.runtime.run.allocate`):

| Pipeline | `--tasks` | `--workers` |
|---|---|---|
| with engines | 1 | every task |
| without engines, every rate-limited host through proxies (`--proxies`, an HTTP policy's `proxies`) | the reader's `auto_tasks` (from the input), else 1 | one per available proxy, divided by `proxies_per_worker` (`ceil(available / N)`), at most the tasks, not capped by the CPUs; with `proxies_per_worker: share` as without proxies |
| without engines, with `--rate-limit` (a host with rate limits and no proxies) | the reader's `auto_tasks`, else 1 | 1 |
| without engines, without `--rate-limit` | the reader's `auto_tasks`, else 1 | one per CPU, at most the tasks |

The available proxies are counted once at launch from one listing of the broker
(`linecaster.runtime.run.available_proxies`): those in the file, less those with a live block or broken mark for the
run's hosts (any host when the hosts are not named in an HTTP policy) and those leased by live workers of other runs
(the run's own earlier leases count as available); on a first launch, without a broker yet, all of them. The run
states the count and why (`linecaster.runtime.run.workers_note`, e.g. `250 proxies available → 250 workers, 1 proxy
each`). The workers mostly wait on the network, so their count is not capped by the CPUs; `--workers` gives fewer
(each worker is a process with its own memory).

`auto_tasks` is about 1,000 pages per task for `ImageParquetReader` and about 5 items per task for `ManifestReader`
(`linecaster.blocks.readers.tables.PAGES_PER_TASK`, `ITEMS_PER_TASK`), so a resume repeats little. The harvest
(`pipelines/harvest.py`) asks its reader for one item per task (`task_per_item`): the tasks divide the items, an
item's rows wherever they are in the table (`tables.item_runs`), so every item is whole in its task and a task that
fails costs one item. Its reader also gets `reuse_folder` (`OUT/images`): when it reaches an item it lists the item's
folder once (an fsspec listing) and reads a page whose image file is already there from the storage instead of
fetching it from the source (`linecaster.blocks.readers.existing`); only pages of interrupted items are read back, so
egress stays small. Such a record is complete and says `image.extra.reused`; the console counts it as done but not in
the rate. On a restart the console's size starts with the finished tasks' `media_size` from datatrove's stats files
(`linecaster.runtime.local.size_before`, read in the background). Parquet tables are
divided over the tasks by rows in equal shards, not by files, so a table never needs splitting for a task count.
`--max-pages N` (`--parquet`, IMAGES; the readers' `max_pages`) reads the input as if it ended after its first N
pages, in the same automatic tasks: a smoke test of the real setup. `--limit` counts per task, as in datatrove.

`--rate-limit` holds per worker: each worker process has one fetcher with its limits (`HTTPFetcher.shared`), so a
server sees the workers running at once times the limits; the run states it before it starts
(`linecaster.runtime.run.rate_note`, e.g. `rate limits per worker: 150/60, 3/1 · 1 worker → up to 150/min at a
server`). One worker keeps any rate limit busy: a reader's requests ahead grow while none waits for the limits
(`linecaster.net.http.prefetched`, at most `MAX_AHEAD`), and the fetcher, with its limits and the window it has
grown to, is shared by the tasks a worker runs one after the other (`HTTPFetcher.shared`). With `--proxies` the
limits hold per proxy instead (below), and the run states that (`rate limits per proxy: 150/60 · 100 proxies → up to
15,000/min at a server`; with fewer workers than proxies `· 10 of 100 proxies in use (1 proxy per worker)`).

**Proxies.** `--proxies FILE` sends the http(s) requests through a list of proxies, shared by the workers through the
[broker](broker.md) (`--broker PATH`, any fsspec folder, default `OUT/logs/broker`; runs pointed at one path share
the proxies and their blocks too). Each proxy has one worker at a time, the one that holds its lease, and each worker
holds one proxy (`linecaster.net.proxies.ProxyPool`): it claims a free one usable for the host and, when that one is
blocked or broken, releases it and claims another at once. An HTTP policy's `proxies_per_worker` (per host or at the
root; hosts that share a list share the setting) gives a worker up to N, claimed one by one, or `share`: a fair share
of the proxies not blocked for the host, divided by the live workers, claimed at most 2 at a time and grown by
rebalancing, which also gives back what is beyond it when another worker joins. The host's rate limits hold per
proxy, so per IP, as servers count them: the owner spaces the requests through a proxy to a host by the strictest
limit, and each request goes through the owned proxy whose turn comes first. A proxy is left out when the failure is
its own. A block (a 429, until its `Retry-After`, else for the host's `blacklist_ttl`, an hour by default; a status in
`blacklist_on`; an HTML page where another format was expected, a resource's format or an image) is a mark in the
broker for that host: the owner stops using the proxy there at once, releases it once it is blocked for every host it
uses, and whoever claims it later sees the mark, so no worker sends a request into another's block, and a restarted
run none into a block it found before. A broken proxy (a proxy error, no connection to it, `blacklist_threshold`
failures in a row) is marked for every host for `blacklist_ttl`. A block does not count as an attempt and the request
goes on through another proxy at once, so `max_retries` (retries after the first attempt) counts only the attempts
that reached the server and failed there; a block page does not count toward the breaker either. A timeout is mostly
a slow server: it is retried and leaves the proxy in. When none of a worker's proxies is usable for a host and none
is free to claim, its requests to the host pause until a block ends or another worker gives a proxy back (one warning
when the pause starts, one when it ends; the wait is in the fetch record's `pause_seconds`); a pause that would pass
the host's `max_pause` (6 hours) stops the run (`StopRequests`) and says when the first proxy returns. An HTTP policy
can set `blacklist_ttl: 72h`, `blacklist_threshold` and further statuses that block a proxy at the host
(`blacklist_on: [403]`). The console shows the proxies the worker holds, those blocked and those free. On Ray each
task is a process of its own; the next task on a machine takes over the worker slot the last one handed over, and
with it its proxies. The file holds one proxy per line, a URL or `host:port[:user:pass]` as Webshare lists them; the
run record keeps its name, logs show proxies without credentials (`linecaster.net.http.redact`), and the broker names
them by a hash of host and port.

**Failures.** Each fetcher has a breaker (`linecaster.net.http.Breaker`): when most attempts of the last minute got a
server error (5xx, Cloudflare's 520-524 among them), its requests pause, a probe goes out now and then (waits doubling
from one to ten minutes), and the first answer that is not a server error lets them go on; the pages wait instead of
failing. A single server error is retried (with a proxy list without counting against the proxy it came through). A
429 (a status in the host's `pause_on`) on a direct connection pauses the worker that got it
(`linecaster.net.http.Pause`): its requests to that host wait until the response's `Retry-After` has passed (seconds
or an HTTP-date; without one a minute, doubling while 429s keep coming, up to an hour), then the request that got it
is tried again, without using up one of its retries; 429s for requests already in flight extend the pause, never
shorten it. The pages wait instead of failing, and other workers go on. The log says when a pause starts (host,
status, how long, until when) and when the requests go on, and a page's fetch record has the time paused
(`pause_seconds`). A worker that would pause more than the host's `max_pause` (6 hours) since its last successful
response stops the run. Through proxies a 429 blocks that proxy at the host instead (above). A
local task that fails is logged and the others go on (`LocalExecutor`); it runs again on the next launch. An error
that is not the pages' (`NOT_THE_PAGES`) or `FAILED_IN_A_ROW` failed tasks in a row in one worker stop the run.
`--retry-failed` runs the finished tasks that left rejects again; `kill -USR1 <pid>` dumps every thread's stack.
On Ray (`linecaster.runtime.ray.RayExecutor`) the same error stops the run through a marker in the logging folder
(`stopped.json`): every task after it ends before its pipeline starts, so none sends a request into the block that
stopped the first, and the launch fails with that task's error; a launch that left tasks unfinished fails too, so the
Ray job does not end as succeeded. A new launch removes the marker.

**Resources.** `pipelines/harvest.py --items TABLE --item-key COL` fetches items' remote files other than page images
(`ResourceReader`): from URL templates per kind (`--resource marcxml=https://lccn.loc.gov/{item}/marcxml`) or a table
with one row per resource (`--url-key`, `--kind-key`, `--name-key`). Each is checked (XML, JSON or an image must parse;
an HTML page where another format was expected fails and counts toward the breaker, or through proxies blocks that
proxy at the host) and kept as a raw copy,
`OUT/<kind>/<item>/<name>.<ext>` (`ResourceFilesWriter`), the reference later stages link to, with its fetch record in
`OUT/resources/<rank>.jsonl.gz` (`ResourceRecordWriter`: source and final URL, status, type, size, `sha256`, ETag,
Last-Modified, time). One item per task, `--max-items` for a smoke test, copies already there read back. `--http-policy FILE`
gives the run's requests their settings from one YAML file (`linecaster.net.policy`): for every host at the root, and
under `hosts:` an entry for each host that differs, whose fields replace the root's; the run's own options go between
the two. The settings: rate limits (per proxy through proxies), proxies or direct, User-Agent, deadline, retries
(`max_retries`), the broker (root only), how long and when a proxy is left out (`blacklist_ttl`, `blacklist_threshold`, `blacklist_on`),
how many proxies a worker holds (`proxies_per_worker`: 1, N or `share`),
`pause_on` statuses that pause the worker's requests until `Retry-After` has passed (default `[429]`) with
`max_pause`, and `stop_on` statuses and `html` that stop the run without a retry (a status in both `pause_on`, or its
default, and `stop_on` is refused; `pause_on: []` with `stop_on: [429]` stops on a 429). For `--items` and
`--parquet`; with rate limits in the file for a host without proxies a run keeps one worker, with proxies for every
rate-limited host it gets one per available proxy (above).

## The console

A local run (`--on local`, `linecaster.runtime.local.LocalExecutor`) shows on the terminal: one line naming the
pipeline (its blocks, without the builder's boundaries; pages, tasks and workers; what an earlier launch finished), a
live progress line (pages done of the total, rate over the last five minutes, size, failed pages, the task, the time
left) pinned to the terminal's top row, with everything else scrolling below it (a scroll region, `Pinned`), a line per finished task and a summary, in human units
(`linecaster.runtime.console`). The `Progress` observer, which the runtime puts on every stage, counts the pages
that leave the pipeline; with several workers each worker process reports its counts to the console about every
second. Off a terminal the progress is a log line every 30 s instead.
datatrove's own console output (its pipeline listing and stats block per task, the merged stats) goes only to the
task logs (`OUT/logs/logs/task_<rank>.log`, in its full line format) and the stats files, which keep it whole. A launch
lists the completion markers once instead of looking them up task by task.

## Secrets

`linecaster.runtime.secrets.EnvVar("NAME")` names an environment variable; the value is read in the task
(`resolve()`), never stored: an `EnvVar` pickles by name, `to_dict()` writes `{"env": "NAME"}`.
`Served(endpoint, model, api_key=EnvVar("NAME"), headers={"X-Team": "ocr", "X-Token": EnvVar("TOKEN")})` (and
`Chat(preset, endpoint, api_key=..., headers=...)` alike) sends `Authorization: Bearer <key>` and the headers with
every request through saturate's `AdaptiveClient(headers=...)`;
a key given as text is refused. A missing variable fails the block's warm-up.

## The item stage

The item-level steps follow a `Binder`; the usual shape (`pipelines/bind.py`, and `--item-texts` of
`pipelines/transcribe_modular.py`):

```python
[PageRecordReader(pages, fetch_images=False, item_shards=True),
 Binder(),                                                  # page records -> item records
 Recomposer("unicode-recomposition@1", unit="item"),        # paragraphs continued across page breaks
 CharacterNormalizer("latin-historic@1", unit="item"),      # normalized lines, paragraphs, table cells
 Composer("docling-composition@1", unit="item"),            # the item's document
 ItemTextWriter(f"{out}/texts"),                            # texts/<variant>/<rank>.jsonl.gz (format="files": <item>.txt|md)
 ItemDocumentWriter(f"{out}/documents", formats=("md", "txt", "json"), by_format=True)]   # documents/<format>/<item>.<ext>
```

A `Splitter` after the item-level blocks passes each item's pages on as pages (e.g. to a `PageJsonlWriter`), with
the paragraphs of the item recomposition.

## Page records

Stored page records are rows `{"schema": "linecaster.page/2", "id", "text", "page", "errors"}` (`PageJsonlWriter`,
`PageParquetWriter`; `PAGE_SCHEMA` in `linecaster.data.page`). `PageRecordReader` brings older rows to today's format
(`UPGRADES`, keyed by the row's `schema`, one version at a time): a `linecaster.page/1` row names a transcription's
steps `model` (read as `steps`); a row without `schema` (the oldest format) names its transcription `ocr`, read as
`ocr_new`; a `.../pages` folder without records is read from its sibling `rows/` (the folder's earlier name).

## HF Jobs helpers

`linecaster.runtime.jobs.dependencies(commit, script=None, engines=True)` spells out what a Job installs from a
pipeline script's metadata; without a script it raises unless `engines=False` (linecaster alone). A derivative
whose own pipeline needs the engine packages passes `ENGINE_SCRIPT` (the modular pipeline script of the checkout,
`pipelines/transcribe_modular.py`), whose metadata lists every engine with its sources and pins.
