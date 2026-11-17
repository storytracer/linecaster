# Plan for 0.12 to 0.14: one vocabulary, a visible core

This file is the working plan of the `clarity/vocabulary` branch and is removed when 0.14 is released. The
target vocabulary is `docs/reference/glossary.md` on this branch; until the renames below are done, the code
still uses the old words.

## Why

Words with several meanings ("block", "step", "strategy", "role", "shape", "policy"), renames that never
finished ("edition"), no top-level API, and reference docs without a concepts page made linecaster hard to
read. The goal: a reader who knows OCR reads one concepts page, runs one tutorial, and can predict where a
class lives and what it is called.

## Target packages

```
linecaster/
  __init__.py     Pipeline, Component, Page, Transcription, catalog, __version__
  core/           the component base, contracts, serialization, Pipeline (plan, checks, stages), errors
  components/     one subpackage per role, one public class per file
  data/           the data model
  formats/        ALTO, PAGE-XML, hOCR, TEI, HTML, IIIF, manifests
  document/       the document and its writers
  normalization/  normalizations and normalization profiles
  conventions/    conventions: format, matchers, decisions
  engines/        the engine API, the registry, built-in engines by role, chat/ (the VLM engines)
  backends/       InProcess, Served, Chat
  catalog/        schema/ (one module per kind), load, resolve, index, verify
  evaluation/     metrics, matching, benchmarks, evidence records, ground truth, external benchmarks
  templates/      the pipeline templates
  execution/      executors (local, Ray, Jobs), the run record, provenance, console, logs
  serving/        linecaster serve and the server launchers
  net/            http, config, limits, proxies, broker
  cli/            the linecaster command, one module per subcommand; the pipelines' command line
  tracing/  testing/  docs/
```

Imports go one way, checked by `tests/test_import_rule.py`:

`data` ← `formats`, `normalization`, `conventions`, `document` ← `engines` ← `core`, `backends`, `catalog` ←
`components` ← `templates` ← `execution`, `cli`

## Renames

Names marked * are proposals the maintainer confirms before the code moves.

| Today | Target |
|---|---|
| `linecaster.blocks`, `Block`, `PageBlock`, `ModelBlock`, `RuleBlock`, `check_block` | `linecaster.components`, `Component`, `PageComponent`, `ModelComponent`, `RuleComponent`, `check_component` |
| block family, block role, catalog step; `step:` in presets; `Annotator.step` | role; `role:`; `Annotator.role` |
| role ids `typography`, `recomposition`, `composition`, `binding` | `hierarchy`, `paragraphs`, `document`, `items` * |
| `Typographer`, `Recomposer`, `Composer`, `Binder`, `Splitter` | `HierarchyDetector`, `ParagraphBuilder`, `DocumentBuilder`, `ItemAssembler`, `ItemSplitter` * |
| `document.DocumentBuilder` (the library class) | `build_document()` * |
| `ModelServer`, `ChatModelServer`, `ServiceServer` | `EngineServer`, `VLMServer`, `VendorServer` * |
| pipeline shape, `SLOTS`, `PIPELINE`, `linecaster.pipelines` | pipeline template, its parameter model, its id, `linecaster.templates` |
| transcription strategy, lane; `strategies/` | normalization profile; `profiles/` |
| by-script strategy | per-script engine |
| HTTP policy, `--http-policy` | HTTP config, `--http-config` |
| block (HTTP), `block_on`, `block_ttl` | refusal, `refuse_on`, `refusal_ttl` * |
| conventions decision `block` | `text_block` * |
| recomposition `Decision` in prose | paragraph decision |
| slice | the stratum dimension `content` |
| trace sample, `--trace-sample` | traced pages, `--trace-share` * |
| `SourceDocument` | `SourceFile` * |
| adapter, chat preset, page preset, page engine | engine (unit `page` or `region`, chat backend) |
| derivative | downstream project |
| `linecaster models` | `linecaster presets` |
| `linecaster truth`, `--truth` | `linecaster ground-truth`, `--ground-truth` |
| `linecaster.markup`, `linecaster.scoring`, `linecaster.runtime`, `linecaster.pipelines`, `linecaster.adapters`, `linecaster.broker` | `linecaster.conventions`, `linecaster.evaluation`, `linecaster.execution`, `linecaster.templates`, `linecaster.engines.chat`, `linecaster.net.broker` |

## Phases

1. **Hygiene, on `main`, a patch.** Stale terms ("edition", "Retyper", `StepInfo`), the generated pages that
   fail to build, duplicate constants and resolvers, dead files.
2. **0.12, the words.** The renames and package moves above with a scripted codemod, no change of behavior.
   One class per file in `components/`. The large files split along their seams. A vocabulary test. The page
   record format rises once for `Annotator.role`.
3. **0.13, the pipeline API.** `Pipeline`, typed templates with a generated command line, `from_dict`, servers
   named by the pipeline, the top-level exports, no import cycles.
4. **0.14, engines and evaluation.** VLM adapters become engines. Normalization profiles replace strategies
   and lanes in code and catalog. Slices become a stratum dimension.

The docs are rewritten alongside 0.12 and 0.13: Get started, Concepts, How-to, Reference, Operations,
Contributing.

## Checks for every phase

- A golden run recorded before 0.12 (every template over the test sample pages with the fake engines) gives
  the same page records and texts afterwards, after the documented field renames.
- A recipe and a VLM preset over a fixed set of real pages give the same literal texts as 0.11.0, on an
  aarch64 and an x86_64 machine with GPUs.
- Page records and run records written by 0.11 still load.

## What 0.12 did, and what it decided otherwise

Done in 0.12: components and `linecaster.core`; component packages by step; the descriptive names and step ids;
server component names; the package moves; `Contract.kind`; the command and option renames; `SourceFile`;
`text_block`; page/6 and run-record/2; the golden test and the vocabulary test; tutorials, concept pages and the
navigation; the glossary.

Decided otherwise while doing it:

- **"step" stays.** Replacing the catalog's "step" by "role" read badly in prose ("the line role found ..."), and
  with "block" gone "step" has one meaning: a kind of work. Families and block roles fold into it; a contract's
  role is its `kind`.
- **`DocumentComposer`, not `DocumentBuilder`**: `linecaster.document.DocumentBuilder` is the class that builds a
  document, and two builders of one name would be the next collision.
- **HTTP policy and HTTP block keep their names.** `HTTPConfig` already names a fetcher's settings, and "blocked" is
  the web's own word; both are always written with "HTTP".
- **`linecaster.text` stays** for helpers that are neither normalizations nor a step's rules (scripts, offsets, a
  page's literal text).

Moved to 0.13: splitting the large files (`execution/run.py`, `catalog/registry.py`, `catalog/schema.py`, `cli.py`,
`tracing/__init__.py`), which the pipeline API rewrites anyway; the layer test over every package; dividing the
long reference pages into how-to and reference; `NOTES.md` as decision records.

## What 0.13 did

`Pipeline` (`linecaster.pipeline`): check, draw, run on this machine, `run_pages`, `to_dict` and `from_dict`, servers
named apart from components. `Component.from_dict` and `backend_from_dict`. `linecaster` exports `Pipeline`,
`Component`, `Page` and `Transcription`. The layers and their test. `execution/run.py` in four modules. The evidence
formats with the evaluation, the format registry in `linecaster.schemas`.

Decided otherwise: the rules of the hierarchy and paragraphs steps are in `linecaster.text` again
(`text.hierarchy`, `text.paragraphs`): the document builder and the plots use them, below the engines.

Still open, for a later minor:

- **Typed templates and a generated command line.** The templates still take an argparse `Namespace`, and
  `execution/options.py` holds about a hundred shared options. Turning each template into a function with a typed
  parameter model touches every pipeline script, the recipes and the Jobs path, which cannot be tested without a
  cluster and Jobs runs: it needs a session of its own, with smoke runs on each executor.
- `linecaster run OUT/run.yaml` (a pipeline rebuilt from a run record: `Pipeline.from_dict` is its base).
- `catalog/registry.py`, `cli.py` and `tracing/__init__.py` in smaller modules.
- The long reference pages (`pipelines.md`, `data-model.md`, `evaluation.md`) divided into how-to and reference;
  `NOTES.md` as dated decision records.
