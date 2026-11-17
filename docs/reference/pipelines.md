# Pipelines: contracts and the builder

A pipeline is a list of components (datatrove `PipelineStep`s) and composites. Before it runs, the builder
(`linecaster.execution.builder`) checks the components' contracts, expands the composites, and cuts the pipeline into
stages. Every pipeline script goes through it (`linecaster.execution.run`). Terms are the [glossary](glossary.md)'s.

## Contracts

Every component returns its contract from `contract()` (`linecaster.core.contract`):

```python
@dataclass(frozen=True)
class Part:
    name: str                  # a name of PARTS, or "*" (every part)
    transcription: str | None  # ocr_new, ocr_original, ...; None: page-level (image, metadata, transcription_file)
                               # or the item record's

@dataclass(frozen=True)
class Contract:
    unit: str                  # "page", "item" (what the input stream carries) or "any" (servers)
    unit_out: str | None       # set when the component changes the stream's unit (binder: page -> item, splitter: back)
    reads: frozenset[Part]
    adds: frozenset[Part]
    replaces: frozenset[Part]
    removes: frozenset[Part]   # parts the component does not pass on (gone for every later component)
    role: str                  # reader, writer, server, model, transform, binder, splitter, validator, composite
```

- **The vocabulary** is `PARTS` in `linecaster.catalog.schema`: `image`, `metadata` and `transcription_file` (a
  library's own transcription delivered with the page, as a document media) (page-level), what presets produce (`PRODUCES`: `regions`, `reading_order`, `lines`, `baselines`, `text`, `words`, `word_confidences`,
  `line_confidences`, `tables`, `formulas`, `markdown`, `html`, `doctags`, `layout_json`, `latex`), and
  `line_regions`, `hierarchy`, `paragraphs`, `document`. A part is written `transcription:name` (`ocr_new:lines`);
  `ocr_original:*` is every part of a transcription.
- **Simple components** declare class attributes (`unit`, `role`, `parts_read`, `parts_added`, `parts_replaced`,
  `parts_removed`) that
  the default `contract()` of `Contracted` reads; page-level names stay page-level, the others belong to the
  component's `transcription`. Components whose parts depend on their options compute `contract()`.
- **Model components** read the page image (recognition also `lines`, tables and formulas `regions`) and add their
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
  md and txt, `document` for HTML and JSON, `image` for plots). **Servers** have role `server` and unit
  `any`.
- **The `ItemAssembler`** changes the unit from pages to items, the **`ItemSplitter`** back: an item record holds its page
  records, so what the pages carried stays available across either (the checks carry the parts over), apart from
  the page image's bytes (`image`: an item record has none) at the binder and the item's `document` at the splitter.
- **Item-unit components** (`ParagraphBuilder(unit="item")`, `DocumentComposer(unit="item")`)
  read item records: one datatrove document per item, `doc.metadata["item"]` holding the item id and its page records
  in order (`linecaster.core.item`); they read and add the parts of the pages' transcriptions, the item
  `DocumentComposer` adds the item's `document` next to the record. **Item writers** (`ItemDocumentWriter`, `ItemTextWriter`)
  read the `document` and write it by each text's transcription strategy.
  `RecipeStamper` has unit `any`: before an item writer it stamps the pages of each item record.
- A step without a contract (a plain datatrove step) passes pages and touches no part.

| Component | Reads | Adds | Replaces, removes |
|---|---|---|---|
| `LineAssigner` | `lines`, `regions` | `line_regions` | `regions`, `reading_order`, `lines` |
| `HierarchyDetector` | `regions`, `lines` | `hierarchy` | `regions`, `lines` |
| `ParagraphBuilder` | `regions`, `lines` | `paragraphs` | `paragraphs` (made anew where they exist) |
| `DocumentComposer` | `regions`, `lines` (and `paragraphs` when there are) | `document` (rendered, not stored; no annotator) | |
| `Tagger` | `regions`, `lines` (the model tagger: `image` and its targets, regions or lines) | `tags` | |
| `ImageFetcher` | `metadata` | | `image` |
| `ImageConverter` | `metadata` | | `metadata` (with `keep_bytes` also `image`; without it removes `image`) |
| `TranscriptionConverter` | `metadata`, `transcription_file` (with `source="media"`) | `<transcription>:*` | |
| `RecipeStamper` | | | |

## Component shapes

- **Per-unit transform** (`shape = "unit"`): `process_page(doc, page) -> page | None`; `PageComponent` owns the loop
  and the stats. In-process model components have this shape.
- **Stream transform** (`shape = "stream"`): overrides `run(data)` and yields each page when it is done, possibly
  out of order (served model components, `PageRecognizer`, `RegionRecognizer`). It reports what happens to each page
  inside it with `notify(doc, event)`: `prepare` when a request is built, `done` when its result came back. The
  served model components share one streaming loop (`ModelComponent`): a component names its requests (`_rows`: one per page, one
  per region for `RegionRecognizer`), builds and parses each (`_request`, `_parse`) and says which pages a finished
  one completes (`_done`).
- Only readers and writers see `rank`, `world_size` and files (a test walks every component class, with no exceptions):
  a component that rejects a page records why on the page, and the `RejectWriter` names the task's file.

## Backends

A model component's backend (`linecaster.backends`) says where its engine runs:

- `InProcess("pkg:Class", **options)` (or `InProcess.from_preset(ref)`; a model component given a preset ref,
  `LayoutDetector("single-region")`, builds one): the engine loads in the worker;
- `Served(endpoint, model=name, ...)`: `linecaster serve` (or a server speaking its routes) hosts it, reached through
  saturate on `/v1/linecaster/{step}`; `warm_up()` refuses a server whose `/health` names another transcription
  format than `linecaster.page/4`, or none;
- `Chat(preset, endpoint=None, served_name=None, max_window=32, initial_window=4, read_timeout=600.0, api_key=None,
  headers=None, prefer="page")`: a chat preset's VLM behind an OpenAI-compatible server (vLLM, SGLang, a hosted
  endpoint) on `/v1/chat/completions`; `preset` is a preset ref, a model's Hugging Face id (its preset with unit
  `prefer`) or a configured adapter (`chat_model`); without an endpoint, the task's `VLMServer` on port 8000.
  `PageRecognizer(backend)` and `RegionRecognizer(backend, labels=..., pad=None)` (`pad`: the adapter's `region_pad`, else 8) take it (or a chat preset's ref).
  `Chat(..., overrides={...})` sets the chat engine's options over the preset's settings (`max_tokens`, `temperature`,
  `top_p`, `repair_max_tokens`, `repair_temperature`, `repetition_detection`; `--set recognition.<option>=<value>` in
  `pipelines/transcribe_vlm.py`, and `--no-repetition-detection` there to turn the last off: it is on by default
  where the preset's vLLM takes it); the ones that differ from the preset's are recorded with the adapter
  (`overrides`) and count in `pipeline_sha256`. With `repair_max_tokens` set, `PageRecognizer` runs the
  [repair passes](glossary.md): a page whose completion stopped at `max_tokens` waits while its repair requests go
  into the same window, one per cap while each stops at its cap, and leaves the component with every pass recorded as a
  raw output (`pass`, `kept`: the one its annotations were parsed from); `PageRecognizer(..., repair_only=True)` sends only
  the repair requests, for page records read with `PageRecordReader` (`--pages ... --repair-only`). The streaming
  loop of `ModelComponent` offers this to every served component: a finished request may ask for a second one
  (`_second_request`), whose response comes back with it (`_second_done`), and that one for another
  (`_next_request`).
  `PageRecognizer` also takes a page engine's `InProcess` or `Served` backend (or its preset's ref): a stream
  transform served, a per-unit transform in-process; it reads the page image and adds `text` and what the preset
  produces. A page engine's `endpoint` option (where its service is) is operational.

The built-in engines (`layout.single-region.v1`, the rule-based steps' and the taggers) run in the pipeline's
process only: `runtime.run.engines` keeps a preset of one in-process when the other models are served, and
`linecaster serve` refuses them.

**The `Tagger`** (`linecaster.components.tagging`) runs a tagging engine on every page, by preset or engine spec like
the rule components (`Tagger("geometry-tags")`, `Tagger(InProcess("linecaster.engines:ChatTaggingEngine",
schemes=["degraded"], panel=[...]))`, `options` over either), and adds `tags`: classifications in property schemes
([data model](data-model.md#classifications)). It decodes the page image only for an engine that reads it (the
model tagger, a client of chat servers that the run provides), and passes the page's id, which review items name.
Stats: `tagged`, `undecided`.

## The builder

```python
plan = build(components, tasks=8, until=None, after=None, taps={"LineAssigner": "OUT/taps/lines"},
             run_folder="OUT", recipe=("squiddle", "sha256:..."))
plan.check()          # PipelineConfigError listing every problem
plan.stages           # [Stage(name, tasks, components, pipeline)]: one datatrove pipeline each, run in order
plan.graph            # nodes (components; composites expanded, their group kept), edges (part -> the component reading it)
plan.mermaid()        # the graph as a Mermaid flowchart: stages and composites as subgraphs
plan.describe()       # stages with each component's contract, the edges, the problems
```

**Checks**, all collected: a stage starts with a reader; every part a component reads is added earlier in its stage
(or by the stage's reader) and not removed since (`removes`, even after a reader that provides anything); a part
is added by one component only, unless a later component declares it in `replaces`;
units fit (a page component cannot follow an item stream, an item component needs a binder before it); the parts carry
across a binder and a splitter (apart from `image` and the item's `document`); server components go last; a served model
component whose endpoint is a server component of its stage (same loopback port) finds its model in that server's list; the alternatives of a group add the same parts, sit next to each other, each with a condition,
`OTHERWISE` last; names given to `until`, `after` and `taps` fit exactly one component.

**Order** is the given one; the builder checks it and does not reorder. It inserts a `TranscriptionConverter` (into
`ocr_original`) right after a component that adds `transcription_file` when no later component reads it, the
`RecipeStamper` before the first writer when the run follows a recipe, a `RejectWriter` into
`<run_folder>/rejects` before the first writer (or binder) when there is a run folder and the pipeline has none, and moves the server components at the end into the
stage of the model components when it cuts. `build(..., max_page_errors=SHARE)` sets every page component's error budget.

**Branches**: `branch(component, when=Condition, group=None)` gives a component a condition, a picklable predicate on the
page record with a `describe()` (`MetadataEquals(key, value)`, `OTHERWISE`). The component processes the pages the
condition accepts; the others pass unchanged. Components with the same `group` are alternatives: each page goes through
the first one whose condition accepts it. A per-unit component gets its pages one by one; any other component one stream of
them, the pages it does not take passed on as it yields.

**Composites**: `Composite(name, components, contract=None)` expands into its components (nested composites too); its
outward contract is derived (what its components read that none of them adds, what they add and replace) unless given.
`ModularTranscriber(lines, recognition, layout, formulas_separately=False, transcription="ocr_new")` is layout
(`"single-region"`: the page as one region) → lines → line assignment → line recognition; each step a component, a
backend or a preset.

**Stages**: with `tasks > 1`, the first binder (a component whose stream changes from pages to items) cuts the
pipeline, unless the reader already gives each task whole items (`ManifestReader`, `PageRecordReader(item_shards=
True)`). The first stage writes its page records in item shards into `<run_folder>/pages/` (the pipeline's own
`PageJsonlWriter` there, now with `item_shards=N`, N = `tasks` unless it set its own); the second starts with
`PageRecordReader(item_shards=True, fetch_images=False)` declaring the parts the first stage added, runs the binder
and what follows, as N tasks. A `ItemSplitter` after the binder needs no cut of its own: the items are whole in the
task, so its pages are too. One stage logs to `OUT/logs/`, two to `OUT/logs/pages/` and `OUT/logs/items/`; the run
record lists the stages. Each stage gets its own executor, and the later one `depends=` on the earlier one:

| `--on` | Executors | Stages |
|---|---|---|
| `local` | `LocalPipelineExecutor` | the second starts when the first is complete |
| `ray` | `RayGPUExecutor` for stages with servers, `RayExecutor` for the item stage and pipelines without engines (CPUs only) | the same, through `depends=` |
| `hf-jobs` | `JobsExecutor` (datatrove's `JobsPipelineExecutor` with JSON-lines logs; `GPUJobsExecutor` for multi-GPU flavors on stages with servers) | consecutive launches: the second launches when the first's Jobs are complete; both on `--flavor` |

**Partial runs** (components named by their datatrove `name`, their class name, or a composite's name for its last
component):

- `until=BLOCK` (`--until`): the components up to and including BLOCK, then a `PageJsonlWriter` into
  `<run_folder>/pages` (and the server components);
- `after=BLOCK` (`--after`, with `--pages DIR`): the pipeline's `PageRecordReader`, then the components after BLOCK;
  the reader declares the parts the components up to BLOCK add;
- `taps={BLOCK: DIR}` (`--tap-after BLOCK DIR`, repeatable): a `Tap` observer writes every page record as it
  leaves BLOCK into `DIR/<rank>.jsonl.gz`.

**In this process**: `run_pages(components, docs)` checks the components and runs them on `docs` (datatrove documents) as
task 0 of 1, without an executor (a leading reader reads its own input after them); `run_plan(plan)` runs a plan's
stages that way. A pipeline script's `--page IMAGE OUT` runs its pipeline on one image like that, and `linecaster
page IMAGE OUT [--recipe R | --pipeline ID] [pipeline options]` finds the script (the recipe's pipeline, else
`transcribe_modular.v1`) and runs it so.

`--dry-run` prints the plan (`describe()` under `plan`, with the run record) and the Mermaid graph, and fails like
a run would when there are problems; a run with problems exits with code 2 before it writes anything.

## Observers

`linecaster.core.observers.Observer` has `on_task_start(rank, world_size)`, `on_warm_up(component, seconds)`,
`on_enter(component, doc)`, `on_exit(component, doc, error=None)`, `on_unit(component, doc, event, **attributes)` (from stream
components' `notify`: `prepare` and `request` in saturate's prepare threads, `request` with a `carrier` dict for the
trace context, `done` with `error`, tokens and `finish_reason`; `region` for a request per region),
`on_task_event(block, event, start_ns, end_ns, **attributes)` (from `Component.report`: a reader's `file`, a writer's
`flush`), `on_leave(doc)` (a page leaves the stage's last component), `on_task_end(error=None)` (also when the task
fails) and `environment()` (variables for a server a component starts in the task). When a stage has observers
(`build(..., observers=[...])`, taps, tracing), the builder puts a `Boundary` after every component: the boundary
between component *i* and *i + 1* calls `on_exit(i)` and `on_enter(i + 1)` for each page, so a component's time per page
includes waiting in a served window; `error` is the entry the component added to `doc.metadata["errors"]`. Boundaries
are plain callables, not datatrove steps, so they add no stats; a stage without observers has none.

Every stage with a run folder (or an OTLP endpoint) is traced: the builder adds a `linecaster.tracing.Tracing`
observer (`build(..., trace_share=SHARE)`, `--trace-share`; [tracing](tracing.md)).

## Warm-up

Every component has `warm_up()` (idempotent): engines load there (`InProcess.warm_up()`), servers start there
(`EngineServer`, `VLMServer`), a served backend reads its secrets there; components with nothing to load keep the
no-op. A component's `__call__`, which datatrove's executors call, warms it up before its `run` starts: components warm up
as the stream reaches them, the last one first (the servers before the components that call them). The time is the
component's own stat, `warm_up_seconds` (per task), and goes to the observers (`on_warm_up(component, seconds)`); a page's
measured `seconds` never include loading. An error in a warm-up fails the task (a server that does not start: a
`ServerError`).

## Failures

- **Per page.** An exception in a per-unit transform's `process_page` (other than a `PipelineConfigError`,
  `CatalogError` or `ServerError`, which fail the task) becomes an entry in the page's `doc.metadata["errors"]`:
  `{"component": class, "step": a model component's step, "preset": its id or null, "type": the exception's class,
  "error": the message}`; a failed request of a served component is the same with type `ServerError`; checks
  (`PageValidator`, `ImageConverter`) add `field` and `raw_value`. The page goes on as it was.
- **Later model components pass it by** (`skip_on_error`, the default for model components; stat `skipped_after_error`), at
  once: in-process the page leaves the component before the next one enters, served it is put straight onto the
  component's results (it never waits for the window, nor for the end of the input).
- **Rejects.** The `RejectWriter` writes every page that carries errors to `OUT/rejects/<rank>.jsonl`, one line
  per error (`key`, `field`, `error`, `raw_value`, and the entry's `component`, `step`, `preset`, `type`), and passes
  it on: the page records keep failed pages with their errors, so a later pipeline reading them passes them by too.
  `PageFileWriter(skip_failed=True)` writes no per-page files for them (the modular pipeline's `--files`), so a
  file is never what the components before the failure made of a page.
- **The error budget.** A component may fail on `max_page_errors` of a task's pages (`--max-page-errors`, default
  0.01), judged from the 100th page on: from then, more errors than `share × pages` fail the task with a
  `PageError` (with the default: two failures in the first 100 pages, three in 300). Fewer pages are too few to
  judge. datatrove reruns a failed task whole.
- **Page images** (`linecaster.images.pixels`). The model components give engines plain 8-bit RGB pixels (Pillow's
  `convert("RGB")` of the file: no ICC profile applied, no EXIF orientation), decoded once per page and process: the
  components after the first that needs a page's image use the same read-only array (stats `image_decoded`,
  `image_shared`). `--image-decode` (`ModelComponent.image_decode`, set by the builder) says how: `auto` (the default)
  decodes JPEG, JPEG 2000 and TIFF in 8-bit gray or RGB on an NVIDIA GPU where the machine has one and
  `linecaster[nvimgcodec]` is installed, the worker's GPU, everything else with Pillow; `cpu` always with Pillow;
  `gpu` like `auto`, but a machine without a GPU is an error. A served component sends its choice with the image, and
  `linecaster serve` decodes there; a chat adapter builds its request from the same pixels. A GPU and Pillow round a
  lossy image's pixels differently, so a step records its decoder (measurement `decoder`); an image a GPU refuses,
  or a GPU that fails, is decoded with Pillow (stats `gpu_decoded`, `cpu_decoded`, `gpu_decode_refused`,
  `gpu_decode_errors`). The option is operational: it is not part of `pipeline_sha256`, since `auto` depends on the
  machine anyway.
- **Errors** (`linecaster.errors`): library code raises `PipelineConfigError` (a pipeline, option or input that
  cannot work; `problems` lists them), `CatalogError`, `PageError(page_id, component)` and `ServerError`, all
  `LinecasterError`s, never `SystemExit`; the `linecaster` command and a pipeline script's `main` turn them into
  exit codes (2: nothing was launched).

## The run record

`OUT/run.yaml` (schema `linecaster.run-record/2`, the pydantic model `linecaster.execution.record.RunRecord`, JSON
Schema `catalog/schemas/run-record-2.json`) records the script, the recipe, the command line, the options, where it
ran and the software, and:

- `pipeline`: per stage its name, tasks and components in order, each component as its `to_dict()` (below) with its
  `contract`, composite, group and condition;
- `pipeline_sha256`: the hash of the pipeline's **functional** parameters.

**`to_dict()`** gives a component as it was built: `{"component": class name, "class": "module:Class", "params": {...}}`,
every constructor parameter with the value it was given or its default (`**kwargs` flattened), JSON-compatible:
backends as `{"backend": "in-process", "engine", "options", "preset", "preset_sha256"}`, `{"backend": "served",
"endpoint", "model", "max_window", ..., "preset", "engine"}` or `{"backend": "chat", "adapter", "preset",
"preset_sha256", "model", "revision", "served_name", "endpoint", "max_window", ...}` (a chat adapter's dict plus where
its server is), nested components as their dicts, secrets as `{"env": NAME}`, folders as paths, callables as `module:name`. A component
keeps the arguments it was constructed with; `live_params` names those the builder may change afterwards (a page
record reader's `provides`). A composite's dict is its group: its parameters and its components' dicts.

**Functional and operational parameters.** A parameter is *functional* when changing it can change what a run
writes for a page or an item (its page records, files and texts) or how they are partitioned (`item_shards`); it is
*operational* when it only changes where things are read and written, how the work is spread and paced, or how a
server is reached. `pipeline_sha256` covers the functional ones (`provenance.functional_pipeline`):

| Operational (left out) | Why |
|---|---|
| folders and file names: `data_folder`, `output_folder`, `output_filename`, `image_folder`, `manifest_folder`, `ocr_folder`, `folder`, `suffix`, `bucket_by_item`, `prefix` | where things are |
| which input files a task reads and how: `paths_file`, `glob_pattern`, `recursive`, `limit`, `skip`, `shuffle_files`, `batch_size` (a reader's), `http` (rate limits, the IIIF format asked for), `uri_map`, progress bars | the pages themselves are recorded per page |
| servers and clients: `port`, `host`, `python`, `script`, `vllm`, `outside_venv`, `boot_timeout`, `max_queue`, `prepare_workers`, `gpu_memory_utilization`, `extra_args`; an in-process engine's `endpoint` and `timeout` (`ENGINE_OPERATIONAL`: where its service is); a served backend's `endpoint`, `model` (the name it is hosted under, unless nothing else names its engine), `max_window`, `initial_window`, `read_timeout`, `api_key`, `headers`; a chat backend's `served_name` and the same (it counts by its adapter, preset and hash, model and revision) | how a server is started and reached |
| `name` (datatrove's display name), `compression`, `max_file_size`, `ImageConverter.keep_bytes`, `.skip_existing`, `.window`, `.initial_window`, `.max_window`, `ImageFolderReader.read_images` | presentation, file handling, memory, how many pages are in flight |
| server components (`EngineServer`, `VLMServer`, `VendorServer`) as a whole | their models count through the components they serve |
| the backend (in-process or served) | a model component counts by its engine, the engine's options and the preset with its hash, wherever it runs |

Everything else is functional: component classes and their order, transcription names, engine options, presets and
their hashes, the recipe stamp, conditions and groups, writers' formats, texts and strategies, `item_shards`. The base list
is `OPERATIONAL` in `linecaster.core.component`; a component class adds its own in `operational`. A parameter added
to a released component with a default that keeps the old behavior is left out while it has that default
(`unhashed_defaults`, e.g. `PageRecognizer`'s `repair_only`), so the pipelines that do not use it keep their hash. So a resumed run,
a run on another executor or backend, or into another folder has the same hash; another preset, option or component
has another.

**Resume.** A run into an OUT that holds a run record is checked against its newest record (`run.yaml`, or a later
`run-<time>.yaml`): another `pipeline_sha256` is refused with a `PipelineConfigError` (finished tasks would be
skipped and the folder would mix two pipelines' outputs) unless `--new-pipeline` (the new record is written next
to the earlier one and is the one the next resume is checked against); another `--tasks` is always refused (each
task would read other input), and so is another sample (the record's `sample.selected.sha256`, [samples](running.md#samples)).
The same hash, tasks and sample: a resume, as datatrove's completion markers make it.
`--dry-run` reports the same problems.

**Describe mode.** `linecaster.execution.run.describe(template, argv)` builds a pipeline template's plan in the current
process without its engines: its options parsed, presets resolved without checking that their engines are
installed, nothing loaded or started. `describe_recipe(ref)` describes a recipe that way (the template of the
recipe's pipeline id, `linecaster.templates.template(id)`, with `--recipe REF` and placeholder folders): what
`linecaster catalog index` records as the recipe's `pipeline_sha256` and `verify` compares ([catalog](catalog.md)).

## Pipeline templates

A pipeline script's code is a pipeline template in `linecaster.templates` (`harvest`, `convert`, `transcribe_modular`,
`transcribe_vlm`, `transcribe_page`, `bind`, `import_transcriptions`, `score`): its docstring (the help text), `options(ap)`, `models(a)`,
`pipeline(a, script)`, `PIPELINE` and, where recipes fill it, `SLOTS`. `linecaster.templates.templates()` lists them by
pipeline id and `template(id)` finds one; importing one imports no engine. The script in `pipelines/` is its PEP 723
block, a docstring and the call that runs the template:

```python
from linecaster.templates import transcribe_modular as template
from linecaster.execution import run

if __name__ == "__main__":
    run.main(__file__, template.__doc__, template.options, template.models, template.pipeline, template.PIPELINE,
             template.SLOTS)
```

A downstream project's script runs a shape the same way, in its own environment (the engine packages its slots need), and
may lay its own defaults over the shape's options: an `options` that calls the shape's and
then `ap.set_defaults(...)` (`--recipe` too, which `run` adds before the script's options), and a `pipeline` that
fills a default depending on other options before it calls the shape's. Its run records name its script; its
`pipeline_sha256` is the shape's for the same options.

## Importing ground truth

`pipelines/import_transcriptions.py` (`import_transcriptions.v1`) reads a source's documents into page records with
one importer (step `import`, slot `import`): a Parquet table's column holding each document (`--data-key`: a wiki
page's wikitext), a column naming a file (`--uri-key`), or the file delivered with the page; `--context-key` columns
are the document's context, `record`, `revision` and `dataset` its source's fields. Its pages are named, not read
(`ImageParquetReader(read_images=False)`, or no `--image-key`): importing needs no image. Its page records are what
`linecaster score` reads as a ground truth, and what a dataset is assembled from.

## The item stage

The item-level steps follow a `ItemAssembler`; the usual shape (`pipelines/bind.py`, and `--item-texts` of
`pipelines/transcribe_modular.py`):

```python
texts = ("literal:txt", "latin-historic+unicode-marks+flow:md")   # --text, repeatable
[PageRecordReader(pages, fetch_images=False, item_shards=True),
 ItemAssembler(),                                                  # page records -> item records
 ParagraphBuilder("unicode-paragraphs", unit="item"),        # paragraphs continued across page breaks
 DocumentComposer("linked-document", unit="item"),             # the item's document, literal
 ItemDocumentWriter(f"{out}/documents", texts=texts),     # documents/<strategy>/<item>.<ext>
 ItemTextWriter(f"{out}/texts", texts=texts)]             # texts/<strategy>.<format>/<rank>.jsonl.gz (bind: --jsonl)
```

A **text** is the item's document written by a transcription strategy in a format (`<strategy>:<format>`:
`literal` or a catalog strategy, normalizations joined by `+` too; `md`, `txt`, `html`, `json`); nothing is
normalized unless a text names a strategy, and `bind` writes only the literal document as JSON unless `--text` names
others. A JSON Lines row holds `id` (the item), `text`, `spec`, `strategy`, `strategy_sha256`, `normalizations`,
`format`, `page_ids`, `pages` and `token_count` with a token counter. The page files (`PageFileWriter`) take one
`strategy` too (`--strategy`, default `literal`).

A `ItemSplitter` after the item-level components passes each item's pages on as pages (e.g. to a `PageJsonlWriter`), with
the paragraphs of the item recomposition.

## Page records

Stored page records are rows `{"schema": "linecaster.page/6", "id", "text", "page", "errors"}` (`PageJsonlWriter`,
`PageParquetWriter`; `PAGE_SCHEMA` in `linecaster.data.page`): `page` is the page record of the
[data model](data-model.md), its annotation sets with their annotators, raw outputs and annotations. Renderings
(the DocumentComposer's document, the files, the texts) are not part of it. `PageRecordReader` brings older rows to
today's format (`UPGRADES`, keyed by the row's `schema`, one version at a time): a `linecaster.page/4` row through
`page_4_to_5` (the derived text dropped, [data model](data-model.md#from-linecasterpage4)); a `linecaster.page/2` row through
`linecaster.data.upgrade.page_2_to_3` (field by field in the [data model](data-model.md#from-linecasterpage2)); a
`linecaster.page/1` row, whose transcriptions name their steps `model`, to page/2 first; a row without `schema` (the
oldest format) names its transcription `ocr`, read as `ocr_new`; a `.../pages` folder without records is read from
its sibling `rows/` (the folder's earlier name).

## Rendering policy

The components that render (`DocumentComposer`, `PageFileWriter`, `ItemDocumentWriter`, `ItemTextWriter`) take `policy`, a
catalog policy (`id`, default `page-layers`; [catalog](catalog.md#policy-policiesidyaml)), which decides the layer of
each region in the documents, files and texts they write ([data model](data-model.md#rendering)).
`pipelines/transcribe_modular.py` and `pipelines/bind.py` set it with `--policy`; it is a functional parameter, so the
run record names it and `pipeline_sha256` covers it.
