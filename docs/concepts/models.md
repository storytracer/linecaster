# Models, engines and presets

A preset names the model that does a step's work, and the catalog lists the presets you can pick.

## The three parts

| Part | What it is | Example |
|---|---|---|
| model | weights from upstream, pinned to a revision and checked by hash | `kraken-ppocrv6-medium` |
| engine | code that loads a model and processes one unit per call | `kraken.recognition.v1` |
| preset | a named configuration: an engine, its options and a model | `kraken-ppocrv6-medium` |

You only ever pick a preset. The preset says which engine runs and which model it loads, so a run names exactly
what it ran.

An engine works on one **unit**: a line, a region or a whole page. A line recognizer reads lines; a
vision-language model reads pages.

## The catalog

The catalog is the list of everything you can pick. It ships with linecaster as YAML files:

- models and presets,
- recipes,
- normalizations and strategies (see [text and normalization](text.md)),
- rendering policies, conventions and vocabularies.

List the presets with `linecaster presets`. The [catalog pages](../catalog/README.md) describe each entry.

## Engine packages

Engines for kraken, PaddleX, Tesseract and others are separate packages (`linecaster-kraken`, ...), because their
dependencies conflict with each other. The core has no torch and no model runtime. A pipeline script installs
exactly the packages its presets need.

## Recipes

A recipe is a tested combination: one preset for each slot of a pipeline template, plus options such as the texts
to write. `uv run launch.py squiddle scans/ out/` runs the recipe `squiddle`.

## Nothing changes unseen

Each catalog entry has a hash of everything that affects its output. The file `catalog.index` lists the hashes,
so a change of behavior shows up in review. A run record names every entry the run used, with its hash and the
linecaster version. Together they reproduce the run.

## Reference

The [catalog reference](../reference/catalog.md) describes the file formats and the commands.
