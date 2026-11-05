# Conventions

Rules that hold across the repository. Each rule is followed by its reason. Terms are the
[glossary](glossary.md)'s.

## Names

| What | Pattern | Examples |
|---|---|---|
| block | `<Object><RoleNoun>`; readers and writers `<Object><Format>Reader` / `Writer` | `LineRecognizer`, `Typographer`, `Composer`, `Binder`, `ManifestReader`, `PageJsonlWriter` |
| composite block | `<Purpose><RoleNoun>` | `ModularTranscriber` |
| block base classes | `<Unit>Block` | `PageBlock`, `ItemBlock`, `ModelBlock` |
| engine class | `<Provider><Step>Engine` | `KrakenRecognitionEngine`, `UnicodeRecompositionEngine` |
| engine id | `<provider>.<step>.v<n>` | `kraken.recognition.v1`, `recomposition.unicode.v1` |
| VLM adapter | `<Model>Adapter` | `ChandraOCRAdapter` |
| pipeline script | a verb, `<verb>[_<kind>].py` | `harvest.py`, `transcribe_modular.py`, `transcribe_vlm.py`, `bind.py` |
| pipeline id | the script's file name, `.v<n>` | `transcribe_modular.v1` |
| slot and its flag | the step's name | `--layout`, `--lines`, `--recognition` |
| catalog step | a noun for the activity | `layout`, `recognition`, `recomposition` |
| transcription names | `ocr_new`, `ocr_original`, `ground_truth`, or `<source>` | |

Reason: one pattern makes names guessable, and role nouns say what a block is in a pipeline. Pipeline scripts are
verbs because they are what one runs.

## Spelling

American English everywhere: code, flags, docs, commit messages (normalize, recognizer, behavior, license, color,
catalog). Upstream text copied verbatim (model cards) keeps its spelling.

Reason: one spelling for everything typed, matching Python and its ecosystem.

## YAML and Markdown

- Data that tools read is YAML; prose for people is Markdown. A catalog entry is `<id>.yaml`, optionally with
  `<id>.md` next to it; tools never read the Markdown. Reason: Markdown renders cleanly, data validates, and diffs
  of the two do not mix.
- Every YAML file names its format twice: a first line `# yaml-language-server: $schema=<relative path to
  src/linecaster/catalog/schemas/<kind>-<n>.json>` (editors validate and complete) and a field
  `schema: linecaster.<kind>/<n>` (tools check it). Reason: mistakes show while editing, not at run time.
- The schemas are generated from the pydantic models (`model_json_schema()`) into `src/linecaster/catalog/schemas/`
  (shipped with the package; `linecaster catalog schemas` rewrites them), and a test fails when a committed schema
  differs from a fresh one. The pydantic models are the only source of truth. Reason: one definition, used by
  tools and editors alike.
- YAML is YAML 1.2, read with `ruamel.yaml`: `true`/`false` are the only booleans (`NO` stays a string), duplicate
  keys are errors, and tools that write files back keep their comments.
- An edition's hash covers its functional content (what changes behavior: step, engine, options, pins, settings,
  labels, serving), read from the YAML. The Markdown prose and descriptive fields (support, provenance) are not
  part of it, so they can be corrected without a new edition; git keeps their history.

Schemas: `preset`, `recipe`, `model`, `evidence`, `run-record`, `lock`. Stored page records name their format in a
`schema` field of their row (`linecaster.page/2`).

## Contracts

- Every block declares its unit and what it reads, adds and replaces ([pipelines](pipelines.md)). A part of the
  record is added by one block only, unless a later block declares that it replaces it. Reason: the builder can then
  check a pipeline before it runs and derive its graph.
- Blocks are pure transforms of their unit; only readers and writers know about tasks, ranks and files. Reason:
  the same blocks run on any executor and in `run_pages()`.

## Tracing

- Tracing (OpenTelemetry) is always on. Spans per task always; spans per page for a sample chosen by page id, plus
  every page that failed. Reason: where a run loses time is only visible per page and across processes.
- A page carries its trace context from the reader on; blocks open spans as children of the page's context, never
  of "the current span". Reason: pages are interleaved in the stream.
- Attributes are identifiers and numbers under `linecaster.*`, never content (text, images). Reason: content
  belongs in the rows, which the page id links to.
- Traces are written to `OUT/traces/` and, when the standard `OTEL_*` variables are set, exported to a backend
  ([tracing](tracing.md)).

## Telemetry

linecaster sends nothing to anyone that the user did not configure. No usage data, no phoning home, not even
opt-in. Reason: libraries and archives run it on their own infrastructure under their own rules.

## Logging

loguru (datatrove's), with `{placeholder}` templates and named values, never formatted strings:
`logger.warning("page {page_id} failed in {block}: {error}", page_id=..., block=..., error=...)` (the values land in
the record's `extra`). JSON lines on Jobs: the pipeline scripts set `LINECASTER_LOG_JSON=1` in their Jobs, where the
tasks (`linecaster.runtime.jobs.JobsExecutor`) and `linecaster serve` log with loguru's `serialize=True`
(`linecaster.runtime.logs`). Log records carry `trace_id` and `span_id`. Reason: logs can be filtered and joined to
traces.

## Errors

Library code raises the classes of `linecaster.errors` (`PipelineConfigError`, `CatalogError`, `PageError`,
`ServerError`, all `LinecasterError`), never `SystemExit`; only the command line (`linecaster`, a pipeline script's
`main`) turns them into exit codes, and a test fails on any other exit. Pure functions of the data model, the formats
and the text transforms keep Python's own `ValueError` for a wrong argument. Reason: a derivative that embeds
linecaster can catch what went wrong, and a run's exit code says whether anything was launched.

## Secrets

A credential is never a value in a pipeline: it is an `EnvVar("NAME")` (`linecaster.runtime.secrets`), read in the
task. Reason: datatrove pickles the pipeline for every executor, and the run record lists every block's parameters.

## Changes

`CHANGELOG.md` in the Keep a Changelog format, with upgrade notes first. `NOTES.md` is the log of measurements and
decisions; reference documents (`docs/reference/`) describe what is, without history.
