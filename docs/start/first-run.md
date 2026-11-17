# Your first pipeline

This tutorial transcribes a folder of page images. You choose a model for each step on the command line, then
swap one of them for another.

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

## 2. See what you can combine

The modular pipeline works in **steps**: a layout model finds the regions of a page, a line detector finds the
lines, and a line recognizer reads each line. For every step you pick a **preset**: a model with its settings.

```bash
uv run linecaster presets --step layout
uv run linecaster presets --step lines
uv run linecaster presets --step recognition
```

Each command lists the presets of one step, with their engine, model and license.

## 3. Run it

Name one preset for each step:

```bash
uv run pipelines/transcribe_modular.py scans/ out/ \
  --layout pp-doclayoutv3 \
  --lines pp-ocrv6-medium-det \
  --recognition paddlex-ppocrv6-medium
```

The first run installs the engines and downloads the models. No step has a default, so the command line says
exactly what ran.

## 4. Look at the result

| In `out/` | What it is |
|---|---|
| `pages/` | one page record per page: everything that was found, with who found it |
| `rejects/` | pages that failed, each with the reason |
| `run.yaml` | the run record: what ran, with which presets and versions |

To get files you can open, name a folder and the formats:

```bash
uv run pipelines/transcribe_modular.py scans/ out/ \
  --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det --recognition paddlex-ppocrv6-medium \
  --files out/files --formats txt,alto
```

The run resumes: pages that are already done are not read again.

## 5. Swap one model

Every step is independent of the others. This run keeps the layout and the lines and reads the text with
Tesseract instead:

```bash
uv run pipelines/transcribe_modular.py scans/ out-tesseract/ \
  --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det \
  --recognition tesseract-best-latin \
  --files out-tesseract/files --formats txt,alto
```

Compare the two folders of text files to see what the change did.

## 6. Add steps

More steps are more options. This run also reads tables, finds the headings, joins the lines into paragraphs and
builds a document, which the Markdown is written from:

```bash
uv run pipelines/transcribe_modular.py scans/ out-full/ \
  --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det --recognition paddlex-ppocrv6-medium \
  --tables slanet-plus \
  --hierarchy ratios --paragraphs unicode-paragraphs --document linked-document \
  --files out-full/files --formats md,alto
```

Two more options are useful while you try things out:

| Option | Effect |
|---|---|
| `--dry-run` | prints the plan and its graph, and runs nothing |
| `--set recognition.batch_size=4` | changes one option of a step's preset |

`--help` lists every option.

## 7. Run a recipe

Once a combination works for your material, it can be kept as a **recipe**: a named, tested set of presets, one
for each step. Linecaster's catalog has the recipe `squiddle`, and `launch.py` runs a recipe by its name:

```bash
uv run launch.py squiddle scans/ out-squiddle/
```

A recipe has a script of its own with exactly the engines its presets need. `squiddle` also reads formulas, with a
model that needs torch, which `transcribe_modular.py` does not install.

Options after the recipe's name replace single steps, and the run record lists what you changed.

## Next

- [Build the same pipeline in Python](python.md).
- [Run a vision-language model](vlm.md) instead of the modular pipeline.
- Read the [overview](../concepts/overview.md) to see how the parts fit together.
