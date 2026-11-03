# vlm.v1

*Pipeline · [`vlm.py`](../../../pipelines/vlm.py)*

A vision-language model reads the page: the whole page (`ChatPageStep`) or, with a --layout preset, each
region it finds (`ChatRegionStep`, a region preset). Each task starts vLLM or SGLang for the model itself
(`ServeChatModel`, last in the pipeline) unless --vlm-endpoint names a running server; with --layout it also
serves the layout model (`--backend`, `--endpoint` as for any engine model). Page rows in OUT/rows; the
model's raw answer is in each page's transcription.

    uv run pipelines/vlm.py IMAGES OUT --vlm dots-ocr                             # needs `vllm` on PATH
    uv run pipelines/vlm.py IMAGES OUT --vlm dots-ocr --vlm-endpoint http://127.0.0.1:8000/v1
    uv run pipelines/vlm.py IMAGES OUT --layout pp-doclayoutv3 --vlm minicpm-ocr-1.0
    uv run pipelines/vlm.py IMAGES OUT --on hf-jobs --commit <sha> --vlm unlimited-ocr-2

--vlm takes a chat preset of the catalogue (`linecaster models`; `id` or `id@edition`) or a Hugging Face
id (that model's page preset, with --layout its region preset where it has one). On HF Jobs the server runs
in the Job's image: the one the preset was validated with (its `serve.image`) unless --image is given. It
has `uv`, Python 3.12 and `vllm` on PATH, so the pipeline runs in the uv environment the executor builds
(linecaster alone for page models; with --layout also linecaster-paddlex for the layout model), and
`ServeChatModel` starts the image's own server. SGLang presets and region reading start it outside that
environment (`outside_venv`), so neither the image's Python nor its CUDA libraries see the pipeline's
packages. vLLM takes --gpu-memory-utilization of the GPU (0.8, the board's value; SGLang: the preset's own
share); with --layout the layout server loads into the rest after vLLM's memory profiling.

## Slots

Each slot takes a preset of that step; a recipe fills them all.

| Slot | Option |
|---|---|
| vlm | `--vlm` |
| layout | `--layout` |

## Options

Besides the options every pipeline shares (`linecaster.run`).

| Option | Values | Default | Description |
|---|---|---|---|
| `--vlm` |  |  | a chat preset (id[@edition]) or a model's Hugging Face id (needed) |
| `--layout` |  |  | a layout preset: the model then reads each region (a region preset) |
| `--vlm-endpoint` |  |  | a running OpenAI-compatible server for the model |
| `--gpu-memory-utilization` | float |  |  |
| `--no-speculative` | flag |  | plain decoding where the spec has a draft |
| `--window` | int | `48` | requests in flight at the model's server |
| `--initial-window` | int | `8` |  |
| `--layout-window` | int | `16` | pages in flight at the layout server |
| `--read-timeout` | float | `1800.0` | seconds per request |
