# Phase 2 design (working document)

Interfaces for phase 2 of [the plan](refactoring.md). Removed with the plan when the refactoring is done; what
remains true moves to `docs/reference/`. Terms are the [glossary](../reference/glossary.md)'s.

## 1. Contracts

Every block declares what one call processes and what it reads, adds and replaces in the record.

```python
@dataclass(frozen=True)
class Part:
    name: str                      # a part of the record (vocabulary below)
    transcription: str | None      # the transcription it belongs to (ocr_new, ocr_original, ...); None: page-level

@dataclass(frozen=True)
class Contract:
    unit: str                      # "page" or "item": what the block's input stream carries
    unit_out: str | None = None    # set when the block changes the stream's unit (Binder: page -> item; Splitter: item -> page)
    reads: frozenset[Part] = frozenset()
    adds: frozenset[Part] = frozenset()
    replaces: frozenset[Part] = frozenset()
    role: str = ""                 # "reader", "writer", "server", "model", "transform", "binder", ...
```

- Blocks return their contract from `contract(self) -> Contract`, computed per instance (a block's transcription
  name and options decide its parts). Simple blocks may declare class attributes the default `contract()` reads.
- Model blocks take `adds` from their preset's `capabilities.produces` (the `PRODUCES` vocabulary in
  `catalog/schema.py`); an engine spec without a preset declares them in code (the engine class's `capabilities`).
- Part vocabulary: page-level `image`, `metadata`; per transcription the `PRODUCES` names (`regions`,
  `reading_order`, `lines`, `baselines`, `text`, `words`, `word_confidences`, `line_confidences`, `tables`,
  `formulas`, `markdown`, `html`, `doctags`, `layout_json`, `latex`) plus `line_regions` (lines assigned to
  regions), `hierarchy` (heading levels, splits: the Typographer), `nfc` (the UnicodeNormalizer), `document`
  (the Composer), and in phase 3 `paragraphs`. New names are added here and in the glossary first.
- Readers add `image` and `metadata` (and the transcriptions they bring: `ManifestReader(existing_ocr=True)` adds
  `ocr_original:*`; `PageRecordReader` adds whatever the records carry, declared by the caller or read from the
  first stage's run record: until then `PageRecordReader(provides=...)`).
- Writers read what they write and add nothing; servers (`ModelServer`, `ChatModelServer`) have role `server`.

## 2. The builder (`linecaster.runtime.builder`)

```python
def build(blocks: list, *, tasks: int = 1, until: str | None = None, after: str | None = None,
          taps: dict[str, str] | None = None, run_folder: str | None = None) -> Plan

@dataclass
class Plan:
    stages: list[Stage]            # one datatrove pipeline each, run in order
    graph: Graph                   # nodes = blocks (composites expanded, their group kept), edges = part -> reader
    problems: list[str]            # empty when the pipeline is valid
    def check(self) -> None        # raises PipelineConfigError listing every problem
    def mermaid(self) -> str       # the graph as a Mermaid flowchart (composites as subgraphs)
    def describe(self) -> dict     # for --dry-run and the run record
```

- **Checks**: every part a block reads is added earlier in its stage (or by the stage's reader); a part is added
  by one block only unless a later block lists it in `replaces`; units fit (a page block cannot follow an item
  stream without a `Splitter`); server blocks go last; a model block with a served backend has a server block in
  its stage or an explicit endpoint; a `when=` group (below) adds the same parts in every alternative. All
  problems are collected, not just the first.
- **Order**: the given order is kept; the builder checks it, it does not reorder.
- **Branches**: any block may take `when=Condition` (a picklable predicate on the page record with a `describe()`);
  blocks sharing `group="name"` are alternatives (each page passes through exactly one of them; the last may be
  `when=OTHERWISE`). A page a block's condition rejects passes through unchanged.
- **Composite blocks**: `Composite(name, blocks, contract=None)` expands into its blocks; the outward contract is
  derived (reads not satisfied inside, adds of all) unless given; the graph and the run record keep the group.
  `ModularTranscriber` is the first one.
- **Stages**: when the stream's unit changes to `item` (a `Binder`) and `tasks > 1`, the builder cuts there: the
  first stage ends with `PageJsonlWriter(item_shards=N)` into `<run_folder>/pages/` (N = tasks unless set), the next
  starts with `PageRecordReader(item_shards=True)`. Stages run one after another (`depends=` on datatrove's
  executors; on HF Jobs as consecutive launches if `depends` is not supported). With one task no cut is needed.
- **Partial runs**: `until=BLOCK` keeps the blocks up to and including it, then writes page records;
  `after=BLOCK` starts from page records (a `PageRecordReader` on `--pages`) with the blocks after it; `taps={BLOCK:
  DIR}` adds an observer writing page records after BLOCK. Blocks are named by their datatrove `name` or class
  name; ambiguity is a problem.
- `run_pages(blocks, docs) -> list[Document]` runs blocks without an executor (warm-up included), for tests and
  `linecaster page IMAGE [--recipe R | pipeline options] [--formats ...]`.

## 3. Block shapes and observers

- **Per-unit transform**: `process(doc, record) -> record | None` (today's `PageBlock.process_page`); the base class
  owns the loop, stats, timing, errors, observers.
- **Stream transform**: overrides `run(data)` and yields each document when it is done, possibly out of order
  (served model blocks with their window). It must call the observer hooks for every document.
- Only readers and writers see `rank`, `world_size` and files; a test walks every block class and fails on others
  that use them.
- **Observers** (`linecaster.runtime.observers`): `on_task_start(rank, world_size)`, `on_enter(block, doc)`,
  `on_exit(block, doc, error=None)`, `on_task_end()`. The builder installs them by inserting a boundary step
  between consecutive blocks; the boundary between block i and i+1 calls `on_exit(i)` and `on_enter(i+1)` for each
  document, so per-block spans include time waiting in a served window. Boundary steps add no stats.

## 4. Tracing (`linecaster.tracing`, OpenTelemetry)

- Dependencies in the core: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`.
- Per task: a `TracerProvider` with resource attributes `service.name=linecaster`, `service.version`,
  `linecaster.run`, `linecaster.task`, host, GPU (if any); span processors: a file exporter writing OTLP JSON lines
  to `<run_folder>/traces/<rank>.jsonl.gz`, and the OTLP exporter when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- Task spans, always: `linecaster.task`, `linecaster.warm_up` (per block, with the model and preset),
  `linecaster.server.start`, `linecaster.reader.file`, `linecaster.writer.flush`.
- Page traces: the reader gives every page a trace context (`doc.metadata["trace"]["traceparent"]`, W3C). Sampled
  if `hash(page_id) < rate` (default 0.01, `--trace-sample`), deterministic across reruns. Spans of unsampled
  pages are buffered per page and exported only if the page fails (a custom span processor; memory bounded by the
  pages in flight); sampled pages carry `trace_id` in their page record (`metadata.trace_id`).
- Spans per page: `linecaster.page` (root), one `linecaster.block` per block (from the observers; explicit parent =
  the page's context, never the current context); inside served model blocks `linecaster.request.prepare`,
  `linecaster.request` (with the HTTP call), and the server's spans `linecaster.serve.queue`,
  `linecaster.serve.decode`, `linecaster.serve.model` (the server extracts `traceparent` from the request
  headers); harvesting: `linecaster.http.fetch` with rate-limit wait and retries.
- Attributes under `linecaster.*`: `block`, `block.family`, `unit`, `page.id`, `item.id`, `preset`, `edition`,
  `engine`, `backend`, `server`, counts (`lines`, `regions`, `words`), `tokens.prompt`, `tokens.completion`,
  `finish_reason`, `error.type`. Never text or images.
- Log records carry `trace_id` and `span_id` (a loguru patcher).
- `linecaster traces OUT [--by block|preset|task] [--slowest N]`: per block the span-duration distribution
  (p50/p90/p99), for served blocks the split request/queue/model, gaps (time a block waited for input), the
  slowest pages with their attributes, and per task the warm-up.
- Cost: measured and recorded in NOTES.md (seconds per page traced and untraced, storage per 1,000 pages).

## 5. Robustness and provenance

- `warm_up()` on every block (idempotent; models and clients load there, not in `__init__` or on the first page);
  the base `run()` calls it first, timed as its own stat and span.
- In-process failures per page: an exception in a per-unit transform records `{block, preset, error}` on the page
  (`doc.metadata["errors"]`), the page skips later model blocks (as served failures do today) and is written to
  `rejects/`; an error budget (`max_page_errors`, default 1 % of pages after the first 100, and any error in
  warm-up) fails the task. Pages skipped after an error are passed on at once, not held until the input ends.
- Errors: `LinecasterError` > `PipelineConfigError`, `CatalogError`, `PageError(page_id, block)`, `ServerError`;
  library code raises these, never `SystemExit` (only the command line turns them into an exit code).
- `to_dict()` on every block: the constructor parameters it was built with (same-named attributes, Haystack's
  convention), JSON-compatible, backends and nested blocks included; secrets as references. The run record gets
  `pipeline:` (the stages with their blocks as dicts) and `pipeline_sha256` over the functional parameters.
- A run into an OUT whose `run.yaml` has a different `pipeline_sha256` is refused (`--new-pipeline` to
  override knowingly); a resume with a different `--tasks` is refused too (it would change each task's input).
- Recipe editions lock their expanded pipeline: `catalog release` records the recipe's pipeline description
  (`describe()`) and its hash in the lock; `catalog verify` rebuilds it (a describe mode that needs no engine
  installed) and reports drift.
- Secrets: `EnvVar("NAME")` (resolved in the task, never pickled; `to_dict` writes `{"env": "NAME"}`); `Served(
  api_key=EnvVar(...), headers={...})` passed to saturate's client.
- Logging: loguru with `{placeholder}` templates and named values; JSON lines on Jobs.
- `runtime.jobs.dependencies(commit, script=None)` raises instead of silently returning linecaster alone when the
  caller expects engines (`engines=True` without a script); the modular pipeline script gets a public name
  (`linecaster.runtime.jobs.ENGINE_SCRIPT`).
- Page records carry `schema: linecaster.page/<n>`; `PageRecordReader` reads records written before phase 1
  (`ocr` → `ocr_new`, folder `rows/`) by a mapping table keyed by the record's schema (records without one are the
  old version).
