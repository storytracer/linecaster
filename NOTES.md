# NOTES

Measurements, decisions and open questions, newest first.

## NFC step and item-level documents (2026-11-03, spark)

**NFC (`NormalizeUnicode`, after recognition).** The chain with the step against squiddleocr's goldens
(7c8a052, spark), goldens NFC-normalised (the parity scripts' new default; `--no-nfc` for raw):

| set | lines (box + words) | txt | md | raw, without NFC on the goldens |
|---|---:|---:|---:|---:|
| sample-60 | 1,560/1,560 | 60/60 | 60/60 | words 978/1,560, txt/md 27/60 |
| tables-7 | 651/651 | 7/7 | 7/7 | words 556/651, txt/md 1/7 |

Table padding in txt is unchanged by NFC: tabulate measures with `wcwidth` (a core dependency since the
post-recognition merge), which gives `a` + U+0308 and `ä` the same display width, so NFC(golden) and
linecaster's NFC output pad identically. (Without `wcwidth`, `len()` would count the combining mark and
the decomposed golden would pad one space less per such character.)

**Item-level documents (`AssembleItemDocument`, `ItemExportsWriter`).** Goldens made with squiddleocr main
itself on the 6 books of sample-60 (10 pages each, in `seq` order): `squiddle_books.py` (squiddleocr's own
`build_pipeline` with the `squiddle ocr` command's defaults, then its `--per-document` branch) for four
combinations; cross-checked against the real command (`squiddle ocr BOOK --per-document --text lines
--sections --dividers -f md,txt,json`) for all 6 books: 18/18 files byte-identical.

| combination | from the same page rows without NFC (md / txt / JSON) | from the chain with NFC (md / txt) |
|---|---:|---:|
| reflow | 6/6 / 6/6 / 6/6 | 4/6 / 4/6 |
| reflow, dividers, furniture | 6/6 / 6/6 / 6/6 | 4/6 / 4/6 |
| lines, furniture | 6/6 / 6/6 / 6/6 | 6/6 / 6/6 |
| lines, sections, dividers | 6/6 / 6/6 / 6/6 | 6/6 / 6/6 |

- The port is exact: from the same rows, md, txt and docling JSON (structure; furniture layer and version
  normalised) are identical for every book and combination, and squiddleocr's own `DocumentBuilder` fed
  with the NFC'd rows gives linecaster's NFC output exactly (24/24).
- With NFC, reflow differs on 2 books, for a reason, not by accident: squiddleocr's `ends_with_mark`
  requires a letter before the hyphen, and in kraken's decomposed text that character is the combining
  accent (category Mn), so `mâ-`/`choire`, `sé-`/`pare`, `exté¬`/`rieur` kept their division marks.
  After NFC they are removed (11 decisions: 9 in histoirenaturell10cuvi, 2 in trudyrusskagoent; one
  then continues a paragraph that the golden had broken). NFC before reflow is the consistent choice and
  the better text; it stays. The item JSON also differs after NFC in charspans (lengths of NFC strings).
- squiddleocr 7c8a052 crashes on `--text reflow --sections` when a page has a title (confirmed with the
  command on birdsofgreatbrit02butl: "Document hierarchy is inconsistent"): its reflow path re-parents
  the title into a new section without detaching it. linecaster opens the section first and puts the
  title inside, as the lines mode does (a test covers it); this combination has no golden.
- Docling renders a heading inside a section one `#` deeper (`### ` for level 2); squiddleocr's goldens
  show the same.

## Post-recognition blocks: retyper and document assembly (2026-11-03, spark)

`Typography` (squiddleocr's retyper) and `AssembleDocument` (squiddleocr's `DocumentBuilder`, `--text lines`)
after the in-process squiddle chain (layout, lines, assign, recognition, tables), exported with
`PageExportsWriter(suffix=".paddle", furniture=True)`, compared byte for byte with squiddleocr's goldens
(`7c8a052`, spark, `--text lines --furniture`; `tests/parity/compare_exports.py`):

| set | txt | md | docling JSON (furniture layer and version field normalised) |
|---|---:|---:|---:|
| sample-60 | 60/60 | 60/60 | 60/60 |
| tables-7 | 7/7 | 7/7 | 7/7 |

- Without the retyper: md 40/60 and 4/7 (headings demoted 34 times on sample-60, page numbers dropped 3
  times on tables-7). Headline splits and drop capitals do not occur on these pages; a differential check
  against squiddleocr's own `retype_page` + `DocumentBuilder` on 2,000 random synthetic pages (470 splits,
  442 drop capitals, 578 page numbers dropped, 678 demotions) gave identical md, txt and region ids,
  labels, levels and order on all of them.
- `wcwidth` is now a core dependency: tabulate (docling's text export of tables) pads with `wcwidth` when
  installed and `len()` otherwise, and kraken writes `ä` as `a` + U+0308, so 3 table pages' txt depended
  on whether the environment happened to have `wcwidth`. (The combining marks also mean the as-written
  text is not NFC yet; normalising it is a separate, recorded transform, not done here.)
- Reflow (`AssembleDocument(text="reflow")`, squiddleocr's default document mode; `linecaster.reflow` is
  squiddleocr's `reflow.py` verbatim, `uniseg` now a core dependency): no reflow goldens exist, so it was
  checked against squiddleocr's own `DocumentBuilder(text="reflow")` fed with the same retyped regions
  and lines: md, txt and docling JSON identical on all 67 pages (446 + 33 paragraphs, 234 division marks
  removed, 1 kept, 4 continuations across regions), and on the 1,000 reflow pages of the random check.
- Not ported: formula recognition (squiddleocr reads formula regions as LaTeX by default; no formula
  regions on these 67 pages; `AssembleDocument` takes `region.extra["formula"]` when a formula step
  provides it), paragraphs continued across pages (needs a book-level document), sections, Markdown
  dividers.

## Chat VLMs: LightOnOCR-2-1B through ChatPageStep (2026-11-03, spark)

Setup:
- Pipeline: `ImageFolderReader` → `ChatPageStep(LightOnOCR2, Served(..., max_window=48, initial_window=8), prepare_workers=4)` → `PageJsonlWriter`, run with `examples/chat_page.py`.
- Server: vLLM 0.21.0 (torch 2.11 cu130) on the same machine.
  - Flags: the spec's serve flags plus `--gpu-memory-utilization 0.22`, because the GPU was shared with `linecaster serve` and kraken-paddlex jobs.
  - The board pins vLLM 0.26.0. That version was not tested here.

Scoring: the rows were converted to the harness's input shape (id, raw, finish_reason) and scored with the frozen bhl-ocr-eval harness along the FineBooks leaderboard's path (consolidation, output normalisation, scoring).

| run | CERdip | CERread | recall µ | loops |
|---|---:|---:|---:|---:|
| sample-60, ChatPageStep | 0.0614 | 0.0285 | 0.9717 | 5/60 |
| sample-60, bare saturate `pump()` (same request/parse) | 0.0661 | 0.0292 | 0.9669 | 4/60 |
| sample-60, board's own outputs (vLLM 0.26.0, A10G), same pages | 0.0656 | 0.0321 | 0.9666 | 4/60 |
| tables-7, ChatPageStep | 0.9453 | 0.5539 | 0.9884 | 0/7 |
| tables-7, bare `pump()` | 0.9532 | 0.5662 | 0.9904 | 0/7 |
| tables-7, board outputs | 0.9701 | 0.5792 | 0.9877 | 0/7 |

- Prompt tokens are identical to the board's on every page, so the image geometry is identical.
- 29 of the 60 completions are byte-identical to the `pump()` run, and 24 to the board's. Sampling is at temperature 0.2.
- Run-to-run variance of `pump()` on sample-60 was CERread 0.026–0.030 on the common pages. The ChatPageStep result falls inside that range.
- All the looped pages (`finish_reason=length`, 4,096 tokens) are in pisciumquerelaee00sche, on every stack.

Throughput, on the same 310 pages (every 7th of the 2,165 IMPACT-BHL images), run back to back against the same server while kraken-paddlex jobs shared the GPU:

| client | wall | pages/s |
|---|---:|---:|
| ChatPageStep pipeline | 1066 s | 0.29 |
| bare `pump()`, `Auto(8,48)`, 4 prep threads | 1251 s | 0.25 |
| (earlier, less contended: bare `pump()`, same settings) | 630 s | 0.49 |

The pipeline adds no measurable overhead. Contention from other GPU jobs dominates these numbers.
Client RSS was about 1.0 GB for the pipeline and 0.7 GB for `pump()`.

**vLLM on spark (unified memory).**
- `--gpu-memory-utilization` is taken against the free memory at start. The same 0.22 gave a 12.3 GiB KV cache in one start and 22.7 GiB in another; EngineCore used 16 GB and 27 GB respectively.
- One start failed with vLLM's profiling assertion ("Initial free memory ... current free memory ..."): another process released memory while vLLM was profiling. Restarting fixed it.

**ServeChatModel** was checked on spark with `examples/chat_page.py --serve --port 8133 --gpu-memory-utilization 0.15 --limit 6`.
vLLM booted in-task in 143 s, 6 pages ran, and the server was stopped at the end.

## HF Jobs image for ChatPageStep (not yet run on Jobs)

`vllm/vllm-openai:v0.26.0` (amd64) qualifies for `JobsPipelineExecutor`. From the image config:
- Python 3.12 (`PYTHON_VERSION=3.12`).
- uv, from `python3 -m pip install uv`, with `UV_PYTHON_INSTALL_DIR` and `UV_CACHE_DIR` set.
- The entrypoint is `vllm serve`, so `vllm` is on PATH.

How the Job is arranged:
- The executor builds the pipeline's uv environment, `--with linecaster @ git+...@<sha>` on Python 3.12.
- `ServeChatModel` starts the image's own `vllm` as a subprocess.
- vLLM never enters linecaster's environment.
- The image sets `UV_INDEX_STRATEGY=unsafe-best-match`, which also applies to that resolve.

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

## Per-page files and item texts in one run (2026-11-03, spark)

`examples/squiddle_chain.py BOOKS OUT --item-from-parent --files OUT/files --texts OUT/texts`
in-process on sample-60 (images grouped by book in subfolders, 6 books): 1 m 45 s; page rows, 360
per-page files (`<item>/<page>.hocr|.alto.xml|.page.xml|.txt|.md|.json`) and 18 item texts.

- All 60 ALTO and 60 PAGE files validate against the schemas in `tests/schemas/`; the 60 hOCR files
  read back with `from_hocr` (1,560 lines, as recognised).
- readable variants: ſ folded (`proſtrati` → `prostrati` on pisciumquerelaee), the as-written ſ kept
  in verbatim_txt; line-end hyphens resolved (`Verbin-/dung`, `Meso-/pleurit`, `Differen-/zierung`
  → joined, on daschitinskelett); page headers and numbers (`— 38 —`) gone from readable, kept in
  verbatim; pages separated by form feeds in verbatim only.
- tables-7 (2 books): table regions appear as HTML tables in readable_md (cells span) and as
  tab-separated rows in readable_txt.
- The test pages are not consecutive within a book, so the joins across page breaks seen here are
  between unrelated pages; on a whole book they are the intended paragraph continuations.
- Item page order: `ItemTexts` sorts by `sequence`; `ImageFolderReader` sets none, so pages fall back
  to their ids (BHL PageIDs ascend with the sequence on these books).
