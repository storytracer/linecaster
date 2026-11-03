# NOTES

Measurements, decisions and open questions, newest first.

## First build (2026-11-03)

### What exists

- Data model (`linecaster.transcription`, `linecaster.page`): `Transcription` (regions, lines,
  words, docling, model, source), `Page`, `PageImage`, `Item`, `Text`. Decisions in
  `specs/data-model.md`.
- ALTO 4.4 / PAGE 2019 / hOCR 1.2 writers and readers on lxml, schema-validated
  (`specs/serialisation.md`); image conversion functions (`linecaster.images`: lossless WebP at full
  resolution, combined size limit).
- Blocks on datatrove: readers (image folder, HF image dataset, page rows), model steps (layout,
  lines, recognition) with an in-process or a served backend, line assignment, page writers,
  `ServeModels`.
- `linecaster serve`: a stateless model server (aiohttp) hosting several engine models; blocks reach it
  through saturate.
- Engines: `backends/paddlex` (PP-DocLayoutV3 layout, PP-OCRv6 detection), `backends/kraken` (kraken's
  PP-OCRv6 recogniser), moved from squiddleocr with their history; `envs/kraken-paddlex` is the
  environment that installs both.
- Recipes: `recipes/hf-jobs/squiddle_chain.py` (datatrove `JobsPipelineExecutor`, one
  `linecaster serve` per Job), `recipes/hf-jobs/cuda_probe.py`.

### Parity with squiddleocr

The squiddle combination composed from blocks (layout → lines → assign lines → recognition)
reproduces squiddleocr's outputs (main `7c8a052`, default paddle pipeline, batch 8, bf16-mixed on
CUDA) line for line on the 60-page sample of the BHL IMPACT ground truth: 1,560/1,560 lines identical
in line box, text and every word box.

| machine | in-process | served (datatrove + saturate + `linecaster serve`) |
|---|---|---|
| spark (GB10, aarch64) | 60/60 pages exact | 60/60 pages exact |
| forge (RTX 4000 SFF Ada, x86_64) | 60/60 pages exact | 60/60 pages exact |

Goldens are per machine: squiddleocr itself gives 50/67 byte-identical text files between spark and
forge (36 differing word tokens in 17 files), the usual GPU numerics. squiddleocr is run-to-run
deterministic on one machine (rerun: 60/60 identical). On the 7 table pages the recognised lines are
identical too; one extra line in linecaster's output is one that squiddleocr's typography step
(retyper, after recognition, not yet ported) removes.

On HF Jobs (L4) the served chain gives the same harness scores as on spark to four decimals on the
60-page sample (CERdip 0.0338, CERread 0.0268, recall 0.9526 vs 0.9528); line geometry identical on
1,552/1,560 lines (different GPU numerics).

### Throughput (squiddle combination, per page, model time)

| machine | layout | lines | recognition | wall, 60 pages, served (models overlap) | wall, in-process |
|---|---|---|---|---|---|
| forge RTX 4000 Ada | | | | 42 s (0.70 s/page) | 65 s |
| HF Jobs L4 | 0.21 s | 0.18 s | 0.74 s | | |
| spark GB10 (GPU shared with other work) | 0.16 s | 0.13 s | 0.71 s | 98 s | 194 s |

Served is faster than in-process because the three models work on different pages at the same time
(one worker per model, saturate keeps several pages in flight).

### Full ground truth (2,165 pages, HF Jobs, 4 × L4)

The chain through datatrove + saturate on HF Jobs scores CERdip 0.0551, CERread 0.0451, recall 0.9754
with the frozen bhl-ocr-eval harness (squiddleocr reference on forge: 0.0587 / 0.0432 / 0.9756). Most
pages score identically; the CERread gap sits in index pages that are tables (conchologia):
squiddleocr's PaddleX table step writes them row by row, matching the ground truth's line structure,
while linecaster has no table step yet and writes each cell as its own line. The table step is the
next block to port.

### Lessons

- `[tool.uv.sources]` applies only to a project's own dependencies: the kraken fork came in
  transitively and uv resolved upstream kraken 7.1.1 (inert `--precision`), so the first run was fp32.
  The engine environment lists kraken directly and pins the numerically relevant versions with
  `constraint-dependencies`.
- PaddleX pins `opencv-contrib-python` (GUI build, needs libGL, missing in the HF Jobs image):
  `stubs/opencv-contrib-python` satisfies the pin with the headless build of the same version; one
  `cv2` in the environment; parity unchanged.
- `ServeModels` must be the last block: datatrove chains generators, and only the last one lives until
  every page is written.
- `[tool.uv]`/`uv run --with` in Jobs: git dependencies are spelled out as direct URLs (fork, stub,
  subdirectories).

### Open

- Port squiddleocr's post-recognition steps (retyper, reflow, document assembly into `docling`, tables,
  formulas) as blocks.
- `/v1/chat/completions` preset route for OpenAI clients.
- Deterministic algorithms flag: not set (squiddleocr does not set it and is run-to-run deterministic);
  cuDNN autotuning is off explicitly.
