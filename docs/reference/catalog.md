# The catalog: models, presets, recipes, evidence

The catalog describes every model Linecaster can run, how it runs it, the tested combinations, and the
measurements behind them. Its entries live in one folder, `src/linecaster/catalog/data/`, shipped with
linecaster; `linecaster.catalog` reads, validates and resolves them.

```
src/linecaster/catalog/data/
  models/<id>/model.yaml, model.md        # + upstream/<revision>/ (the upstream card, verbatim)
  presets/<step>/<id>.yaml, <id>.md       # layout, lines, recognition, tables, formulas
  recipes/<id>.yaml, <id>.md
  evidence/<date>-<subject>-<dataset>.yaml
  catalog.lock
src/linecaster/catalog/schemas/<kind>-<n>.json    # generated from the Pydantic models
```

## What the catalog holds

The catalog and its docs are organized by five kinds: engines and pipelines (code, by versioned id) and
three kinds of catalog entry (models, presets, recipes; a YAML file each).

| Kind | Is | Named | Lives in |
|---|---|---|---|
| engine | code that runs a model for one step | versioned id: `kraken.recognition.v1` | `engines/<engine>/` (a package each); `chat.v1` in linecaster |
| model | one upstream artifact at pinned revisions, with its card | slug: `kraken-ppocrv6-medium` | `models/<id>/model.yaml` |
| preset | an engine, a model pin and the engine's options, ready to use | slug, with an edition: `kraken-ppocrv6-medium@1` | `presets/<step>/<id>.yaml` |
| pipeline | code: a shape with slots and the run-anywhere command line | versioned id: `transcribe_modular.v1` (the script's name) | `pipelines/<name>.py` |
| recipe | a named combination: a pipeline, a preset edition per slot, options | slug, with an edition: `squiddle@1` | `recipes/<id>.yaml` |

Besides these: **evidence** records (catalog entries too: one measurement of a preset or recipe edition), the **lock**
(released editions) and the **run record** (`OUT/run.yaml`, and per page in each `ModelInfo`: what a run
resolved).

## Ids and versions

| Term | Whose | Meaning | Example |
|---|---|---|---|
| `version` | upstream | what upstream calls it, verbatim, never parsed | `PP-OCRv6 medium`, `Chandra 2` |
| `revision` | upstream | the exact identity of the files | HF commit, version DOI, git commit, sha256 |
| `edition` | linecaster | integer per preset or recipe, raised when outputs can change | `edition: 3` |
| `.v<n>` | linecaster | the contract of an engine's options or a pipeline's slots and options | `transcribe_modular.v1` |
| `schema` | linecaster | the format of a YAML file | `linecaster.preset/1` |
| release | linecaster | the package version (run records only) | `0.4.0` |

- Slugs (models, presets, recipes): lowercase `[a-z0-9.-]`. They may contain upstream names
  (`deepseek-ocr-2`), never our versions. Ids are unique across presets and recipes, so a name means one
  thing.
- Code ids (`CODE_ID`): lowercase dotted names ending in `.v<n>`. An incompatible change is a new id
  (`.v2`); the old one stays registered. Adding an option is compatible when its default keeps the old
  behavior; changing a default, removing or renaming an option is not.
- A reference is `id@edition`; `id` alone means the current edition. Run records always store the explicit
  edition and its hash.
- A tag or branch is resolved to a commit when a model is pinned; the tag is kept as `tag:` for information.
  Zenodo: the version DOI identifies the files, the concept DOI is information. Downloads without a commit:
  the file's sha256 is the revision.

## Files

A model, preset or recipe is a YAML file, the data, validated strictly by `linecaster.catalog.schema` (unknown
keys are errors), and a Markdown file of the same name next to it, the prose for people (why these settings,
limitations, changes), without front matter. Tools read only the YAML; the docs generator also includes the
prose. The prose is optional, except for presets and recipes with `support: core`. Evidence and the lock are
YAML only. Bulk data (page records, exports) is JSON Lines or Parquet, not catalog data.

| Format | Schema id | JSON Schema |
|---|---|---|
| model | `linecaster.model/1` | `schemas/model-1.json` |
| preset | `linecaster.preset/1` | `schemas/preset-1.json` |
| recipe | `linecaster.recipe/1` | `schemas/recipe-1.json` |
| evidence | `linecaster.evidence/1` | `schemas/evidence-1.json` |
| lock | `linecaster.lock/2` | `schemas/lock-2.json` |
| run record (`OUT/run.yaml`, not catalog data; its schema ships here) | `linecaster.run-record/1` | `schemas/run-record-1.json` |

Every YAML file names its format twice: its first line is `# yaml-language-server: $schema=<relative path to
src/linecaster/catalog/schemas/<kind>-<n>.json>` (for editors), and its field `schema` holds the schema id (for
tools). The JSON Schemas are generated from the Pydantic models (`linecaster catalog schemas`); the test suite
fails when a committed one differs from a fresh one.

YAML has 1.2 semantics, read with `ruamel.yaml` through `linecaster.catalog.yamlio`: only `true` / `false` are
booleans (`NO` stays Norwegian), and a duplicate key is an error. Values that look like numbers or versions are
quoted (`"1.0"`). Commands that write a file back (`release`, `pin`) keep its comments.

### Model (`models/<id>/model.yaml`)

| Field | Meaning |
|---|---|
| `id`, `version` | our slug; upstream's name, verbatim |
| `source` | `kind` (`hf`, `zenodo`, `git`, `url`) and `ref` (repo id, concept DOI, repository URL, download URL) |
| `pins` | one entry per upstream revision: `revision`, `tag`, `doi`, `pinned` (date), `files` (name → `sha256:<hex>`), `card`, `card_sha256`, `license_file` |
| `license` | SPDX id where there is one, else the license's own name |
| `languages`, `scripts` | ISO 639-3 (`mul` for many), ISO 15924 |
| `params` | parameter count, as upstream states it |
| `derived_from` | `ref` and `relation` (`mirror`, `converted`, `quantized`, `finetuned`) |

The upstream card is always copied, verbatim, at the pinned revision, whatever its license: Hugging Face
`README.md`, the HTRMoPo record, a repository README; a separate license file next to it. Its sha256 is in the
pin. Cards are never edited; license, languages and scripts in `model.yaml` are taken from them where they say.
A new upstream revision is a new entry in `pins`, with its own `upstream/<revision>/` folder. Model entries
are written by `linecaster catalog pin`.

### Preset (`presets/<step>/<id>.yaml`)

| Field | Meaning |
|---|---|
| `id`, `edition`, `step` | the step must match the folder |
| `model` | `id` and `revision` of a model pin |
| `submodels` | further pins of a multi-model engine, by role |
| `engine` | the engine's id: `engine: kraken.recognition.v1` |
| `options` | the engine's options (its `Options` model) |
| `settings` | prompts, sampling and other request settings (chat presets) |
| `labels` | native layout label → DoclingDocument label; unmapped labels are `text` |
| `serve` | the server it was validated with: `server` (`vllm`, `sglang`, `linecaster`), `version`, `image` (with digest, for HF Jobs), `flags`, `env`, `revision_flag`, `pin_ignore`, `server_packages`, `draft` (speculative decoding) |
| `capabilities` | `unit` (`line`, `region`, `page`) and `produces` (vocabulary `PRODUCES`) |
| `provenance` | `derived_from` (sources of the settings, each at a commit or revision), `authored_by`, `created` |
| `support`, `superseded_by` | see Support |

### Recipe (`recipes/<id>.yaml`)

| Field | Meaning |
|---|---|
| `id`, `edition` | |
| `pipeline` | the pipeline it fills: `pipeline: transcribe_modular.v1` |
| `presets` | slot → preset `id@edition` (always an explicit edition) |
| `options` | the pipeline's options, by name |
| `provenance`, `support`, `superseded_by` | as for presets |

Measurements of a whole run (goldens, the pipeline's CER) are the recipe's evidence. A derivative's recipe
lives in this catalog too (squiddleocr's `squiddle`); the derivative names it by id.

### Evidence (`evidence/<date>-<subject>-<dataset>.yaml`)

One measurement per file: `preset: id@edition` or `recipe: id@edition`, `context` (for a preset measured
inside a pipeline: the rest of it), `source` (`own-run`, `board`, `card-claim`, `vendor-benchmark`),
`dataset` (`repo@revision`, or a description for claims), `metrics`, `date`, `hardware`, `software`
(linecaster commit, server version), `run`, `notes`. Claims are never measurements; the docs show the source of
every number.

## Released editions are immutable

`linecaster catalog release <id>` writes the current edition's resolved functional content and its sha256 into
`catalog.lock` (per entry: `sha256`, `previous_sha256` where a catalog migration changed it, `released`,
`linecaster` commit, `resolved`; a recipe edition also `pipeline` and `pipeline_sha256`, below).

- **A preset's functional content** is what can change outputs: `step`, the model pin and every submodel pin
  (`id`, `revision`, `files`), `engine`, `options`, `settings`, `labels` and `serve`. Only what the YAML file
  states counts, so a new optional schema field changes no hash. The Markdown prose, provenance, support level
  and capabilities are not part of it.
- **A recipe's functional content** is its pipeline, each slot's preset edition with that edition's hash and
  the options it states. A recipe is released only on released preset editions, so one recipe edition pins a
  whole run down to the weights' files.

`linecaster catalog verify` (and `tests/catalog/test_catalog.py`) fails when a released edition's content changed;
such a change is a new edition. Old editions stay resolvable from the lock after the file moves on.
Unreleased editions are drafts.

### A recipe edition's expanded pipeline

A recipe names a pipeline id, presets and options; what runs is the pipeline its script builds from them. The lock
keeps that too: `release` builds the recipe's pipeline (its pipeline script with `--recipe id@edition` on placeholder
folders, in-process, one task) and records `pipeline`, every block with its class and its functional parameters
(engines with their options, presets with their hashes; [pipelines](pipelines.md#the-run-record)), and its
`pipeline_sha256`, the hash a run record of that recipe names. `verify` builds every released recipe edition's
pipeline again and reports drift: a block, a parameter or a default that changed in code changes the hash, and
`verify` names the blocks that differ.

Building it needs no engine: the **describe mode** (`linecaster.runtime.run.describe_script`) loads the pipeline
script as a module of the current process (its PEP 723 environment is not used), and blocks and backends import
no engine before `warm_up()`; a preset whose engine is not installed names the engine's class from the repository's
engine packages (`catalog.code`). So `verify` runs in the core environment, and its hash is the one a run of the
script with its engines records. It needs the pipeline scripts of the checkout.

Drift is resolved like any change of a released edition: a change that can change outputs gives the recipe a new
edition; a change of the code that keeps behavior (a renamed parameter, a new option whose default keeps the old
behavior) is recorded anew with `linecaster catalog release <id> --migrate-pipeline`. A recipe edition released
before pipelines were locked gets its pipeline on its next `release` (a catalog migration: the edition and its
`sha256` stay). The lock format stays `linecaster.lock/2`: the two fields are optional, and only recipe entries have
them.

### Catalog migrations

A change of the catalog's own vocabulary or format that keeps every output as it was (a renamed step, a renamed
pipeline id, a new file format) is a **catalog migration**: every released edition keeps its number, its
`resolved` content is rewritten in the new terms and its hash recomputed, and the hash it had before stays in
the lock as `previous_sha256`. A run record names `id@edition` and that edition's hash at the time; it resolves
by either hash (`Catalog.resolve(ref, sha256=...)`, `resolve_recipe`, `by_sha256`, `linecaster catalog show
sha256:<hex>`). A change that can change outputs is never a migration: it is a new edition.

## Steps, capabilities, labels

Steps (`STEPS`): `layout`, `lines`, `recognition`, `tables`, `formulas`. Recognition reads a `unit`
(`capabilities.unit`): `line` (kraken, PaddleX, Tesseract), `region` (a VLM per layout region) or `page` (a VLM
reads the whole page: a **page preset**, which `launch.py` runs by name). `OCRD_STEPS` maps the steps to OCR-D's
functional steps for METS agents.

What depends on the code belongs to the engine (`capabilities` on the class), e.g. kraken's word boxes with
confidences. What depends on the weights belongs to the model or preset: languages, scripts, output format.

## Engines

An engine is a class registered under its id in the entry-point group `linecaster.engines`
(`"kraken.recognition.v1" = "linecaster_kraken:KrakenRecognitionEngine"`); linecaster's own is `chat.v1` (VLM
presets, served only). It declares `engine_id`, `step`, `Options` (a Pydantic model whose fields have
descriptions; the docs come from it) and `capabilities`, and takes the pin as `weights` (and
`submodel_weights`), fetched and checked by `linecaster.catalog.fetch`. Engine packages carry code only; their
presets and models are in this catalog.

## Pipelines, recipes and `launch.py`

Every pipeline script declares `PIPELINE`, its id: its file name with `.v<n>` (`harvest.v1`,
`transcribe_modular.v1`, `transcribe_vlm.v1`, `bind.v1`). A script with slots also declares `SLOTS` (slot →
option; the option is the step's name: `--layout`, `--lines`, `--recognition`, ...). It has no default presets:
the user fills every slot, or names a recipe (`--recipe id[@edition]`), with single flags on top recorded as
overrides in the run record (`recipe`: the edition, the pipeline id, the hash and the overrides).

`uv run launch.py NAME IMAGES OUT [options]` launches a recipe or a page preset by name: it finds the
script whose `PIPELINE` the recipe names (`transcribe_vlm.v1` for page presets) and runs it in that script's own
environment with `--recipe` or `--recognition`. `serve` and `ray` pass through for recipes. A preset that is one step
of a pipeline gets a hint instead: the pipeline, the flag and the recipes that use it.

## Support

`core` (maintained, validated), `experimental` (works, may change), `legacy` (kept resolvable;
`superseded_by:` names the replacement).

## Commands

| Command | Does |
|---|---|
| `linecaster models [--step STEP]` | lists the presets (and the recipes) |
| `linecaster catalog pin ID --hf REPO [--revision REV]` | pins a Hugging Face model: model entry, card, file hashes |
| `linecaster catalog pin ID --github OWNER/NAME --revision COMMIT --file F [--tag T]` | pins files of a GitHub repository |
| `linecaster catalog release ID [--commit SHA] [--migrate-pipeline]` | freezes the current edition of a preset or recipe in the lock, a recipe with its expanded pipeline |
| `linecaster catalog verify` | checks the files (schema lines, prose next to its YAML file), the JSON Schemas against the models, cards, pins, released editions and their hashes, recipes and their expanded pipelines, and evidence |
| `linecaster catalog show REF` | the resolved functional content of a preset or recipe edition (`id@edition`, or a hash, today's or a previous one), with its hash |
| `linecaster catalog schemas [--out DIR]` | regenerates the JSON Schemas (default `src/linecaster/catalog/schemas/`) |
| `linecaster catalog docs [--out docs/catalog] [--readme README.md]` | the generated docs and the README's tables |

The generated docs are grouped by kind: `docs/catalog/{engines, models, presets/<step>, pipelines,
recipes}/` and an index. Engine and pipeline pages are read from the source (`linecaster.catalog.code`, with
`ast`), so the engines need not be installed.
