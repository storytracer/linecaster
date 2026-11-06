# NOTES

Measurements, decisions and open questions, newest first.

## The four board models the catalog lacked: Surya OCR 2.5, Indra OCR, Falcon-OCR, OXR-1.0 (2026-11-06, spark and an x86_64 A6000 machine)

The BHL OCR board's rows 10 (`datalab-to/surya-ocr-2.5`), 22 (`datalab-to/indra-ocr`), 25 (`SoMarkAI/OXR-1.0`) and 26
(`tiiuae/Falcon-OCR`) as presets that run them the way the board's drivers do (`drivers/{surya-ocr25,indra-ocr,oxr,
falcon-ocr}-port.py` of finebooks/bhl-ocr-eval at 76bc19d). None of them is a chat model, so none fits `chat.v1`.

Decisions:

- **Page engines.** An engine whose unit is the page, run by `PageRecognizer` like any model block (`InProcess`, or
  `Served` behind `linecaster serve`), next to the `Chat` backend; its raw output verbatim in `extra["raw"]`, as for
  chat presets, and the board's post-processing left to the harness. One pipeline shape for all four:
  `pipelines/transcribe_page.py` (reader → `PageRecognizer` → writer → the service), a new script rather than
  `transcribe_vlm.py` because its environment differs (surya-ocr brings torch; `transcribe_vlm.py`'s lock stays as
  it was).
- **Engine packages**: `linecaster-indra` (`indra-ocr==1.1.2`), `linecaster-surya` (`surya-ocr==0.23.0`) and
  `linecaster-services` (Falcon-OCR's and OXR's clients, standard library HTTP, no dependency of their own). The
  vendor services' clients are in-process engines, not a new backend: one page per request, one request in flight
  per task (the board's drivers had up to 8 and 16 in flight). More tasks share one running service with
  `--recognition-endpoint`; the engine's `endpoint` is operational (left out of `pipeline_sha256`).
- **`ServiceServer`** starts what a page preset's `serve` block names: `vllm serve` on the fetched pin (Surya) or the
  vendor image's entrypoint (`serve.server: vendor`: `command`, `health`, `weights_dir`, new optional schema
  fields), without the pipeline's environment. The pipeline runs inside the vendor's image (on HF Jobs the preset's
  `serve.image`; here `docker run` of the same image digest, with uv mounted).
- **One environment for both packages**: surya-ocr pins OpenCV 4.11.0.86, indra-ocr takes any, so both get 4.11
  (the board's Indra job resolved the newest of its day). surya-ocr declares `pillow<11`, linecaster `Pillow>=11`:
  the script overrides Pillow with the shared pin (12.3.0; the board's Surya run had 10.4.0) and keeps torch at the
  2.14.0 build every other script has (surya-ocr would resolve 2.15.0; with the vLLM backend surya uses torch only to
  detect the device). No existing script or lock changed.
- **An engine may take the image file's bytes** (`image_input = "bytes"`): the board's Indra driver gave the package
  the dataset's own file. On the sample, Indra from the file reproduced the board's Markdown on 54 of 60 pages;
  from a PNG of the decoded RGB pixels on 26 (CER reading 0.0486 against 0.0489; spark and the x86_64 machine
  agreed on all 60 pages).
- **Falcon OCR is pinned at `177110bf`**, not the repository's head: every file of `/models/Falcon-OCR` in the
  board's image (`ghcr.io/tiiuae/falcon-ocr@sha256:2ec80252...`) has the git blob of that revision (2026-03-09),
  `model.safetensors` its sha256 (`6e7f73a5...`); head (Falcon OCR v1.5, 2026-09-11) has other weights.
- **OXR's form**: `output_formats` goes as one field per format, as httpx (the board's saturate 0.2.0) encodes a
  list. saturate 0.3.0's multipart sends `str(value)` (`"['markdown', 'json']"`), so OXR is not streamed through
  saturate. `OXR_API_HOST` is set to 127.0.0.1 (the entrypoint's vLLM and layout services bind loopback anyway);
  Falcon's entrypoint binds both its services to every address of the container and has no setting for it.
- **Surya's server flags** are the package launcher's for `VLLM_GPU_TYPE=a100-80` (the board's A100 80 GB), checked
  against the installed package (`linecaster_surya.package_flags`, a test); vLLM serves the fetched pin under the
  package's model name, and the package attaches through `SURYA_INFERENCE_URL`.

Runs on the 60-page sample (`finebooks/bhl-ocr-eval-sample-60@41ff3475`), scored the board's way with a fresh clone
of bhl-ocr-eval at 76bc19d (consolidate → `normalize_outputs` postproc 3 → `score_dataset`; the normalizer run from
outside the project, as its run note says), next to the board's own outputs for the same pages
(`hf://buckets/finebooks/bhl-ocr-outputs/rows/<row>/normalized.parquet`). CER reading:

| Model | Where | linecaster | board, same 60 pages | identical to the board | board, 2,165 pages |
|---|---|---|---|---|---|
| Surya OCR 2.5 | RTX A6000, vLLM 0.25.1 image | 0.0262 | 0.0251 | HTML of 52 pages, full-page completion of 30 | 0.0351 |
| Indra OCR | spark CPU, one task | 0.0489 | 0.0489 | 54 pages | 0.0621 |
| OXR-1.0 | RTX A6000, the board's image | 0.0380 | not published | - | 0.1104 |
| Falcon-OCR | RTX A6000, the vendor image | 0.0775 | 0.1301 | 47 pages | 0.1384 |

- Falcon-OCR: the gap is one plate page (8966788) on which the board's run looped (a numbered list from 101. to 791.,
  5,466 characters, page CER 66.5) and this run did not (114 characters). Of the other 59 pages, 12 differ, by up to
  0.07 page CER either way. The service reports no finish reason.
- OXR-1.0: the board's outputs for these pages are not published (its bucket has no OXR row), so there is no
  same-page comparison. Per volume here: Conchologia 0.118 and Piscium 0.116, the other four 0.006 to 0.014; the
  board's full-benchmark number carries text read twice on Conchologia pages and runaway leader dots on three Trudy
  index pages (bhl-ocr-eval RESULTS.md).
- Surya: the blocks' confidences differ in the last digits on every page, so the raw JSON is never identical; no page
  fell back to block mode (the board's run: one).
- Time per page, one page in flight: Indra 0.3 s (one GB10 core), Falcon-OCR 2.3 s, Surya 4.8 s, OXR 2.6 s. The
  services took 68 s (Falcon-OCR), 336 s (vLLM for Surya, with torch.compile) and 185 s (OXR, the weights
  downloaded) to start.

Not verified: any of them on HF Jobs (the Falcon-OCR image has Python 3.10 and no uv, so the pipeline cannot run in
it there as it is); `GPUJobsExecutor` and Ray with these services (a vendor entrypoint's ports are fixed, so
`point_to_gpu` cannot move them); the page engines behind `linecaster serve`; on forge. The engines return text-only
transcriptions; the geometry the vendors return (Surya's and Indra's blocks with boxes, Falcon's regions, OXR's
blocks) is kept in `extra`, not made into regions and lines.

Licenses: Surya OCR 2.5 and Indra OCR weights under modified OpenRAIL-M licenses (the "AI Pubs Open RAIL-M License
(Modified)": free for research and personal use and below USD 5 million (Surya) or 20 million (Indra) of revenue and
of funding, never for a competing product or service; the packages' code is Apache-2.0); OXR-1.0 under the "OXR
License" (Apache-2.0 with additional terms: commercial use without a separate license below USD 2 million of funding
and of revenue, never for a competing hosted API); Falcon OCR Apache-2.0.

## olmOCR-2-7B-1025-FP8 on native FP8 (2026-11-06, RTX 4000 SFF Ada)

The preset `olmocr-2-7b-1025-fp8@1` (board row 5) on the 60-page sample, on an RTX 4000 SFF Ada 20 GB (x86_64,
compute capability 8.9), which runs FP8 natively. The board's run was one HF Jobs `a10g-small` job (A10G, Ampere: no
FP8 tensor cores, so vLLM dequantizes the weights; the driver's docstring calls it the Marlin path).

Setup:
- linecaster at 2b26d5d (a fresh clone): `pipelines/transcribe_vlm.py OUT --parquet <sample>/data --id-key PageID
  --recognition olmocr-2-7b-1025-fp8@1 --window 12 --initial-window 4`. `ChatModelServer` started `vllm serve
  allenai/olmOCR-2-7B-1025-FP8 --revision 40bd720... --max-model-len 16384 --no-enable-prefix-caching
  --mm-processor-cache-gb 0 --limit-mm-per-prompt {"image": 1} --gpu-memory-utilization 0.8`, on loopback: the
  board driver's flags exactly. At most 12 pages in flight, 4 at the start, as the driver's saturate window
  (`Auto(initial=4, target_waiting=4, max_limit=12)`).
- vLLM 0.26.0 (the board's version) from PyPI in its own venv: `uv venv --python 3.12`, then `uv pip install
  --exclude-newer 2026-07-26T00:00:00Z vllm==0.26.0` (the day after the release, to approximate the image's
  resolve): torch 2.11.0+cu130, transformers 5.14.1, flashinfer-python 0.6.14, compressed-tensors 0.17.0. Its
  `bin` goes first on `PATH` (`vllm` and `ninja`). Not the board's image `vllm/vllm-openai:v0.26.0` (no Docker
  here), whose package versions were not compared. The venv of the MiniCPM-OCR run (a vLLM nightly, 0.32.1rc1, with
  a transformers dev build) was not used: it is not the board's version.
- vLLM picked `CutlassFP8ScaledMMLinearKernel` for the FP8 layers (W8A8) and FlashAttention 2.
- Memory: no change needed. Weights 9.56 GiB, KV cache 5.72 GiB (107,040 tokens, 6.5 times one full context),
  17.5 of 20 GB in use.

Scored the board's way with a fresh clone of bhl-ocr-eval at 76bc19d (consolidate → `normalize_outputs` postproc 3 →
`score_dataset`), next to the board's raw completions for the same pages (`rows/olmocr2/normalized.parquet`, column
`raw_verbatim`) put through the same three steps:

| run | CER dip | CER reading | recall | loops |
|---|---:|---:|---:|---:|
| linecaster, RTX 4000 SFF Ada (FP8 W8A8) | 0.0350 | 0.0204 | 0.9431 | 0 of 60 |
| board, A10G, same 60 pages | 0.0345 | 0.0196 | 0.9436 | 0 of 60 |
| board, 2,165 pages (RESULTS.md) | 0.0576 | 0.0279 | 0.9573 | 0.55 % |

- The board's published `markdown` column for this row predates its front-matter fix of 2026-10-30 (made without a
  postproc bump): on 9 of these pages, all blank, it holds the YAML front matter alone, which scores 0.0461 / 0.0304
  / 0.9436. Compare against the raw completions re-normalized, not against that column.
- 34 of the 60 completions are byte-identical to the board's. linecaster's image encoding gives the driver's PNG
  bytes on all 60 pages (same Pillow), and the prompt tokens equal the board's (96,718 in all; 1,372 to 1,786 per
  page). Completion tokens 27,163 against 27,153.
- Page CER reading: worse than the board's on 16 pages, better on 5, equal on the rest. The largest difference is
  one Conchologia plate (8966788), where this run also read the two engraver lines (page CER 0.79 against 0.38);
  without that page 0.0198 against 0.0193. The others are small (at most 0.064 page CER, on a 61-character page), across all six volumes.
- No page reached its token cap (longest completion 1,325 of 8,192 tokens), no errors.
- Time: 291 s for the whole process (the uv environment, vLLM's start of 120 s with 19 s of torch.compile, then the
  pages); the 60 pages took 167 s, 2.8 s per page with up to 12 in flight. The board's job ran 3,527 s for 2,165
  pages on the A10G (1.6 s per page, its start included).
- Scoring: `normalize_outputs` needs `uv run --no-project --no-config <clone>/runners/normalize_outputs.py`; with uv
  0.13.6, `--no-project` alone still applied the clone's `exclude-newer` (2026-07-05), under which `docling-core>=2.89`
  does not resolve.

Not checked: the board's image itself (its own vLLM build, transformers and Pillow); a second run (sampling at
temperature 0.1, so run-to-run variation on these pages is not measured).

## The refactoring of November 2026 (2026-11-06)

Six phases, each merged into main after the suite and the goldens (sample-60, 60/60 pages exact): the decisions on
paper (glossary, conventions); renames, layout and the catalog format; tracing, contracts and the builder; rule-based
steps as catalog engines, recomposition and binding; backends and families (the chat backend, converters,
skeletons); docs; tests and engine hygiene. The plan and the per-phase designs were working documents under
`docs/plan/`, removed at `v0.1.0`; they are in the history at 9c7fe4e. Every rename is in `CHANGELOG.md` (0.1.0).

## Ray Data instead of an executor: a spike (2026-11-06, spark)

Could a pipeline's per-page blocks run as Ray Data `map_batches` stages (an actor per block, pages streaming
between them) instead of datatrove's executors? `tests/integration/ray_data_spike.py` builds the `squiddle@1`
pipeline as a normal run does (the script's `pipeline()`, the builder, one task) and runs its 11 per-page blocks
(LayoutDetector, LineDetector, LineAssigner, LineRecognizer, UnicodeNormalizer, TableRecognizer, FormulaRecognizer,
Typographer, Recomposer, Composer, RecipeStamper) as one `map_batches` stage each: `batch_size=1`, one actor per
block (`ActorPoolStrategy(size=1)`), each `warm_up()` once and then `block.run` per page; the five model blocks
`num_gpus=0.2` and 3 CPUs each, the rule blocks 0.5 CPU. A page travels between stages as a row (id, text, metadata
as JSON, the image media's fields as JSON, the image bytes); the round trip is exact for all 60 pages. Ray 2.59.0
from the `transcribe_modular.py` environment (extra `[ray]`), nothing installed, no lock changed, torch
2.14.0+cu130 before and after. Pages: `bhl-ocr-eval/sample-60`, one run each, no warm-up run.

| | datatrove, local, 1 task | Ray Data |
|---|---|---|
| wall time, end to end | 84.4 s | 59.0 s |
| model loading | 16.1 s, one after another | in parallel, the longest 12.3 s (formulas) |
| after loading, to the last page | 65.4 s | 39.0 s |

- Outputs: the `ocr_new` transcription of all 60 pages is identical (every step's `seconds` and `datetime` left
  out); the whole rows of 59: the one page the normal run sampled for tracing has a `trace_id`.
- The gain is the blocks overlapping in separate processes: throughput is set by the recognition stage (44.9 s of
  the normal run's 65.4 s). Not measured: datatrove with two or more tasks on the one GPU, which overlaps the same way
  at the cost of each task loading its models.
- Blocks pickle into Ray actors with cloudpickle as they are (0.5 to 2 KB; `InProcess` leaves loaded models out).
  Five CUDA contexts instead of one; GPU memory not measured (the GB10 reports none). Ray sets `OMP_NUM_THREADS`
  to an actor's CPUs.
- Ray listens on every interface by default even with `_node_ip_address="127.0.0.1"`; with
  `RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER=0` set before `import ray`, every Ray process listened on loopback only (the
  script checks this while the actors run). Ray writes `~/.ray/auth_token` (token auth is on by default) and session
  folders under `/tmp/ray`.
- What the Ray Data path lacks: resume (no completion markers), `OUT/logs` and datatrove's stats (a block's
  `stat_update`s stay in its actor), stage cutting (item shards, `--until`, `--after`, `--tap-after`), the
  `RejectWriter` and the error budget (`run()` per page resets it), tracing, the run record, writers per rank.
  Back pressure was not exercised on 60 pages.

The same day, the two datatrove alternatives the comparison left out (same machine and pages, one run each, the GPU
otherwise idle; `uv run pipelines/transcribe_modular.py IMAGES OUT --recipe squiddle` plus the flags):

| | wall time, end to end | goldens (sample-60) |
|---|---|---|
| in-process, 1 task (above) | 84.4 s | — |
| `--backend served`, 1 task | 65.5 s (of it 15.3 s the server's warm-up) | 60/60 pages, 1560/1560 lines exact |
| in-process, `--tasks 2 --workers 2` | 64.4 s (the longer task 61.5 s) | 60/60 pages, 1560/1560 lines exact |
| Ray Data (above) | 59.0 s | `ocr_new` identical to the 1-task run |

Each closes most of the gap: 25.4 s of the 84.4 s with Ray Data, 18.9 s served, 20.0 s with two tasks. Served with
two tasks (a server per task) and larger `--window` values were not measured.

Recommendation: do not adopt it now. The outputs are the same and the time after loading is 1.7x shorter here, but
all of it comes from overlapping the blocks, and resume, logs, stats, rejects, tracing, the run record and stage
cutting would each have to be rebuilt on Ray. With served or two tasks per GPU, datatrove
gets within 6 s of it on these 60 pages; revisit only when one GPU per task is clearly underused on Jobs.

## Readable item texts from the item recomposition (2026-11-06, spark)

The six whole items of the BHL ground truth (2,165 pages), from the squiddle recipe's page records of the parity run
above (531a422). Before: `ItemTexts` (its own line flow, `join_lines`), recorded at ff3328f. After: `bind.py --recipe
item-texts` (`Binder` → `Recomposer(unit="item")` → `CharacterNormalizer` → `ItemTextWriter`).

| Item | Pages | Paragraphs before | after | Decisions before | after | Differ | Only before | Only after | CER before | after |
|---|---|---|---|---|---|---|---|---|---|---|
| birdsofgreatbrit02butl | 341 | 1,392 | 1,521 | 287 | 268 | 54 | 19 | 0 | 0.0288 | 0.0287 |
| conchologiaiconi05reev | 648 | 6,390 | 8,631 | 2,769 | 2,163 | 186 | 636 | 30 | 0.0705 | 0.0693 |
| daschitinskelett00prel | 84 | 492 | 600 | 314 | 299 | 1 | 15 | 0 | 0.0388 | 0.0388 |
| histoirenaturell10cuvi | 516 | 2,426 | 2,847 | 2,082 | 1,980 | 55 | 102 | 0 | 0.0475 | 0.0472 |
| pisciumquerelaee00sche | 60 | 144 | 206 | 438 | 414 | 1 | 26 | 2 | 0.1491 | 0.1494 |
| trudyrusskagoent161881russ | 516 | 3,096 | 3,843 | 3,155 | 2,994 | 17 | 163 | 2 | 0.0828 | 0.0827 |
| all | 2,165 | 13,940 | 17,648 | 9,045 | 8,118 | 314 | 961 | 34 | 0.0615 | 0.0610 |

- Paragraphs: the readable texts' blocks other than tables (a paragraph continued across regions or pages counts
  once). Decisions: a line-end hyphen removed or kept, keyed by page and the line it ends (after: the last line of
  the row). CER: `readable_txt` against the ground truth's page texts of the item joined in page order, whitespace
  collapsed to single spaces, edit distance over the ground truth's length (3,220,317 characters). The ground truth
  is as laid out and full page (running heads, page numbers, line-end hyphens kept), so both CERs include those.
- Differ (314): 311 hyphens the old flow removed (a lower-case letter followed) are kept now because the item has
  the hyphenated form elsewhere (`attested`): `ear-coverts`, `under tail-coverts`, `blackish-purple`,
  `fusco-nigricante`, `au-dessous`, `Au-devant`, `lui¬|même` → `lui-même`, `semi¬|cercle` → `semi-cercle`; 3 the
  other way (`letter_follows`), marks at the foot of a page whose paragraph continues on the next page.
- Only before (961): 834 rows ending in a hyphen after which the recomposition starts a new paragraph at an indented
  row (hanging indents in species descriptions and references, most of them in conchologiaiconi05reev:
  `anfractibus nunc per-|paucis`), so the mark stays at the paragraph's end; 82 region ends the recomposition does
  not continue (`olive to red-` at the end of a region); 37 lines the old flow joined side by side within a row
  (index entries, `Calcarius lapponicus-|130`); 8 row ends inside a paragraph without a decision.
- Only after (34): continuations across a region or page break the old flow did not join.
- verbatim_txt: identical for all six items. Item documents (md, txt, json) from `bind.py`'s blocks equal
  `BindItem`'s for all six in the project environment; `bind.py`'s own lock has docling-core 2.106.0 (the project
  2.105.0), whose JSON says `version` 1.11.0 instead of 1.10.0, md and txt identical.
- The squiddle recipe after the change: `compare_goldens.py` 60 of 60 pages exact, 1,560 of 1,560 lines.

## Rule-based steps on their engines: parity (2026-11-06, spark)

The squiddle recipe before (531a422) and after the rule-based steps moved onto their engines and presets
(`ratios@1`, `unicode-recomposition@1`, `docling-composition@1`), in-process:

- Page runs, sample-60 and tables-7, `--text reflow` and `lines`, with and without `--furniture`, formats md, txt,
  html, doclang, json, hocr, alto, page, transcription (2,412 files): md, txt, html, doclang and the Docling JSON
  byte-identical; hOCR, ALTO and PAGE identical apart from the step records (the typography step now named by its
  engine and preset, new recomposition and composition steps); transcription JSON and page records identical apart
  from the steps and, with `reflow`, the paragraphs the `Recomposer` adds. The documents replayed from the same page
  records with sections and dividers on and off: 5,360 files, all identical.
- `compare_goldens.py`: 60 of 60 pages exact, 1,560 of 1,560 lines.
- Item documents (`BindItem`, reflow) of the six whole items of the BHL ground truth (2,165 pages) from the same page
  records: md, txt, html, doclang, json identical. Item texts (`--item-texts`) of two whole items run again: the
  text files identical; the JSONL rows differ only in their trace context.

## Daniel's four kraken changes measured one by one (#1, 2026-11-04, HF Jobs L4)

Each change alone against the same baseline, full ground truth (bhl-impact-gt, 2,165 pages), one `l4x1` Job
per variant (one server reads every page), `--recipe squiddle`. Branches: kraken fork `perf/line-prefetch`
(b4f651aa), `perf/early-seq-lens` (cf21c0cd), stock 3d235ee8; linecaster `perf/kraken-sort-by-width`,
`perf/kraken-compile`; each variant a `measure/...` branch whose only commit is the kraken pin.

| change | recognition, steady state | vs baseline | text changed | shortest body lines (width/height < 2) | CERdip | CERread | recall | furniture |
|---|---|---|---|---|---|---|---|---|
| baseline (stock 3d235ee8) | 0.802 s/page | | | | 0.0576 | 0.0419 | 0.9754 | 0.8491 |
| 1 line prefetch | 0.733 s/page | −8.5 % | none | none | = baseline | | | |
| 2 seq_lens before the forward pass | 0.786 s/page | −1.9 % | none | none | = baseline | | | |
| 3 batching by line width | 0.728 s/page | −9.2 % | 0.220 % | 8.25 % of their characters | 0.0577 | 0.0416 | 0.9752 | 0.8441 |
| 4 torch.compile of the backbone | 0.719 s/page | −10.3 % | 0.021 % | 0.05 % | 0.0576 | 0.0419 | 0.9754 | 0.8485 |

- Changes 1 and 2 are in main (fork 48eecb78, both together; −12 % measured earlier on 300 pages).
- Change 3 reads the shortest lines (single characters, page numbers, the last word of a paragraph) worse:
  in a batch of only narrow lines they get little padding. Not adopted; batching stays as kraken forms it.
- Change 4 keeps the CER and the short lines; its 163 s warm-up per server pays off from about 2,000 pages
  per server (0.083 s saved per page). Candidate for long runs, ideally with the compile cache kept between
  Jobs (`torch.compiler.save_cache_artifacts` / `load_cache_artifacts`).
- Earlier round of the same day with 4 Jobs per variant: queueing for free L4s made launch-to-finish times
  misleading; the Jobs' own runtime is what counts.

## Later: hardware acceleration across platforms (parked 2026-11-04)

Ideas, none measured:

- kraken stays on PyTorch: CUDA (with torch.compile and its cache), MPS on Macs, CPU elsewhere; one model
  file, kraken's own code. AOTInductor `.pt2` packages per GPU type would remove the warm-up.
- PaddleX models: every one in the chain has a `PaddlePaddle/<name>_safetensors` variant whose architecture
  transformers 5.12 implements (pp_doclayout_v3, pp_ocrv6_*_det, slanet, pp_lcnet, pp_formulanet); PaddleX's
  transformers engine would put the whole chain on torch and drop onnxruntime-gpu. Changes numerics (goldens
  were recorded on ONNX Runtime) and speed is unknown.
- ONNX Runtime execution providers (TensorRT, CoreML, OpenVINO, DirectML) for platforms without a usable
  PyTorch; costs an export path of our own for kraken.
- VLMs off NVIDIA: llama.cpp (`llama-server`, GGUF) or MLX-VLM behind the same OpenAI interface as `chat.v1`;
  GGUF files as `converted` / `quantized` model documents, each with its own evidence. GGUF does not suit
  kraken (no graph importer in ggml; a reimplementation).

## kraken: batching by line width and torch.compile (#1, 2026-11-04: spark, HF Jobs L4)

Daniel van Strien's changes 3 and 4 as options of `kraken.recognition.v1`, off by default: `sort_by_width` (a
page's lines go to kraken widest first, by box width / height, and come back in line order) and
`compile_backbone` (`torch.compile(dynamic=True)` of the PP-OCRv6 backbone). Measured with `--recipe squiddle
--set recognition....`, against the same commit without them (93bac25, kraken fork 48eecb78).

Full ground truth (bhl-impact-gt, 2,165 pages), HF Jobs `l4x1`, 4 tasks of 541 pages each, served:

| | recognition, steady state | compile warm-up | characters changed | CERdip | CERread | recall | furniture |
|---|---|---|---|---|---|---|---|
| kraken-ppocrv6-medium@1 | 0.724 s/page | | | 0.0576 | 0.0419 | 0.9754 | 0.8491 |
| + sort_by_width | 0.650 s/page (−10 %) | | 0.220 % | 0.0577 | 0.0416 | 0.9752 | 0.8441 |
| + sort_by_width + compile_backbone | 0.529 s/page (−27 %) | about 167 s per server | 0.223 % | 0.0578 | 0.0416 | 0.9752 | 0.8437 |

- Scored with the frozen bhl-ocr-eval harness (board lane). sample-60 and tables-7 move the same way (sample-60
  CERread 0.0268 → 0.0265). On sample-60 locally (spark, in-process): 0.716 → 0.631 → 0.530 s/page, compile
  warm-up about 52 s.
- Characters change much more than on Daniel's single book (0.03 %): other batches pad differently, which
  flips CTC near-ties; word boxes move more often than text.
- The furniture drop is the typography step: it removes 70–72 page numbers as uncertain instead of 61, because
  short page-number lines come out with other text or confidence in other batches. Its rule was tuned on the
  old batching.
- Compiling pays off only for long-lived servers: about 167 s of warm-up against 0.12 s saved per page, so
  from about 1,400 pages per server. With 541 pages per task the compiled run used more GPU time in total
  than sorting alone.
- Neither option was adopted from this round: `sort_by_width` was dropped (it is not in linecaster), and
  `compile_backbone` is an option off by default (see the entry above for both measured on their own).

Where the characters change with `sort_by_width` (full ground truth, against kraken's own batching):

| region | line width / height | lines | lines changed | characters changed | mean confidence |
|---|---|---|---|---|---|
| body | < 2 (one or two characters) | 3,430 | 569 | 8.25 % | −0.119 |
| body | 2–5 | 2,961 | 242 | 1.76 % | −0.012 |
| body | 5–10 | 7,093 | 762 | 0.94 % | −0.001 |
| body | 10–20 | 26,590 | 1,831 | 0.21 % | ±0 |
| body | ≥ 20 | 27,229 | 1,087 | 0.07 % | ±0 |

Sorted widest first, a page's narrowest lines end up together in the last batch, only a few dozen pixels wide;
in kraken's order they share batches with full-width lines and are padded to them. Page numbers dropped only with
sorting (17; 6 the other way): `viii` (0.97) → `rii` (0.60), `vii` (0.99) → `ru` (0.69), `ii` (0.95) → empty,
`xj` (0.97) → empty, `IX` (0.99) → `IX` (0.74), `G3` (0.91) → `G3` (0.67). The typography rule (mean character
confidence below 0.75) only reveals it; lowering it would keep the wrong readings.


## kraken line prefetch (#1, 2026-11-04: spark, forge, HF Jobs L4)

Daniel van Strien's issue #1: kraken's recognition loop makes the CPU wait for the GPU on every line (the
empty-line check on a tensor built on the device) and once per batch (`seq_lens` copied after the backbone is
queued). Fork commit `48eecb78` (storytracer/kraken, `perf/recognition-prefetch`): lines are extracted,
transformed and checked on the CPU in a producer thread, `seq_lens` goes to the device before the forward pass,
and the last partial batch is recognized also when a page ends in empty lines (stock kraken flushed it only on an
append, so such lines were never recognized and the page failed `zip(strict=True)`). Batches are formed as
before, so the output is unchanged.

| machine | recognition, pinned `3d235ee8` | patched `48eecb78` | output |
|---|---|---|---|
| spark GB10, sample-60 in-process | 0.73 s/page | 0.77 s/page (noise) | goldens 1,560/1,560 lines |
| forge RTX 4000 Ada, sample-60 in-process | 0.647 s/page (warm) | 0.61 s/page (−6 %) | goldens 1,560/1,560 lines |
| HF Jobs `l4x1`, bhl-impact-gt first 300 pages, served | 0.903 s/page | 0.793 s/page (−12 %) | 300/300 pages, 7,276/7,276 lines identical |

The GB10 gains nothing: its CPU does not stall the GPU the way an L4 host does. On the L4 recognition sets the
pace (served wall 274 s → 242 s). Not done yet (they change 0.02–0.03 % of characters): batching by line width
and `torch.compile` of the backbone, Daniel's changes 3 and 4.

Same change set: TablesStep and FormulasStep send no image for a page without their regions (the engines still
record the step), a malformed served answer is that page's error, the readiness probe uses the step route, and
`HFImageDatasetReader` raises when a repository has no Parquet files (an image folder such as
`finebooks/bhl-impact-gt` silently read 0 pages with `--dataset`; it is read as `hf://datasets/...` IMAGES).

## Specs are reference documents (2026-11-04)

`specs/` describes what is, without history. Moved here from them:

- The catalog's role models: HTRMoPo v1 and Hugging Face model cards (Markdown with YAML front matter),
  OCR-D (functional steps, declared resources, provenance per processing step), Docling (typed options per
  engine, one factory per stage), spaCy (versioned registry names that stay resolvable), Datalab's marker,
  surya and chandra (configuration declared once, evidence with its source), Daniel van Strien's
  `uv-scripts/ocr/models.json` (one catalog, support levels), ocrscout's profiles (label mappings as data).
- WebP encoding effort, one measurement on spark, a 3996 × 5964 newspaper JPEG: decode 0.09 s; encode effort
  0: 1.67 s / 17.2 MB, 25: 1.99 s / 17.1 MB, 80: 7.0 s / 16.6 MB, 100: 9.6 s / 16.4 MB. Effort 0 is 4× faster
  for 4 % more bytes; left at Pillow's default (80) until measured on a broader sample.
- The kraken source lesson (a source applies only to direct dependencies) is under "Lessons" below.

## launch.py: recipes and models by name (2026-11-04, spark)

`uv run launch.py squiddle IMAGES OUT` and `uv run launch.py chandra-ocr-2 IMAGES OUT`: a recipe names its
pipeline (`chain.v1`), a whole-page preset runs in `vlm.v1`; `launch.py` finds the script declaring that
`PIPELINE` (`catalog.code.pipelines`, ast) and execs `uv run --script pipelines/<script>.py ... --recipe NAME`
(or `--vlm NAME`), so the pipeline keeps its own environment and launch.py needs only linecaster's core.
Discussed and dropped: the kind of entry as first argument (`model`/`recipe`/`pipeline`), `server` and `cluster`
words, and names such as run.py (`uv run run.py`), recipe.py, transcribe.py, read.py, lc.py. Own combinations
use the pipeline scripts directly. Names stay unambiguous: the catalog already refuses an id used by a preset
and a recipe. A preset that is one step (a line recognizer, a region reader) gets a hint instead: which pipeline
and flag, and the recipes that use it. Checked: `--dry-run` builds the squiddle chain with its recipe record and
chandra-ocr-2's vLLM command at the pinned revision.

## One catalog (2026-11-04, spark)

The catalog is one folder, `src/linecaster/catalog/data/`: the engine packages' catalogs (kraken, PaddleX,
Tesseract: 21 models, 18 presets, their evidence) and squiddleocr's (the recipe `squiddle` and its 4 evidence
records) were moved into it, and the entry-point group `linecaster.catalog`, `--with-dir` and recipe file paths
went. Presets are grouped by step (`presets/<step>/<id>.md`, the folder checked against `step`). "kind" is gone: a
preset names its engine, `engine: kraken.recognition.v1`, with `options:` beside it; a recipe its pipeline,
`pipeline: chain.v1`; code ids end in `.v<n>` (were `/1`). The generated docs are grouped by kind
(`docs/catalog/{engines,models,presets/<step>,pipelines,recipes}`); engine and pipeline pages are read from the
source with `ast`, since no environment has every engine.

- The lock was re-released from scratch: the functional content changed shape (`engine` a string, `options` at
  the top), so every hash changed; the editions stayed (39 presets at edition 1, `slanet-plus` at 2; `squiddle@1`).
  `slanet-plus@1` was dropped from the lock; no run had recorded it. This is the last re-baselining before runs
  record editions in earnest; from now on a released edition changes only as a new edition.

## Pipelines and recipes (2026-11-03, spark)

"Recipes" were pipeline shapes with slots, and since the defaults went they chose nothing: renamed `pipelines/`
(`chain.py`, kind `chain/1`; `vlm.py`, `vlm/1`; `cuda_probe.py` to `tools/`; since 2026-11-05
`transcribe_chain.py` and `transcribe_vlm.py`, and the item stage `items.py` is `bind.py`). A **recipe** is now a catalog
document: a pipeline kind, a preset edition for each slot, options; edition, provenance, support level and evidence
like presets. Its hash covers its presets' hashes (and so their model pins), and it is released only on released
preset editions. `--recipe id[@edition]` or a recipe file fills the slots and options the command line leaves open;
what the command line gives instead goes into the run record as overrides. `RecipeStamp` (before the first writer)
puts the recipe edition and hash into every `ModelInfo`, so page rows and ALTO/PAGE/hOCR name it.

- squiddleocr ships `squiddle@1` (its catalog, entry point `linecaster.catalog`): pp-doclayoutv3@1,
  pp-ocrv6-medium-det@1, kraken-ppocrv6-medium@1, slanet-plus@2, pp-formulanet-plus-l@1, text reflow. Its evidence:
  the goldens reproduced (sample-60 1,560/1,560 lines and tables-7 651/651, in-process and served).
  `uv run pipelines/chain.py IMAGES OUT --recipe ../squiddleocr/src/squiddleocr/catalog/recipes/squiddle.md` on
  sample-60: goldens 1,560/1,560, `squiddle@1` in every ALTO step and in `run.yaml`. `squiddle ocr` stamps the recipe
  when its options are the recipe's.
- The recognizer comparison stays preset evidence (it varied one preset), with the rest of the pipeline as
  `context`.

## The catalog: models, presets, evidence (2026-11-03, spark)

`docs/reference/catalog.md` is the design; built in parallel by three agents (engines, VLMs, provenance) on top of the
foundation (`linecaster.catalog`). In the checkout: 39 models with their upstream cards copied verbatim, 39 presets
released as edition 1 (`slanet-plus` also edition 2), 39 evidence records.

- **PaddleX downloads** `PaddlePaddle/<name>_onnx` (ONNX Runtime) or `_safetensors` (transformers) from Hugging Face
  at `main`, without a revision (PaddleX 3.7.2, `official_models.py`), into `~/.paddlex/official_models/`. Those
  repositories are what is pinned now; the engines load the pinned snapshot with `create_predictor(model_dir=...)`.
  Identical outputs to PaddleX's own download on 3 pages (layout V3 and plus-L, lines, PaddleX small rec, SLANet_plus
  table HTML, PP-FormulaNet_plus-L LaTeX); tiny/small det, tiny/medium rec and PP-FormulaNet-L not compared.
- **kraken's PP-OCRv6 models** are trained from scratch on an architecture adapted from PP-OCRv6 (their card), not
  converted from PaddleOCR's weights: `derived_from` is only the Zenodo mirror relation.
- **Tables** need four models; `submodels` (by PaddleX name) pins the classifier and the two cell detectors next to
  SLANet_plus, so their file hashes are part of the edition (`slanet-plus@2`; `@1` held them as an option).
- **Hashes cover only what a document states** (`exclude_unset`): adding the server fields `revision_flag`,
  `pin_ignore`, `server_packages` and `draft` to `Serve` had changed every chat preset's hash through the defaults.
  The current editions were released again under that rule before the first push.
- **Chat presets**: requests, server commands and Jobs plans byte-identical to the former spec classes for all 20
  models, with two deliberate changes: LightOnOCR-3 (0.8B, 4B) now names `vllm/vllm-openai:v0.30.0`, the version the
  board validated them with (the old recipe used 0.26.0, with which LightOn says they loop); Unlimited-OCR-2's
  recorded `sglang_version` is now the wheel that runs (`0.5.20.dev10+g8d62f5fb9c`).
- **Licenses to check by hand** (as the cards state them): chandra "AI Pubs Open RAIL-M License (Modified)",
  Nemotron `OpenMDW-1.1`; SmolDocling's front matter says CDLA-Permissive-2.0, its text Apache-2.0.

Parity of `recipes/chain.py` through presets (pinned PaddleX snapshots, kraken from its pin) with squiddleocr's
goldens (7c8a052, spark): sample-60 1,560/1,560 lines and 60/60 pages exact in-process (80 s), served with the
server in the task (71 s) and against `uv run recipes/chain.py serve` (47 s); tables-7 651/651 in-process and
served. Served pages carry preset, edition, hash and the step's start time in every `ModelInfo`.

## One recipe per pipeline (2026-11-03, spark)

The scripts had made the environments self-contained, but the pipelines were still copied once per machine: the
squiddle chain three times (`examples/`, `recipes/ray/`, `recipes/hf-jobs/`), its model list four times (with
`examples/squiddle_models.json`), the chat page and region pipelines twice each, the kraken + PaddleX metadata block
twice. Now:
- `recipes/chain.py`: layout → lines → assignment → kraken, PaddleX PP-OCRv6 or Tesseract (`--recognizer`) → NFC →
  tables → formulas → typography → document, with --files/--exports/--texts. One environment holds all three
  engines (torch + PaddleX + tesserocr resolve together), so the PaddleX + Tesseract combination needs no script of
  its own. The HF Jobs chain now runs NFC, typography and page composition too (it wrote raw page rows before).
- `recipes/vlm.py`: a chat VLM per page, or per PP-DocLayoutV3 region with `--regions` (MiniCPM-OCR is one model it
  takes; its DSpark draft comes from the spec, its image from the recipe's table of validated images).
- `linecaster.runtime.run` gives both the same command line: `--on local|ray|hf-jobs`, `--backend in-process|served`
  (default in-process here, served on Ray and Jobs), `--endpoint`, `serve` (`linecaster serve` with the recipe's
  models, picked by its options) and `ray ...` (Ray's CLI from the recipe's environment). Page rows go to
  `OUT/rows/${rank}.jsonl.gz`, logs to `OUT/logs`, on every machine.
- `ServeModels(script=...)` starts a recipe's `serve`; `jobs.dependencies(commit, script)` reads a recipe's metadata
  (`engines=False`: linecaster alone, for page VLMs in a vLLM image).
- `point_to_gpu` moves each server and loopback client up by the GPU index instead of setting all of them to
  `base_port + GPU`: with a layout server and vLLM in one task, the old rule put both on the same port.
  `base_port` is gone from `RayGPUExecutor` and `GPUJobsExecutor`.
- Dry runs (`--dry-run`) give the old recipes' plans: images, `--with` lists and server commands (MiniCPM: the
  same vLLM flags with the DSpark speculative config, `outside_venv`, 0.8 of the GPU).
- Both recipes carry `linecaster[ray]` for `--on ray`; `dependencies()` leaves the extra out of a Job's list. Adding
  Ray and Tesseract changed no version in the lock the goldens run used (packages added only).

Checked on spark against squiddleocr's goldens (7c8a052) and on Ray (3 pages, one task):

| run of `recipes/chain.py` | sample-60 lines (box + words) | tables-7 lines | wall, sample-60 |
|---|---:|---:|---:|
| in-process | 1,560/1,560, 60/60 pages exact | 651/651, 7/7 | 88 s |
| `--backend served` (the task starts `serve`) | 1,560/1,560, 60/60 pages exact | 651/651, 7/7 | 63 s |
| `--endpoint` against `uv run recipes/chain.py serve` | 1,560/1,560, 60/60 pages exact | | 47 s |
| `--on ray`, Ray started with `uv run recipes/chain.py ray start` | 3/3 pages written | | |

`recipes/vlm.py` on spark (vLLM 0.21.0, started in the task, `--gpu-memory-utilization 0.3`), sample-60:
- page mode, LightOnOCR-2-1B: 60/60 pages in 232 s, CERread 0.0372 (CERdip 0.0738, 4 of 60 truncated), board lane.
  The old HF Jobs recipe's run of the same model scores 0.0403 with today's harness; sampling is at temperature 0.2.
- `--regions` (PP-DocLayoutV3 in-process + LightOnOCR-2-1B per region): 60/60 pages in 584 s, no errors, 418 regions
  read; 64 of them ran into the token limit (LightOnOCR's known looping on crops). Not scored.
- HF Jobs: a LightOnOCR page smoke was launched; MiniCPM regions was canceled while it waited for an L4.

## Self-contained uv scripts instead of environment folders (2026-11-03, spark)

`envs/kraken-paddlex` and `envs/paddlex-tesseract` are gone. Every example, recipe and server is a uv script
with inline metadata (PEP 723) and a `<script>.py.lock` next to it:
- `servers/kraken-paddlex.py`, `servers/paddlex-tesseract.py`: `linecaster serve` with one engine combination.
  `ServeModels(script=...)` starts one with `uv run --script`; `linecaster.runtime.jobs.dependencies(commit, engines)` reads
  its metadata for a Job's `--with` list (sources as URLs at the commit, pins for the packages its lock resolves), so
  the pins live in one place per combination instead of in `jobs.py`.
- `examples/squiddle_chain.py` carries the kraken-paddlex block (in-process needs the engines); the VLM examples and
  the HF Jobs launchers carry core linecaster only; `recipes/ray/squiddle_chain.py` carries linecaster with Ray and
  runs Ray's own CLI from its environment (`uv run recipes/ray/squiddle_chain.py ray start --head`), because Ray's
  `uv run` support (`RAY_ENABLE_UV_RUN_RUNTIME_ENV`) does not handle scripts: workers came up without Ray. It is
  switched off in the recipe. Checked on spark: 3 pages, one task, server started from the script.
- Locking the scripts afresh moved seven packages the old env lock had older: the CUDA libraries (cuBLAS 13.8,
  NVRTC/runtime 13.4, cuFFT 12.4, cuRAND 10.4.4), cuDNN 9.27 (paddlex-tesseract) and scipy 1.16–1.18,
  scikit-image 0.26. All are pinned back to the goldens' versions in `constraint-dependencies`, the same list in
  every engine script; the kraken-paddlex lock then differs from the old env lock only in soupsieve, pyarrow and
  ujson.
- uv's `required-environments` is not accepted in script metadata. `tests/test_scripts.py` stands in: same pins and
  kraken source in every script, a lock per script, the pins resolved, and Linux wheels for aarch64 and x86_64 for
  every package with platform wheels. One allowed source build: coremltools (kraken's CoreML format, no aarch64
  wheel; built from source on spark before as well; not on the recognition path).

Parity of the scripts with squiddleocr's goldens (7c8a052, spark): `uv run examples/squiddle_chain.py`, in-process
and served through `uv run servers/kraken-paddlex.py`:

| run | sample-60 lines (box + words) | tables-7 lines | wall, sample-60 |
|---|---:|---:|---:|
| in-process | 1,560/1,560, 60/60 pages exact | 651/651, 7/7 | 89 s |
| served | 1,560/1,560, 60/60 pages exact | 651/651, 7/7 | 48 s |

## More line recognizers: PaddleX PP-OCRv6 and Tesseract (2026-11-03, spark)

Two more engines for `RecognitionStep`, next to kraken:
- `linecaster_paddlex:PaddleRecognitionModel`: PaddleOCR's own PP-OCRv6 recognizers (`PP-OCRv6_{tiny,small,medium}_rec`)
  on PaddleX's ONNX Runtime engine. Lines cut as PaddleX's OCR pipeline cuts them (minimum-area rectangle, warped upright),
  sorted by aspect ratio, `batch_size` 8. Words: the text split at whitespace (kraken's rule), placed along the line
  rectangle by the CTC columns of their characters (PaddleX's `return_word_box` mapping); no per-word confidence.
  PP-OCRv5 left out on purpose: PP-OCRv6 only.
- `linecaster_tesseract:TesseractRecognitionModel` (new package `linecaster-tesseract`): Tesseract 5.5.3 LSTM through
  tesserocr 2.12.0 (the wheels bundle Tesseract and Leptonica on Linux aarch64 and x86_64), page segmentation mode 7 on
  each line's bounding box, outside the polygon painted white, 4 px white padding. Words, boxes and confidences from
  Tesseract. Language data from tessdata_best (default) or tessdata_fast, pinned to a commit, cached in
  `~/.cache/linecaster/tessdata`. On the CPU, one line at a time.
- New engine combination PaddleX + Tesseract (no torch, so no PP-FormulaNet there); now the script
  `servers/paddlex-tesseract.py`.

Comparison on the 60-page sample: the same chain for every row (PP-DocLayoutV3 → PP-OCRv6 medium detection → line
assignment → *recognizer* → NFC → tables → typography → document → Markdown), in-process, one task, scored as-is
(no postproc) with the frozen bhl-ocr-eval harness (`score_dataset`, sample-60 at 41ff3475). Wall includes model loading.

| recognizer | CERdip | CERread | recall | wall, 60 pages |
|---|---:|---:|---:|---:|
| kraken PP-OCRv6 medium (bf16) | 0.0341 | 0.0270 | 0.9508 | 72 s |
| PaddleX PP-OCRv6 medium | 0.0387 | 0.0315 | 0.9343 | 49 s |
| PaddleX PP-OCRv6 small | 0.0375 | 0.0300 | 0.9351 | 44 s |
| PaddleX PP-OCRv6 tiny | 0.0446 | 0.0376 | 0.9123 | 33 s |
| Tesseract best, `script/Latin` | 0.0430 | 0.0364 | 0.9131 | 132 s |
| Tesseract best, `eng` | 0.0595 | 0.0516 | 0.8570 | 110 s |

- kraken's port reads better than PaddleX's own runtime of the same model family on every volume but one (cuvier); the
  likely difference is the line image (kraken's polygon-based extraction against PaddleX's rectangle warp). Not
  investigated further.
- PaddleX small is as good as medium here (0.0300 vs 0.0315): a 60-page sample, no conclusion about defaults.
- Tesseract with the Latin script model is close to PP-OCRv6 tiny; `eng` alone loses on the German, French, Latin and
  Russian volumes. Tesseract is the slowest (CPU, single process); more tasks would spread it over cores.
- No default changed.

## squiddleocr 0.3's features in linecaster (2026-11-03, spark)

Every feature and option of squiddleocr 0.3's paddle pipeline (`squiddle legacy ocr --pipeline paddle`), where it
lives now. eynollah and kraken's blla pipeline are out of scope (they stay in `squiddle legacy`).

| 0.3 feature or option | status | where |
|---|---|---|
| PP-DocLayoutV3 layout, learned reading order | already in linecaster | `LayoutStep` + `PaddleLayoutModel` |
| `--layout-model PP-DocLayout_plus-L` (XY-cut order) | already in linecaster | `PaddleLayoutModel(model_name=...)` |
| `--layout none` (the page is one text region) | missing, built | `SingleRegionLayout` (`blocks/layout/single_region.py`) |
| PP-OCRv6 detection, `--det-model`, `--unclip-ratio` | already in linecaster | `LinesStep` + `PaddleLineModel(model_name, unclip_ratio)` |
| lines into regions, orphan rows, pictures skipped | already in linecaster | `AssignLinesToRegions` (`formulas_separately=False` without formulas) |
| kraken recognition, `-m tiny/small/medium/path`, `--batch-size`, `--precision` | already in linecaster | `RecognitionStep` + `KrakenRecognitionModel` |
| `--device` | already in linecaster | `device` of every engine (in-process; the server's otherwise) |
| `--rtl` | already in linecaster | `KrakenRecognitionModel(text_direction=...)`, `ComposePage(rtl=)`, `BindItem(rtl=)` |
| `--tables` | already in linecaster | `TablesStep` + `PaddleTableModel` |
| `--formulas`, `--formula-model` | already in linecaster | `FormulasStep` + `PaddleFormulaModel` (29/29 formulas identical, 82e2e7b) |
| `--typography` (heading levels, demotion, headline split, drop capitals, uncertain page numbers) | already in linecaster | `Typography` |
| NFC of the as-written text | linecaster's choice (0.3 kept kraken's decomposed text) | `NormalizeUnicode` |
| `--text reflow/lines` | already in linecaster | `ComposePage(text=)`, `BindItem(text=)` |
| `--sections` | per item already; per page missing, built | `BindItem(sections=)`; `ComposePage(sections=)` |
| `--dividers` | per item already; per page missing, built | `ComposePage` keeps the item → region map (`extra["docling_region_of"]`); `dividers` on `PageFilesWriter` / `PageExportsWriter` |
| `--furniture` | already in linecaster | `furniture` on the export writers (the items always sit in Docling's furniture layer) |
| `--per-document` | already in linecaster | `BindItem` + `ItemExportsWriter`; `ImageFolderReader(item_id=, sequence=)` (built) puts a run's pages into one item in name order |
| `-f md, txt, json` | already in linecaster | `PageFilesWriter`, `PageExportsWriter`, `ItemExportsWriter`; JSON now formatted as docling's `save_as_json` |
| `-f html, doclang` | missing, built | `linecaster.formats.docling.export` / `to_html` / `to_doclang` in all three writers |
| `-f hocr, alto, page` | already in linecaster | linecaster's lxml serializers (not kraken's, by design) |
| `--detail word` | already in linecaster | the serializers' default (words are the finest level) |
| `--detail line` | missing, built | `PageFilesWriter(detail="line")` (a word-less copy to the serializers) |
| `--detail glyph` (0.3's default) | not in linecaster, by design | no glyph level in the data model; squiddle's default becomes `word` |
| `--plots` | missing, built | `linecaster.images.plots.plot_layout`, `PageFilesWriter` format `plot` (`<page>.layout.jpg`) |
| processing settings in ALTO | already in linecaster | `ModelInfo` per step → ALTO `Processing` |
| output naming `<name>.<suffix>.<ext>`, next to the image unless `-o`; per-document stem (folder name, file stem or `document`); `--suffix`; format `auto` = md | squiddle-specific | squiddleocr `cli.py` (writer `suffix=`, a `PageFilesWriter` subclass for "next to the image") |
| status lines (typography and reflow counts), failed pages listed at the end | squiddle-specific | datatrove's stats instead; an in-process exception stops the task (served errors are recorded per page) |

**Parity.** `squiddle ocr` (squiddleocr 0.4, now built from these blocks) against `squiddle legacy ocr` on the same
machine and environment: sample-60 + tables-7 (67 BHL pages), `squiddletest/scans` (17), `squiddletest/formulas`
(12), each in 7 configurations (defaults with every format and plots; `--text lines --furniture --sections
--dividers --detail line`; `--no-typography --no-tables --no-formulas`; `--layout none`;
`--layout-model PP-DocLayout_plus-L`; reflow with `--dividers --furniture`; `-m small --det-model
PP-OCRv6_small_det --unclip-ratio 2.0 --batch-size 4` on scans and formulas), and the 6 books × 10 pages per
document in 4 combinations. Each run twice: as shipped, and with NFC switched off (`--no-nfc`, hidden, for
parity only). Scripts in squiddleocr's `work/parity/` (git-ignored); outputs in `~/data/squiddle-parity/`.

- **Without NFC every document format and the plots are byte-exact** in every configuration on every page:
  md, txt, html, doclang, json, layout.jpg (96 pages × 7 configurations, c7 on 29 pages), with `--furniture` aside
  (below).
- **As shipped (NFC):** md, txt, html and doclang are byte-exact or exact after NFC of 0.3's text on every page,
  except where NFC changes reflow decisions: 10 division marks on 9 sample-60 pages (`mâ-`/`choire`,
  `géné-`/`ral`, `exté¬`/`rieur`, ...), removed now because the character before the mark is a letter after
  NFC and a combining accent (Mn) in 0.3's decomposed text. The same cause as on the books (above). JSON:
  the same plus charspans (lengths of NFC strings).
- **`--furniture` in json and doclang:** 0.3 moved page headers and footers into the body layer; linecaster keeps
  them in Docling's furniture layer and the export chooses. JSON differs in `content_layer` of those items,
  DocLang by the `<layer value="furniture"/>` marker; md, txt and html are exact. Kept by decision.
- **JSON provenance clamping:** docling-core clamps provenance boxes to the page whenever it validates a
  document; 0.3's JSON had them clamped only when Markdown or text was exported before JSON in the same run
  (`-f json` alone kept a picture box at y = −3). `DocumentBuilder.build` now validates (clamped always); 4
  sample-60 pages with picture boxes past the edge are exact since.
- **JSON charspans and DocLang:** docling-core's DocLang export rewrites the provenance charspans of the document
  it serializes; 0.3 saved its JSON from that same document, so with `doclang` before `json` in `-f` 0.3's
  charspans changed (reflow paragraphs: every row's span restarted at 0). linecaster writes JSON from the
  stored document and `to_doclang` works on a copy, so the order of formats does not matter; the parity runs
  list json before doclang.
- **hocr, alto, page** are linecaster's serializers, so the files differ by design; read back with linecaster's
  readers, every line on every page has the same text, line box and word boxes (words: NFC text and box),
  with three conventions of kraken's serializer set aside: kraken writes whitespace runs as words of their
  own (hOCR, PAGE), collapses double spaces between ALTO Strings, and clips line boxes to width − 1 / height − 1
  (one `--layout none` page whose line reaches the right edge). At `--detail line` kraken's ALTO has one
  box-less String per line, linecaster's one String with the line's box: same text and line boxes.
- **Served** (`linecaster serve` with `squiddle models-config`, defaults, 96 pages and the 6 books): identical to
  in-process.
- **Per document** (6 books, reflow / lines + sections + dividers / reflow + dividers + furniture / lines +
  furniture): without NFC md, txt, html, doclang and json identical for all 24 (furniture layer aside); with NFC
  the lines combinations exact after NFC, reflow 4/6 books (histoirenaturell10cuvi, trudyrusskagoent: the NFC
  division marks, as above).

- `--rtl` and `--device cpu` on one page (iiif_page_8, left to right): exact without NFC (kraken on the CPU at
  32-true, the PaddleX models on ONNX Runtime's CPU provider).

Not exercised here: a right-to-left page, `--device tensorrt` / `coreml`, `-m` with a model file path,
PP-FormulaNet-L, forge.

## Unlimited-OCR, Unlimited-OCR-2, PaddleOCR-VL-1.6, GLM-OCR specs; SGLang in ServeChatModel (2026-11-03, not yet run)

- Four page specs from the board drivers: `models/unlimited_ocr.py` (`UnlimitedOCR` on vLLM 0.26.0,
  `UnlimitedOCR2` on SGLang), `models/paddleocr_vl.py`, `models/glm_ocr.py`. Checkpoints pinned to the
  board's; completions verbatim, the board's post-processing (grounding strip, Baidu's Markdown
  converter, strip) left to the harness.
- PaddleOCR-VL-1.6 is run as the board runs it: the VLM alone on the whole page with `OCR:`, the
  recipe's client-side `smart_resize`; not PaddleOCR-VL's PP-DocLayout + VLM pipeline.
- `ServeChatModel` starts SGLang for a spec with `server = "sglang"`: `python -m sglang.launch_server
  --model-path ... --enable-metrics`, the spec's `server_env` through `env`, its `server_packages`
  installed into the server's Python with `uv pip install --python` first, and `gpu_memory_utilization`
  passed as `--mem-fraction-static`. `recipes/hf-jobs/chat_page.py` runs SGLang specs with
  `outside_venv` (the image's `/opt/sglang/bin/python3`).
- Unlimited-OCR-2 cannot take `--revision` (Baidu's SGLang then skips its tokenizer fix-up). The board
  refused to start unless the default branch was the pinned commit. Since then the default branch has
  moved, with README and wheel changes only. So `revision_flag = False` makes the serve block compare
  git blob ids between the default branch and the pin, ignoring README, `.gitattributes`, `wheel/` and
  PDFs. Baidu's dev10 wheel is still read from the pinned revision (on main it is replaced by dev13).
- `lmsysorg/sglang:v0.5.20-cu130` (amd64) from its image config: SGLang in `/opt/sglang` (Python 3.12),
  first on PATH. The board's own Job ran `hf jobs uv run` on it, so uv is there.
- Not checked: any of the four on a GPU, and Unlimited-OCR-2 on an L4. The board ran it on an RTX PRO
  6000 with the card's flags for an 80 GB A800 (`--mem-fraction-static 0.7`, CUDA graphs up to 16384
  prefill tokens).

## Qwen3.5-9B, Qianfan-OCR, DeepSeek-OCR and DeepSeek-OCR-2 specs for ChatPageStep (2026-11-03, not yet run)

- `models/qwen35.py`, `models/qianfan_ocr.py`, `models/deepseek_ocr.py` reproduce the board drivers; each
  module's docstring lists request, image handling, sampling and serve flags. Checkpoints pinned; vLLM 0.26.0.
- Qwen3.5-9B is the board's "greedy + card penalties" row: `neutral` prompt, temperature 0.0 with
  presence_penalty 1.5 and repetition_penalty 1.0, JPEG q95 capped at 2048 x 1024 px of area.
- Qianfan-OCR and DeepSeek-OCR send the page at full resolution. Qianfan gets the image bytes as received
  (the sample-60 lossless WebP decodes to the same pixels the board's dataset bytes did); DeepSeek gets
  RGB PNG/JPEG as is and anything else as RGB PNG.
- DeepSeek: vLLM's default resolution (Gundam), grounding prompt, `skip_special_tokens` false; the card's
  n-gram guard is registered at boot (`--logits_processors`, kept last on the command line) and set per
  request (`vllm_xargs`). v2 uses v1's processor and `<td>`/`</td>` whitelist, as the v2 vLLM recipe does;
  that the ids are the same tokens in v2's tokenizer is not verified.
- Completions are kept verbatim. The board's post-processing stays in the harness: `unwrap_fence` (Qwen),
  the `</think>` strip (Qianfan), `deepseek_strip_grounding` (both DeepSeeks, postproc 3).
  `qwen35.unwrap_fence` and `deepseek_ocr.strip_grounding` apply the same rules for other consumers.
- Memory: Qwen3.5-9B has 18.0 GiB of bf16 weights. The board ran it on an L40S at 0.9. On a 24 GB card
  (L4, A10G) about 2 GiB would be left at 0.9 for activations, the vision encoder and the KV cache. That
  fit has not been tested. The other three need 6 to 9 GiB of weights and ran on an A10G.

## SmolDocling and Nemotron 3.5 Parse specs; three board rows that are not chat models (2026-11-03, not yet run)

`SmolDocling` (`ds4sd/SmolDocling-256M-preview`) and `NemotronParse35` (`nvidia/Nemotron-3.5-Parse`) follow the BHL
board's drivers (module docstrings). Not checked on a GPU yet.
- SmolDocling answers in DocTags. The completion is kept verbatim; `parse` also stores the board's conversion
  (docling-core, body + furniture, no image placeholder) in `extra["markdown"]`. The board converted with docling-core
  2.89; the lock has a newer one, so a scorer that wants the board's exact text should compare both.
- Nemotron 3.5 Parse needs NVIDIA's vLLM plugin from the model repo. `ChatModel.serve_setup()` is a bash script that
  `ServeChatModel` runs before `vllm serve`. For this model it installs the plugin into the Python that runs `vllm`,
  the way the board's install script does. The card's flags include FlashAttention 3, a Hopper kernel: the board ran
  on an H200, and the flags as they are will not run on an L4. The board's Markdown rendering imports code from the
  model repo, so `parse` does not call it; `to_markdown` reproduces it.
- Not chat models, so no spec. They do not fit `ChatPageStep`:
  - `datalab-to/indra-ocr`: the board ran it in-process on CPU (the `indra-ocr` package: ONNX Runtime detector,
    orientation, script classifier, line recognizers, layout and reading order). It would need an engine package
    `backends/indra/` (`linecaster-indra`, pinning `indra-ocr==1.1.2` and the model tag `v1.1.0`). Its engine model
    would call `indra_ocr.load(mode="auto", furniture=False, math=False, dpi=200, threads=1)` and `Converter.convert(path)`
    on the page file, and return `page.markdown` (and the package's lines, if it exposes geometry). A page the package
    marks `source == "error"` would be an error.
  - `SoMarkAI/OXR-1.0` and `tiiuae/Falcon-OCR`: vendor page pipelines inside their own images: a layout model, a VLM
    behind the image's internal vLLM reading the regions, and the vendor's own Markdown assembly. The board posts the
    whole page to the vendor API: OXR `POST /v1/parse/sync` (multipart, `output_formats` markdown + json), Falcon
    `POST /falconocr/parse` (`{"images": [data URI], "skip_layout": false}`). Neither answers chat completions with
    a page transcription. They would need a served step with a per-model route and request (JSON or multipart) and a
    serve block that starts the image's entrypoint and waits for its health URLs (OXR: weights downloaded to
    `/models/oxr-model` first, then `/docs`; Falcon: vLLM `/health` and pipeline `/health`). Falcon's image is not known
    to have uv or Python 3.12, which `JobsPipelineExecutor` needs. The other way is to run the VLM through
    `ChatRegionStep` behind linecaster's own layout step, as for MiniCPM-OCR, but that is not the board's run.

## olmOCR-2-7B-1025-FP8 spec for ChatPageStep (2026-11-03, not yet run)

- `models/olmocr2.py` reproduces the board driver: no-anchoring v4 YAML prompt as a text part before
  the image, PNG with the longest side forced to 1288 px (LANCZOS), temperature 0.1, max_tokens 8192,
  repetition_penalty 1.05, stop `<|im_end|>`/`<|endoftext|>`; `--max-model-len 16384`, no prefix
  caching, no mm processor cache, one image per prompt; checkpoint pinned; vLLM 0.26.0 (the board's;
  Daniel's recipe has since moved to 0.29.0).
- The completion is kept verbatim; the YAML front matter is parsed into `extra["front_matter"]`.
  Dropping it from the scored text is the board's post-processing (`drop_front_matter`), left to the
  harness; `olmocr2.body()` does the same split.

## chandra-ocr-2, dots.ocr, OvisOCR2, OvisOCR3 specs for ChatPageStep (2026-11-03, not yet run)

- `models/chandra_ocr2.py`, `models/dots_ocr.py`, `models/ovis_ocr.py` reproduce the board drivers; request
  bodies (image bytes included) were checked equal to the drivers' `to_request` on JPEG/PNG/WebP, RGB and gray
  pages, and the serve flags equal the drivers' `SERVING` flags. Checkpoints pinned; vLLM 0.26.0 for all four.
- Completions verbatim. The board converts chandra's HTML layout blocks to Markdown
  (`chandra_html_to_markdown`) and drops Ovis's `<img src="images/bbox_…">` blocks (`drop_bbox_blocks`) in the
  harness's `normalize_outputs`, not in the drivers, so both stay in the harness.
- chandra: one attempt per page (the vendor client's loop retries at raised temperature are not run, as on the board).
- dots.ocr: the scored row ran with `--gpu-memory-utilization 0.6`, at most 4 pages in flight and
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (`chat_page.py --env`); 0.8 / 12 ran out of memory.
- OvisOCR3 ran on an A100 on the board; on an L4 vLLM may pick another default GDN prefill backend
  (Qwen3.5 base), which can move numerics: compare at CER level.

## MiniCPM-OCR 1.0 through ChatRegionStep (2026-11-03, forge)

Setup: `ImageFolderReader` → `LayoutStep` (`linecaster serve`, PP-DocLayoutV3 ONNX) → `ChatRegionStep(MiniCPMOCR)` →
page rows, then the SDK's own assembly (`linecaster.adapters.minicpm_ocr.assemble_markdown`, keep footnote and aside_text
as the BHL board row did) and the board lane (consolidate → normalize postproc 3 → score_dataset).
- vLLM nightly 5d35ce3 (`0.32.1rc1.dev602+g5d35ce393`, cu130 wheel from the per-commit index, torch 2.14 cu130) with
  transformers at OpenBMB's pin, in its own venv on forge (RTX 4000 SFF Ada 20 GB); `ninja` must be on PATH (the venv's
  bin) or the engine fails at startup. Serve flags from the SDK tutorial, `--gpu-memory-utilization 0.85`, DSpark
  speculative decoding with the matching draft model (mean acceptance length about 7).
- Reference: OpenBMB's SDK itself (minicpm-ocr 1.0.1 with PaddlePaddle GPU 3.3.0 and the PP-DocLayoutV3 Paddle model, the
  board image's lock) against the same server on the same pages.

| run | sample-60 CERdip / CERread / recall | tables-7 CERdip / CERread / recall | loops | wall, sample-60 |
|---|---|---|---:|---:|
| linecaster | 0.0361 / 0.0243 / 0.9379 | 0.8893 / 0.5622 / 0.9850 | 0 of 460 regions | 73 s |
| SDK | 0.0360 / 0.0241 / 0.9390 | 0.8885 / 0.5615 / 0.9843 | 0 | 77 s |

- Per book the two agree within 0.002 CERread; 39 of 60 pages give byte-identical Markdown.
- Layout: the region label sequence is the same on 52 of 60 pages, boxes within 3 px on 37. Differences come from the
  ONNX export vs PaddlePaddle, linecaster's containment suppression vs PaddleX's `filter_overlap_boxes`, and the SDK's
  `merge_blocks` (aligned text blocks merged into one composite crop), none of which is ported.
- Where a region's box matches within 1 px, the completion is identical for 320 of 339 regions; the rest differ by crop
  pixels (rounding, the polygon mask drawn by Pillow vs OpenCV) or decoding.
- No region hit its token cap (LightOnOCR-2, a page model, looped on 16 % of region crops).
- One sample-60 plate page has a single `image` region covering the page in linecaster's layout: nothing is read there.
- tables-7: the 5 content pages score CERread 0.209 (recall 0.985); the aggregate 0.562 comes from the 2 sparse pages of
  trudyrusskago, where both linecaster and the SDK read about 470 characters the GT does not transcribe (CER 74 on those pages).

## NFC step and item-level documents (2026-11-03, spark)

**NFC (`NormalizeUnicode`, after recognition).** The chain with the step against squiddleocr's goldens
(7c8a052, spark), goldens NFC-normalized (the parity scripts' new default; `--no-nfc` for raw):

| set | lines (box + words) | txt | md | raw, without NFC on the goldens |
|---|---:|---:|---:|---:|
| sample-60 | 1,560/1,560 | 60/60 | 60/60 | words 978/1,560, txt/md 27/60 |
| tables-7 | 651/651 | 7/7 | 7/7 | words 556/651, txt/md 1/7 |

Table padding in txt is unchanged by NFC: tabulate measures with `wcwidth` (a core dependency since the
post-recognition merge), which gives `a` + U+0308 and `ä` the same display width, so NFC(golden) and
linecaster's NFC output pad identically. (Without `wcwidth`, `len()` would count the combining mark and
the decomposed golden would pad one space less per such character.)

**Item-level documents (`BindItem`, `ItemExportsWriter`).** Goldens made with squiddleocr main
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
  normalized) are identical for every book and combination, and squiddleocr's own `DocumentBuilder` fed
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

## Post-recognition blocks: retyper and page composition (2026-11-03, spark)

`Typography` (squiddleocr's retyper) and `ComposePage` (squiddleocr's `DocumentBuilder`, `--text lines`)
after the in-process squiddle chain (layout, lines, assign, recognition, tables), exported with
`PageExportsWriter(suffix=".paddle", furniture=True)`, compared byte for byte with squiddleocr's goldens
(`7c8a052`, spark, `--text lines --furniture`; `tests/parity/compare_exports.py`):

| set | txt | md | docling JSON (furniture layer and version field normalized) |
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
  text is not NFC yet; normalizing it is a separate, recorded transform, not done here.)
- Recomposition (`ComposePage(text="reflow")`, squiddleocr's default document mode; `linecaster.text.recomposition` is
  squiddleocr's `reflow.py` verbatim, `uniseg` now a core dependency): no reflow goldens exist, so it was
  checked against squiddleocr's own `DocumentBuilder(text="reflow")` fed with the same retyped regions
  and lines: md, txt and docling JSON identical on all 67 pages (446 + 33 paragraphs, 234 division marks
  removed, 1 kept, 4 continuations across regions), and on the 1,000 reflow pages of the random check.
- Not ported: formula recognition (squiddleocr reads formula regions as LaTeX by default; no formula
  regions on these 67 pages; `ComposePage` takes `region.extra["formula"]` when a formula step
  provides it), paragraphs continued across pages (needs an item-level document), sections, Markdown
  dividers.

## Chat VLMs: LightOnOCR-2-1B through ChatPageStep (2026-11-03, spark)

Setup:
- Pipeline: `ImageFolderReader` → `ChatPageStep(LightOnOCR2, Served(..., max_window=48, initial_window=8), prepare_workers=4)` → `PageJsonlWriter`, run with `examples/chat_page.py`.
- Server: vLLM 0.21.0 (torch 2.11 cu130) on the same machine.
  - Flags: the spec's serve flags plus `--gpu-memory-utilization 0.22`, because the GPU was shared with `linecaster serve` and kraken-paddlex jobs.
  - The board pins vLLM 0.26.0. That version was not tested here.

Scoring: the rows were converted to the harness's input shape (id, raw, finish_reason) and scored with the frozen bhl-ocr-eval harness along the FineBooks leaderboard's path (consolidation, output normalization, scoring).

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

## HF Jobs recipe for MiniCPM-OCR 1.0 regions (not yet run on Jobs)

`recipes/hf-jobs/minicpm_regions.py`: PP-DocLayoutV3 (`ServeModels`, `linecaster serve`) → `ChatRegionStep(MiniCPMOCR)`
(`ServeChatModel`, vLLM) → page rows, both servers in each Job on one GPU.
- Image: the BHL board's MiniCPM-OCR image (vLLM nightly 5d35ce3 on `vllm/vllm-openai`, transformers at OpenBMB's pin;
  uv and Python 3.12 from the vLLM base). Its SDK venv and Paddle layout model are not used.
- vLLM runs in the image's Python; `ServeChatModel(outside_venv=True)` starts it with `VIRTUAL_ENV` unset and the uv
  environment's `bin` off `PATH`, as the board recipe does. Draft model pinned through the speculative config's
  `revision` (vLLM passes it to the draft's `ModelConfig`).
- The pipeline and the layout server run in the uv environment from `dependencies(commit, kraken=False)`: linecaster +
  linecaster-paddlex + the OpenCV stub, no kraken (the image has no git) and no lightning.
- Memory: the last block boots first, so vLLM (`--gpu-memory-utilization 0.8` by default) profiles before the layout
  server loads into the rest of the L4.
- Checked locally: `--dry-run` (plan and dill pickle of the pipeline). Not checked: the Job itself, ONNX Runtime's CUDA 13
  wheels next to the image's CUDA, DSpark draft pulled by revision rather than from a local directory.

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

- Data model (`linecaster.data`, `linecaster.data.page`): `Transcription` (regions, lines,
  words, docling, model, source), `Page`, `PageImage`, `Item`, `Text`. Decisions in
  `docs/reference/data-model.md`.
- ALTO 4.4 / PAGE 2019 / hOCR 1.2 writers and readers on lxml, schema-validated
  (`docs/reference/serialization.md`); image conversion functions (`linecaster.images.convert`: lossless WebP at full
  resolution, combined size limit).
- Blocks on datatrove: readers (image folder, HF image dataset, page rows), model steps (layout,
  lines, recognition) with an in-process or a served backend, line assignment, page writers,
  `ServeModels`.
- `linecaster serve`: a stateless model server (aiohttp) hosting several engines; blocks reach it
  through saturate.
- Engines: `backends/paddlex` (PP-DocLayoutV3 layout, PP-OCRv6 detection), `backends/kraken` (kraken's
  PP-OCRv6 recognizer), moved from squiddleocr with their history; `envs/kraken-paddlex` is the
  environment that installs both.
- Recipes: `recipes/hf-jobs/squiddle_chain.py` (datatrove `JobsPipelineExecutor`, one
  `linecaster serve` per Job), `recipes/hf-jobs/cuda_probe.py`.

### Parity with squiddleocr

The squiddle combination built from blocks (layout → lines → assign lines → recognition)
reproduces squiddleocr's outputs (main `7c8a052`, default paddle pipeline, batch 8, bf16-mixed on
CUDA) line for line on the 60-page sample of the BHL IMPACT ground truth: 1,560/1,560 lines identical
in line box, text and every word box.

| machine | in-process | served (datatrove + saturate + `linecaster serve`) |
|---|---|---|
| spark (GB10, aarch64) | 60/60 pages exact | 60/60 pages exact |
| forge (RTX 4000 SFF Ada, x86_64) | 60/60 pages exact | 60/60 pages exact |

Goldens are per machine: squiddleocr itself gives 50/67 byte-identical text files between spark and
forge (36 differing word tokens in 17 files), the usual GPU numerics. squiddleocr is run-to-run
deterministic on one machine (rerun: 60/60 identical). On the 7 table pages the recognized lines are
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

### GPUs compared (full ground truth, complete chain incl. tables, 4 tasks on HF Jobs)

Model seconds per page (datatrove stats); recognition sets the pace because the models work on
different pages at the same time. Scores are identical on all three (CER reading 0.0419–0.0420).

| GPU | layout | lines | recognition | tables |
|---|---|---|---|---|
| L4 | 0.21 | 0.18 | 0.76 | – |
| A10G | 0.21 | 0.20 | 0.72 | 0.03 |
| L40S | 0.13 | 0.12 | 0.44 | 0.02 |
| RTX 4000 SFF Ada (forge) | 0.17 | 0.12 | 0.69 | – |

With one worker per model the L40S finishes about twice as fast as an L4.

### Replicas: several copies of the recognition model on one GPU (measured, then removed)

**Decision: `linecaster serve` keeps one worker per model.** A `--replicas NAME=N` option (N copies of
a model, each with its own worker thread on the model's queue; commit 3303cd3, reverted) was measured
and removed: the gain is small, depends on the current batching, and the option suggests a scaling path
that does not exist. Measurement: Full ground truth, complete chain, 4 tasks on HF Jobs; seconds per page = the sum of the
tasks' recognition-block wall time / 2,165 (the chain runs at the pace of recognition). Lines, words and
tables are identical for every N (2,165/2,165 pages).

| GPU | 1 replica | 2 replicas | 3 replicas |
|---|---|---|---|
| L4 | 0.819 | 0.756 (−7.6 %) | – |
| L40S | 0.452 | 0.416 (−7.9 %) | 0.405 (−10.4 %) |
| RTX 4000 SFF Ada (forge, 310 pages) | 0.714 | 0.686 (−4 %) | 0.671 (−6 %) |

(L4 1 and 2 replicas from the same commit; L40S 1 replica from the earlier run of the same chain.)
Recognition is GPU-bound, not GIL-bound: per-request time roughly doubles with two replicas (L4 0.81 →
1.49 s), and on forge kraken in two separate processes reaches the same total throughput as one (80
pages in 52 s alone; 2 × 80 pages in 102 s side by side). Replicas only fill the gaps between a page's
batches. The lever left is the recognizer's GPU efficiency (8 lines per forward pass in bf16), which
changes numerics if the batching changes.
Revisit only with a server that runs model copies on separate CUDA streams or processes, or after a
change that makes recognition much faster (then layout, at about 0.2 s/page, sets the pace).

### Region recognition with a page model

`ChatRegionStep` with PP-DocLayoutV3 regions and LightOnOCR-2-1B (a page-trained VLM): the model loops
to its token limit on 68 of 418 region crops of the 60-page sample (page headers 30, footers 15,
footnotes 15); with those regions left empty the reading CER is 0.0402 against 0.0285 for the same
model on whole pages. The block works; region reading wants a region-trained model or tighter
per-region limits.

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

- Port squiddleocr's post-recognition steps (retyper, reflow, page composition into `docling`, tables,
  formulas) as blocks.
- `/v1/chat/completions` preset route for OpenAI clients.
- Deterministic algorithms flag: not set (squiddleocr does not set it and is run-to-run deterministic);
  cuDNN autotuning is off explicitly.

## Per-page files and item texts in one run (2026-11-03, spark)

`examples/squiddle_chain.py BOOKS OUT --item-from-parent --files OUT/files --texts OUT/texts`
in-process on sample-60 (images grouped by book in subfolders, 6 books): 1 m 45 s; page rows, 360
per-page files (`<item>/<page>.hocr|.alto.xml|.page.xml|.txt|.md|.json`) and 18 item texts.

- All 60 ALTO and 60 PAGE files validate against the schemas in `tests/schemas/`; the 60 hOCR files
  read back with `from_hocr` (1,560 lines, as recognized).
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

## Board models as chat specs: validation on the 60-page sample (2026-11-03)

Each spec ran through `recipes/hf-jobs/chat_page.py` (ChatPageStep + ServeChatModel in one HF Job) on the
sample-60 pages, and was scored the board's way (consolidate → `normalize_outputs` postproc 3 →
`score_dataset`) next to the board's own outputs for the same 60 pages (bhl-ocr-eval's consolidated rows).
CER reading, linecaster vs board:

| Model | GPU | linecaster | board |
|---|---|---|---|
| rednote-hilab/dots.ocr | L4 | 0.0170 | 0.0170 |
| datalab-to/chandra-ocr-2 | L4 | 0.0190 | 0.0197 |
| baidu/Unlimited-OCR-2 (SGLang) | L4 | 0.0251 | 0.0262 |
| ATH-MaaS/OvisOCR2 | L4 | 0.0276 | 0.0274 |
| ATH-MaaS/OvisOCR3 | L4 | 0.0299 | 0.0325 |
| PaddlePaddle/PaddleOCR-VL-1.6 | L4 | 0.0309 | 0.0309 |
| Qwen/Qwen3.5-9B | L40S | 0.0358 | 0.0356 |
| zai-org/GLM-OCR | L4 | 0.0368 | 0.0360 |
| nvidia/Nemotron-3.5-Parse | H200 | 0.0403 | 0.0454 |
| baidu/Unlimited-OCR | L4 | 0.0429 | 0.0449 |
| baidu/Qianfan-OCR | L4 | 0.0482 | 0.0491 |
| deepseek-ai/DeepSeek-OCR | L4 | 0.0551 | 0.0543 |
| deepseek-ai/DeepSeek-OCR-2 | L4 | 0.0576 | 0.0628 |
| ds4sd/SmolDocling-256M-preview | L4 | 0.0643 | 0.0556 |

- Greedy decoding with identical requests reproduces the board exactly (PaddleOCR-VL-1.6, dots.ocr); the
  others differ within sampling and GPU variation (CIs on 60 pages are about ±0.02).
- SmolDocling is the largest gap (3 vs 5 truncated pages); the board copy compared against may not be the
  scored run (see the SmolDocling section above). Worth a second look.
- Not ported: indra-ocr (in-process ONNX package, not a server), OXR-1.0 and Falcon-OCR (vendor parse
  APIs, not chat completions).

## Manifests through pybookget: IIIF (2026-11-04) and METS (2026-11-05), spark

`ManifestReader` (before 2026-11-05 `IIIFManifestReader`) and `pipelines/harvest.py` checked against public
servers with linecaster's user agent, 2 requests per second, 3 pages per item:

- Wellcome Collection (`presentation/v3/b18035723`): a Presentation 3 manifest whose image service is Image
  API 2, so the request is `full/full` (not `max`); 36 canvases. Its canvases link ALTO (`seeAlso`), read as
  `ocr_original` (35 and 5 lines; none on the cover). Canvas files skip a number (`_0001`, `_0003`, `_0004`):
  pages count canvases, and each page's image and ALTO come from the same canvas. On 2026-11-04 a harvest of 3
  pages, then the squiddle recipe on `--rows`.
- Bodleian (a Presentation 2 manifest, 84 canvases): first image fetched at full size; the manifest has no
  `license`, so `rights` is empty.
- Heidelberg University Library (`diglitData/mets/cpg389.xml`, a manuscript, 694 pages): METS with `MAX`,
  `DEFAULT`, `DEFAULTPLUS`, `MIN`, `THUMBS`, `INTROIMAGE` groups; `MAX` taken; page labels from the METS
  ("Vorderdeckel", "Vorderspiegel 1"); no `FULLTEXT`. Title and rights (Public Domain Mark) from MODS.
- SLUB Dresden (OAI-PMH `GetRecord`, `metadataPrefix=mets`, a print of 472 pages): `ORIGINAL` taken, the
  full-size JPEGs (2848 × 4288); no `FULLTEXT` in this record.

Open: the per-task rate limit is the only limit (datatrove keeps no state between tasks); a run against one
server sets `--workers` × `--rate-limit` to what that server accepts.

## Tracing: overhead and storage (2026-11-05, GB10)

The squiddle recipe on the 60-page sample, one task, in-process and served (`--backend served`: the task starts
`linecaster serve`), each configuration twice. Untraced is the commit before tracing (`e4b8d1d`); traced at
`--trace-sample` 0, 0.01 and 1. Seconds per page from the reader's first file to datatrove's "Processing done"
(warm-ups and server start left out):

| | untraced | sample 0 | sample 0.01 | sample 1 |
|---|---|---|---|---|
| in-process | 1.092, 1.088 | 1.092, 1.084 | 1.087, 1.078 | 1.091, 1.087, 1.091 |
| served | 0.811, 0.810 | 0.812, 0.811 | 0.815, 0.817 | 0.814, 0.818, 0.812 |

- The differences are within the run-to-run variation. The cost alone, on CPU: the modular pipeline with fake
  engines (ten blocks with the rejects writer) on 2,000 small pages, best of three: 0.526 ms per page untraced,
  +0.20 ms at sample 0 and 0.01 (every page's spans are recorded and held until it is done), +0.50 ms at sample 1.
- Storage (gzipped OTLP JSON lines): the task spans take about 1.05 KB per task in-process, 1.25 KB served; a traced
  page about 0.5 KB in-process (31,340 bytes for 60 pages at sample 1) and 1.7 KB served, pipeline and server
  together (102,518 bytes). Per 1,000 pages: sample 0, only the task spans (and 0.5 KB per failed page); sample
  0.01, about 5 KB in-process and 17 KB served; sample 1, about 0.5 MB in-process and 1.7 MB served.
- Memory of the buffer for unsampled pages: 3.3 KB per held span (tracemalloc), 39 KB for a page of twelve blocks.
- `linecaster serve` lost its last spans at first: saturate's `Engine` signals the server's process group and
  `uv run` passes the signal on, so the server got SIGTERM twice and the second cut its graceful end short; and
  PaddlePaddle puts its own SIGTERM handler in place at its first operation ("FatalError: Termination signal"),
  which ends the process at once. The server now ends on the first signal only and sets its handlers again after
  the engines load and after each model's first call; with that every request of the served run has its
  `linecaster.serve.*` spans (60 of 60 per model).
- vLLM 0.20.0 continues a `traceparent` from request headers when started with `--otlp-traces-endpoint`
  (protocol from `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL`, default gRPC); saturate 0.3.0 sends the same headers with
  every request, so a chat request carries no page context and vLLM's spans are traces of their own. Not run
  against vLLM or an OTLP collector here.
- Parity: the squiddle recipe in-process (sample 0.01) and served (sample 1) reproduce the goldens (60 of 60 pages
  exact).
