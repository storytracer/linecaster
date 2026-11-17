# Run a vision-language model

A vision-language model (VLM) reads a whole page in one request and returns its text, often with layout and
tables. This tutorial runs one on a folder of page images.

## What you need

- Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer
- a folder of page images, here `scans/`
- an NVIDIA GPU
- the `vllm` command on your `PATH`, or let linecaster build an environment for it with uv

## 1. Get linecaster

```bash
git clone https://github.com/storytracer/linecaster
cd linecaster
```

There is nothing to install: every pipeline is a uv script that brings its own environment on its first run.

## 2. Pick a preset

```bash
uv run linecaster presets --step recognition
```

A **preset** is a model with its settings. The presets whose engine is `chat.v1` are vision-language models, for
example `lightonocr-2-1b`.

## 3. Run it

The pipeline has one step to fill:

```bash
uv run pipelines/transcribe_vlm.py scans/ out/ --recognition lightonocr-2-1b
```

Linecaster starts a vLLM server for the model, sends the pages to it and stops the server when the run ends.
Starting the server takes a few minutes. `uv run launch.py lightonocr-2-1b scans/ out/` is a shorter way to write
the same run.

## 4. Use a server that is already running

If you already serve the model, name its address and no server is started:

```bash
uv run pipelines/transcribe_vlm.py scans/ out/ --recognition lightonocr-2-1b \
  --recognition-endpoint http://127.0.0.1:8000/v1
```

## 5. Let a layout model find the regions first

Some presets read one layout region at a time. Add a layout preset, and the model reads each region:

```bash
uv run pipelines/transcribe_vlm.py scans/ out/ --layout pp-doclayoutv3 --recognition minicpm-ocr-1.0
```

## What is in the page record

The model's answer is kept verbatim as a **raw output**, next to the regions, lines and text that linecaster
parsed from it. If a page looks wrong, the raw output shows what the model actually wrote.

## Next

- [Combine models step by step](first-run.md): a model for each step instead of one for the page.
- [Score a run against ground truth](score.md).
- The [catalog](../catalog/README.md) has a page for every preset, with the model's settings.
