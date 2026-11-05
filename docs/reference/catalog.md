# The catalogue: models, presets, recipes, evidence

The catalogue describes every model Linecaster can run, how it runs it, the tested combinations, and the
measurements behind them. Its documents live in one folder, `src/linecaster/catalog/data/`, shipped with
linecaster; `linecaster.catalog` reads, validates and resolves them.

```
src/linecaster/catalog/data/
  models/<id>/model.md                    # + upstream/<revision>/ (the upstream card, verbatim)
  presets/<step>/<id>.md                  # layout, lines, recognition, tables, formulas, page
  recipes/<id>.md
  evidence/<date>-<subject>-<dataset>.yaml
  catalog.lock
```

## Components

"Component" is the umbrella word for the five things the catalogue and the docs are organised by.

| Component | Is | Named | Lives in |
|---|---|---|---|
| engine | code that runs a model for one step | versioned id: `kraken.recognition.v1` | `engines/<engine>/` (a package each); `chat.v1` in linecaster |
| model | one upstream artifact at pinned revisions, with its card | slug: `kraken-ppocrv6-medium` | `models/<id>/model.md` |
| preset | an engine, a model pin and the engine's options, ready to use | slug, with an edition: `kraken-ppocrv6-medium@1` | `presets/<step>/<id>.md` |
| pipeline | code: a shape with slots and the run-anywhere command line | versioned id: `chain.v1` | `pipelines/<name>.py` |
| recipe | a named combination: a pipeline, a preset edition per slot, options | slug, with an edition: `squiddle@1` | `recipes/<id>.md` |

Besides the documents above: **evidence** (one measurement of a preset or recipe edition), the **lock**
(released editions) and the **run record** (`OUT/run.yaml`, and per page in each `ModelInfo`: what a run
resolved).

## Ids and versions

| Term | Whose | Meaning | Example |
|---|---|---|---|
| `version` | upstream | what upstream calls it, verbatim, never parsed | `PP-OCRv6 medium`, `Chandra 2` |
| `revision` | upstream | the exact identity of the files | HF commit, version DOI, git commit, sha256 |
| `edition` | linecaster | integer per preset or recipe, raised when outputs can change | `edition: 3` |
| `.v<n>` | linecaster | the contract of an engine's options or a pipeline's slots and options | `chain.v1` |
| `schema` | linecaster | the format of a document | `linecaster.preset/1` |
| release | linecaster | the package version (run records only) | `0.4.0` |

- Slugs (models, presets, recipes): lowercase `[a-z0-9.-]`. They may contain upstream names
  (`deepseek-ocr-2`), never our versions. Ids are unique across presets and recipes, so a name means one
  thing.
- Code ids (`CODE_ID`): lowercase dotted names ending in `.v<n>`. An incompatible change is a new id
  (`.v2`); the old one stays registered. Adding an option is compatible when its default keeps the old
  behaviour; changing a default, removing or renaming an option is not.
- A reference is `id@edition`; `id` alone means the current edition. Run records always store the explicit
  edition and its hash.
- A tag or branch is resolved to a commit when a model is pinned; the tag is kept as `tag:` for information.
  Zenodo: the version DOI identifies the files, the concept DOI is information. Downloads without a commit:
  the file's sha256 is the revision.

## Documents

Model, preset and recipe documents are Markdown with YAML front matter: the front matter is data, validated
strictly by `linecaster.catalog.schema` (unknown keys are errors); the body is prose for people (why these
settings, limitations, changes). Evidence, the lock and run records are plain YAML. Every document starts with
`schema: linecaster.<type>/<n>`. Bulk data (page rows, exports) is JSON Lines or Parquet, not catalogue data.

YAML has 1.2 semantics: only `true` / `false` are booleans (`NO` stays Norwegian), read and written with
`linecaster.catalog.yamlio`. Values that look like numbers or versions are quoted (`"1.0"`). JSON Schemas for
editors: `linecaster catalog schema`.

### Model (`models/<id>/model.md`)

| Field | Meaning |
|---|---|
| `id`, `version` | our slug; upstream's name, verbatim |
| `source` | `kind` (`hf`, `zenodo`, `git`, `url`) and `ref` (repo id, concept DOI, repository URL, download URL) |
| `pins` | one entry per upstream revision: `revision`, `tag`, `doi`, `pinned` (date), `files` (name → `sha256:<hex>`), `card`, `card_sha256`, `license_file` |
| `license` | SPDX id where there is one, else the licence's own name |
| `languages`, `scripts` | ISO 639-3 (`mul` for many), ISO 15924 |
| `params` | parameter count, as upstream states it |
| `derived_from` | `ref` and `relation` (`mirror`, `converted`, `quantised`, `finetuned`) |

The upstream card is always copied, verbatim, at the pinned revision, whatever its licence: Hugging Face
`README.md`, the HTRMoPo record, a repository README; a separate licence file next to it. Its sha256 is in the
pin. Cards are never edited; licence, languages and scripts in `model.md` are taken from them where they say.
A new upstream revision is a new entry in `pins`, with its own `upstream/<revision>/` folder. Model documents
are written by `linecaster catalog pin`.

### Preset (`presets/<step>/<id>.md`)

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

### Recipe (`recipes/<id>.md`)

| Field | Meaning |
|---|---|
| `id`, `edition` | |
| `pipeline` | the pipeline it fills: `pipeline: chain.v1` |
| `presets` | slot → preset `id@edition` (always an explicit edition) |
| `options` | the pipeline's options, by name |
| `provenance`, `support`, `superseded_by` | as for presets |

Measurements of a whole run (goldens, the pipeline's CER) are the recipe's evidence. A derivative's recipe
lives in this catalogue too (squiddleocr's `squiddle`); the derivative names it by id.

### Evidence (`evidence/<date>-<subject>-<dataset>.yaml`)

One measurement per file: `preset: id@edition` or `recipe: id@edition`, `context` (for a preset measured
inside a pipeline: the rest of it), `source` (`own-run`, `board`, `card-claim`, `vendor-benchmark`),
`dataset` (`repo@revision`, or a description for claims), `metrics`, `date`, `hardware`, `software`
(linecaster commit, server version), `run`, `notes`. Claims are never measurements; the docs show the source of
every number.

## Released editions are immutable

`linecaster catalog release <id>` writes the current edition's resolved functional content and its sha256 into
`catalog.lock` (per entry: `sha256`, `released`, `linecaster` commit, `resolved`).

- **A preset's functional content** is what can change outputs: `step`, the model pin and every submodel pin
  (`id`, `revision`, `files`), `engine`, `options`, `settings`, `labels` and `serve`. Only what the document
  states counts, so a new optional schema field changes no hash. Prose, provenance, support level and
  capabilities are not part of it.
- **A recipe's functional content** is its pipeline, each slot's preset edition with that edition's hash and
  the options it states. A recipe is released only on released preset editions, so one recipe edition pins a
  whole run down to the weights' files.

`linecaster catalog verify` (and `tests/test_catalog.py`) fails when a released edition's content changed;
such a change is a new edition. Old editions stay resolvable from the lock after the file moves on.
Unreleased editions are drafts.

## Steps, capabilities, labels

Steps (`STEPS`): `layout`, `lines`, `recognition`, `tables`, `formulas`, `page` (end to end: a whole page in,
text out). Recognition reads a `unit`: `line` (kraken, PaddleX, Tesseract) or `region` (a VLM per layout
region). `OCRD_STEPS` maps the steps to OCR-D's functional steps for METS agents.

What depends on the code belongs to the engine (`capabilities` on the class), e.g. kraken's word boxes with
confidences. What depends on the weights belongs to the model or preset: languages, scripts, output format.

## Engines

An engine is a class registered under its id in the entry-point group `linecaster.engines`
(`"kraken.recognition.v1" = "linecaster_kraken:KrakenRecognitionModel"`); linecaster's own is `chat.v1` (VLM
presets, served only). It declares `engine_id`, `step`, `Options` (a Pydantic model whose fields have
descriptions; the docs come from it) and `capabilities`, and takes the pin as `weights` (and
`submodel_weights`), fetched and checked by `linecaster.catalog.fetch`. Engine packages carry code only; their
presets and models are in this catalogue.

## Pipelines, recipes and `launch.py`

A pipeline script declares `PIPELINE` (its id) and `SLOTS` (slot → option). It has no default presets: the
user fills every slot, or names a recipe (`--recipe id[@edition]`), with single flags on top recorded as
overrides in the run record.

`uv run launch.py NAME IMAGES OUT [options]` launches a recipe or a whole-page preset by name: it finds the
script whose `PIPELINE` the recipe names (`vlm.v1` for whole-page presets) and runs it in that script's own
environment with `--recipe` or `--vlm`. `serve` and `ray` pass through for recipes. A preset that is one step
of a pipeline gets a hint instead: the pipeline, the flag and the recipes that use it.

## Support

`core` (maintained, validated), `experimental` (works, may change), `legacy` (kept resolvable;
`superseded_by:` names the replacement).

## Commands

| Command | Does |
|---|---|
| `linecaster models [--step STEP]` | lists the presets (and the recipes) |
| `linecaster catalog pin ID --hf REPO [--revision REV]` | pins a Hugging Face model: model document, card, file hashes |
| `linecaster catalog pin ID --github OWNER/NAME --revision COMMIT --file F [--tag T]` | pins files of a GitHub repository |
| `linecaster catalog release ID [--commit SHA]` | freezes the current edition of a preset or recipe in the lock |
| `linecaster catalog verify` | checks cards, pins, released editions, recipes and evidence |
| `linecaster catalog show REF` | the resolved functional content of a preset or recipe edition, with its hash |
| `linecaster catalog schema [--out DIR]` | JSON Schemas of the documents |
| `linecaster catalog docs [--out docs/catalog] [--readme README.md]` | the generated docs and the README's tables |

The generated docs are grouped by component: `docs/catalog/{engines, models, presets/<step>, pipelines,
recipes}/` and an index. Engine and pipeline pages are read from the source (`linecaster.catalog.code`, with
`ast`), so the engines need not be installed.
