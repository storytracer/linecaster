# Conventions

Rules that hold across the repository. Each rule is followed by its reason. Terms are the
[glossary](glossary.md)'s.

## Names

| What | Pattern | Examples |
|---|---|---|
| block | `<Object><RoleNoun>`; readers and writers `<Object><Format>Reader` / `Writer` | `LineRecognizer`, `Typographer`, `Composer`, `Binder`, `ManifestReader`, `PageJsonlWriter` |
| composite block | `<Purpose><RoleNoun>` | `ModularTranscriber` |
| block base classes | `<Kind>Block` | `PageBlock`, `ModelBlock`, `RuleBlock` |
| engine class | `<Provider><Step>Engine` | `KrakenRecognitionEngine`, `UnicodeRecompositionEngine` |
| engine id | `<provider>.<step>.v<n>` | `kraken.recognition.v1`, `recomposition.unicode.v1` |
| VLM adapter | `<Model>Adapter` | `ChandraOCRAdapter` |
| pipeline script | a verb, `<verb>[_<kind>].py` | `harvest.py`, `transcribe_modular.py`, `transcribe_vlm.py`, `transcribe_page.py`, `bind.py` |
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

## Docstrings

Google style, checked by `tests/test_docstrings.py` (with `ast`, no extra tool) for every public block, built-in
engine, backend, serializer, `build`, `run_pages`, `runtime.run.main`, public function of `linecaster.catalog` and
public name of `linecaster.engines.api` and `linecaster.testing`:

- **Summary line**: what the block or function does, in the present tense, starting with a verb, one sentence:
  "Recognizes the text of every line with its engine." It may wrap; it ends at the first blank line. The block
  index and the README's block table show it.
- **Body**: the contract in words (what it reads, adds and replaces), edge cases, what it records (step infos,
  stats, errors on the page).
- **`Args:`** names every parameter of the signature (a class documents its constructor's), and no other: one entry
  each, `name: meaning, the effect of the default, constraints.`, continuation lines indented. Several parameters
  may share an entry (`data_folder, paths_file, ...: datatrove's BaseDiskReader arguments.`), as datatrove's
  inherited reader and writer arguments do; `**kwargs` is an entry too. A class that keeps its base's constructor
  keeps its base's `Args:`.
- **`Example:`** (indented Python code) is required for `runtime.run.main`, `build()`, the serializers (`to_alto`,
  `from_alto`, ...) and the public functions of `linecaster.catalog`; optional for blocks, whose generated pages show
  it.
- Inline code in double or single backticks; the generated pages render both as code. Engine options are described
  in their `Options` model (`Field(description=...)`), not in a docstring.

Reason: the generated block pages come from the docstrings, so the reference is only as good as they
are, and a test keeps them complete as signatures change.

## Contracts

- Every block declares its unit and what it reads, adds and replaces ([pipelines](pipelines.md)). A part of the
  record is added by one block only, unless a later block declares that it replaces it. Reason: the builder can then
  check a pipeline before it runs and derive its graph.
- Blocks are pure transforms of their unit; only readers and writers know about tasks, ranks and files. Reason:
  the same blocks run on any executor and in `run_pages()`.

## Tests

- Every built-in engine passes `linecaster.testing.check_engine` and every public block `check_block`
  (`tests/testing/test_conformance.py`); an engine package checks its engines the same way in
  `engines/<engine>/tests/`. Reason: the protocol and the contracts hold for every implementation, not only the
  ones a pipeline happens to run.
- A test that needs a CUDA device is marked `gpu`, one that downloads weights or reaches the internet `network`, one
  over about 10 s `slow`, one that compares against the goldens `parity` (`--strict-markers`). Reason: the default
  run skips what a machine cannot run, and CI runs what a CPU can.
- Tests use the fake engines, the fake chat server and the fake service of `linecaster.testing`, not copies of their
  own. Reason: one fake per step behaves the same in every test.

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
