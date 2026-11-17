# Run a recipe

This tutorial transcribes a folder of page images with a recipe: a tested combination of models.

## What you need

- Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer
- a folder of page images, here `scans/`

An NVIDIA GPU is recommended: the models run much faster on one.

## 1. Get linecaster

```bash
git clone https://github.com/storytracer/linecaster
cd linecaster
```

There is nothing to install: every pipeline is a uv script that brings its own environment on its first run.

## 2. See what you can run

```bash
uv run launch.py
```

This lists the recipes and the presets of the catalog.

## 3. Run the recipe

```bash
uv run launch.py squiddle scans/ out/
```

The first run installs the engines and downloads the models. `squiddle` is a modular recipe: a layout model, a
line detector and a line recognizer, followed by rule-based steps that find headings and paragraphs.

## 4. Look at the result

| In `out/` | What it is |
|---|---|
| `pages/` | one page record per page: everything that was found, with who found it |
| `rejects/` | pages that failed, each with the reason |
| `run.yaml` | the run record: what ran, with which presets and versions |

To get files you can open, name the formats:

```bash
uv run launch.py squiddle scans/ out/ --files out/files --formats md,alto
```

## 5. Change one step

Options after the recipe's name replace single steps. This keeps the recipe but changes one option of its
recognizer:

```bash
uv run launch.py squiddle scans/ out2/ --set recognition.batch_size=4
```

The run record lists what you changed.

## Next

- [Run a vision-language model](vlm.md) instead of the modular pipeline.
- Read the [overview](../concepts/overview.md) to see how the parts fit together.
