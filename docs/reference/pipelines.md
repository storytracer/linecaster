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
    transcription: str | None  # ocr_new, ocr_original, ...; None: page-level (image, metadata) or the item record's

@dataclass(frozen=True)
class Contract:
    unit: str                  # "page", "item" (what the input stream carries) or "any" (servers)
    unit_out: str | None       # set when the block changes the stream's unit (a binder: page -> item)
    reads: frozenset[Part]
    adds: frozenset[Part]
    replaces: frozenset[Part]
    role: str                  # reader, writer, server, model, transform, binder, validator, composite
```

- **The vocabulary** is `PARTS` in `linecaster.catalog.schema`: `image` and `metadata` (page-level), what presets
  produce (`PRODUCES`: `regions`, `reading_order`, `lines`, `baselines`, `text`, `words`, `word_confidences`,
  `line_confidences`, `tables`, `formulas`, `markdown`, `html`, `doctags`, `layout_json`, `latex`), and
  `line_regions`, `hierarchy`, `nfc`, `document`. A part is written `transcription:name` (`ocr_new:lines`);
  `ocr_original:*` is every part of a transcription.
- **Simple blocks** declare class attributes (`unit`, `role`, `parts_read`, `parts_added`, `parts_replaced`) that
  the default `contract()` of `Contracted` reads; page-level names stay page-level, the others belong to the
  block's `transcription`. Blocks whose parts depend on their options compute `contract()`.
- **Model blocks** read the page image (recognition also `lines`, tables and formulas `regions`) and add their
  preset's `capabilities.produces`: the preset of the `InProcess` backend (`preset`), of the `Served` backend
  (`preset`, set by `runtime.run.engines`) or of the chat adapter; without a preset the engine class's
  `capabilities` (read from its source in the repository, else from the class); without either the step's default.
  The chat recognizers add `text` too, `RegionRecognizer` also `lines`.
- **Readers** add `image` and `metadata`; `ManifestReader(existing_ocr=True)` also `ocr_original:*`;
  `PageRecordReader` what `provides=` declares (`["ocr_new:lines", ...]`), or anything (`*`, reads after it are
  not checked) when it declares nothing. With `fetch_images=False` it brings no `image`.
- **Writers** read what they write and add nothing (`PageFileWriter`: `lines` for hOCR, ALTO and PAGE, `text` for
  md and txt, `document` for HTML, DocLang and JSON, `image` for plots). **Servers** have role `server` and unit
  `any`.
- **Binders** change the unit: `ItemTexts` reads `text` and adds the item record's `text`, `BindItem` reads
  `regions` and `lines` and adds the item's `document`; item writers read those.
- A step without a contract (a plain datatrove step) passes pages and touches no part.

| Block | Reads | Adds | Replaces |
|---|---|---|---|
| `SingleRegionLayout` | `metadata` | `regions`, `reading_order` | |
| `LineAssigner` | `lines`, `regions` | `line_regions` | `regions`, `reading_order`, `lines` |
| `UnicodeNormalizer` | `text` | `nfc` | `text` |
| `Typographer` | `regions`, `lines` | `hierarchy` | `regions`, `lines` |
| `Composer` | `regions`, `lines` | `document` | |
| `ImageFetcher` | `metadata` | | `image` |
| `ImageConverter` | `metadata` | | `metadata` (with `keep_bytes` also `image`) |
| `RecipeStamper` | | | |

## Block shapes

- **Per-unit transform** (`shape = "unit"`): `process_page(doc, page) -> page | None`; `PageBlock` owns the loop
  and the stats. In-process model blocks have this shape.
- **Stream transform** (`shape = "stream"`): overrides `run(data)` and yields each page when it is done, possibly
  out of order (served model blocks, `PageRecognizer`, `RegionRecognizer`). It reports what happens to each page
  inside it with `notify(doc, event)`: `prepare` when a request is built, `done` when its result came back.
- Only readers and writers see `rank`, `world_size` and files (a test walks every block class); the blocks that
  still write a rejects file per task are listed in that test.

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
(or by the stage's reader); a part is added by one block only, unless a later block declares it in `replaces`;
units fit (a page block cannot follow an item stream, an item block needs a binder before it); server blocks go
last; a served model block whose endpoint is a server block of its stage (same loopback port) finds its model in
that server's list; the alternatives of a group add the same parts, sit next to each other, each with a condition,
`OTHERWISE` last; names given to `until`, `after` and `taps` fit exactly one block.

**Order** is the given one; the builder checks it and does not reorder. It inserts the `RecipeStamper` before the
first writer when the run follows a recipe, and moves the server blocks at the end into the stage of the model
blocks when it cuts.

**Branches**: `branch(block, when=Condition, group=None)` gives a block a condition, a picklable predicate on the
page record with a `describe()` (`MetadataEquals(key, value)`, `OTHERWISE`). The block processes the pages the
condition accepts; the others pass unchanged. Blocks with the same `group` are alternatives: each page goes through
the first one whose condition accepts it. A per-unit block gets its pages one by one; any other block one stream of
them, the pages it does not take passed on as it yields.

**Composites**: `Composite(name, blocks, contract=None)` expands into its blocks (nested composites too); its
outward contract is derived (what its blocks read that none of them adds, what they add and replace) unless given.
`ModularTranscriber(lines, recognition, layout=None, formulas_separately=False, transcription="ocr_new")` is layout
(or the page as one region) → lines → line assignment → line recognition; each step a block or a backend.

**Stages**: with `tasks > 1`, the first binder (a block whose stream changes from pages to items) cuts the
pipeline, unless the reader already gives each task whole items (`ManifestReader`, `PageRecordReader(item_shards=
True)`). The first stage writes its page records in item shards into `<run_folder>/pages/` (the pipeline's own
`PageJsonlWriter` there, now with `item_shards=N`, N = `tasks` unless it set its own); the second starts with
`PageRecordReader(item_shards=True, fetch_images=False)` declaring the parts the first stage added, runs the binder
and what follows, as N tasks. One stage logs to `OUT/logs/`, two to `OUT/logs/pages/` and `OUT/logs/items/`; the run
record lists the stages. Each stage gets its own executor, and the later one `depends=` on the earlier one:

| `--on` | Executors | Stages |
|---|---|---|
| `local` | `LocalPipelineExecutor` | the second starts when the first is complete |
| `ray` | `RayGPUExecutor` for stages with servers, `RayPipelineExecutor` for the item stage | the same, through `depends=` |
| `hf-jobs` | `JobsPipelineExecutor` (`GPUJobsExecutor` for multi-GPU flavors on stages with servers) | consecutive launches: the second launches when the first's Jobs are complete; both on `--flavor` |

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

`linecaster.runtime.observers.Observer` has `on_task_start(rank, world_size)`, `on_enter(block, doc)`,
`on_exit(block, doc, error=None)`, `on_unit(block, doc, event, **attributes)` (from stream blocks' `notify`, called
in saturate's prepare threads for `prepare`) and `on_task_end()`. When a stage has observers (`build(...,
observers=[...])`, taps), the builder puts a `Boundary` after every block: the boundary between block *i* and *i +
1* calls `on_exit(i)` and `on_enter(i + 1)` for each page, so a block's time per page includes waiting in a served
window; `error` is the entry the block added to `doc.metadata["errors"]`. Boundaries are plain callables, not
datatrove steps, so they add no stats; a stage without observers has none.
