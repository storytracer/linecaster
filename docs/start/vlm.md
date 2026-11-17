# Run a vision-language model

A vision-language model (VLM) reads a whole page in one request and returns its text, often with layout and
tables. This tutorial runs one on a folder of page images.

## What you need

- everything from [Run a recipe](first-run.md)
- an NVIDIA GPU
- the `vllm` command on your `PATH`, or let linecaster build an environment for it with uv

## 1. Pick a preset

```bash
uv run launch.py
```

The list shows the VLM presets, for example `lightonocr-2-1b`.

## 2. Run it

```bash
uv run launch.py lightonocr-2-1b scans/ out/
```

Linecaster starts a vLLM server for the model, sends the pages to it and stops the server when the run ends.
Starting the server takes a few minutes.

## 3. Use a server that is already running

If you already serve the model, name its address and no server is started:

```bash
uv run pipelines/transcribe_vlm.py scans/ out/ --recognition lightonocr-2-1b \
  --recognition-endpoint http://127.0.0.1:8000/v1
```

## 4. Let a layout model find the regions first

Some presets read one layout region at a time. Add a layout preset, and the model reads each region:

```bash
uv run pipelines/transcribe_vlm.py scans/ out/ --layout pp-doclayoutv3 --recognition minicpm-ocr-1.0
```

## What is in the page record

The model's answer is kept verbatim as a **raw output**, next to the regions, lines and text that linecaster
parsed from it. If a page looks wrong, the raw output shows what the model actually wrote.

## Next

- [Score a run against ground truth](score.md).
- The [catalog](../catalog/README.md) has a page for every preset, with the model's settings.
