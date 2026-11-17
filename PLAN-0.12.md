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

## Progress on 0.12

Done: absolute imports; `blocks` → `components` and `core` (modules, base classes, prose, generated pages).

Open:
- formats: run record (`component` keys) and page record (`errors[].component`, `Annotator.role`) versions and upgrades;
  trace attributes `linecaster.component*`
- roles: `step` → `role`, role ids, class renames (print shop, servers), engine ids, preset ids, flags
- `Contract.role` → `kind`
- package moves: `runtime`, `pipelines`, `markup`, `scoring`, `adapters`, `broker`, `text`
- HTTP config and refusals; CLI renames; `SourceFile`; `text_block`
- large files split; vocabulary test; docs; migration guide; engine packages' linecaster range; locks; release
