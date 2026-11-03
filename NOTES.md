# NOTES

Measurements, decisions and open questions, newest first.

## One recipe per pipeline (2026-11-03, spark)

The scripts had made the environments self-contained, but the pipelines were still copied once per machine: the
squiddle chain three times (`examples/`, `recipes/ray/`, `recipes/hf-jobs/`), its model list four times (with
`examples/squiddle_models.json`), the chat page and region pipelines twice each, the kraken + PaddleX metadata block
twice. Now:
- `recipes/chain.py`: layout → lines → assignment → kraken, PaddleX PP-OCRv6 or Tesseract (`--recognizer`) → NFC →
  tables → formulas → typography → document, with --files/--exports/--texts. One environment holds all three
  engines (torch + PaddleX + tesserocr resolve together), so the PaddleX + Tesseract combination needs no script of
  its own. The HF Jobs chain now runs NFC, typography and document assembly too (it wrote raw page rows before).
- `recipes/vlm.py`: a chat VLM per page, or per PP-DocLayoutV3 region with `--regions` (MiniCPM-OCR is one model it
  takes; its DSpark draft comes from the spec, its image from the recipe's table of validated images).
- `linecaster.run` gives both the same command line: `--on local|ray|hf-jobs`, `--backend in-process|served`
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
- HF Jobs: a LightOnOCR page smoke was launched; MiniCPM regions was cancelled while it waited for an L4.

## Self-contained uv scripts instead of environment folders (2026-11-03, spark)

`envs/kraken-paddlex` and `envs/paddlex-tesseract` are gone. Every example, recipe and server is a uv script
with inline metadata (PEP 723) and a `<script>.py.lock` next to it:
- `servers/kraken-paddlex.py`, `servers/paddlex-tesseract.py`: `linecaster serve` with one engine combination.
  `ServeModels(script=...)` starts one with `uv run --script`; `linecaster.jobs.dependencies(commit, engines)` reads
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

## More line recognisers: PaddleX PP-OCRv6 and Tesseract (2026-11-03, spark)

Two more engines for `RecognitionStep`, next to kraken:
- `linecaster_paddlex:PaddleRecognitionModel`: PaddleOCR's own PP-OCRv6 recognisers (`PP-OCRv6_{tiny,small,medium}_rec`)
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
assignment → *recogniser* → NFC → tables → typography → document → Markdown), in-process, one task, scored as-is
(no postproc) with the frozen bhl-ocr-eval harness (`score_dataset`, sample-60 at 41ff3475). Wall includes model loading.

| recogniser | CERdip | CERread | recall | wall, 60 pages |
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
| `--layout none` (the page is one text region) | missing, built | `SingleRegionLayout` (`blocks/layout.py`) |
| PP-OCRv6 detection, `--det-model`, `--unclip-ratio` | already in linecaster | `LinesStep` + `PaddleLineModel(model_name, unclip_ratio)` |
| lines into regions, orphan rows, pictures skipped | already in linecaster | `AssignLinesToRegions` (`formulas_separately=False` without formulas) |
| kraken recognition, `-m tiny/small/medium/path`, `--batch-size`, `--precision` | already in linecaster | `RecognitionStep` + `KrakenRecognitionModel` |
| `--device` | already in linecaster | `device` of every engine model (in-process; the server's otherwise) |
| `--rtl` | already in linecaster | `KrakenRecognitionModel(text_direction=...)`, `AssembleDocument(rtl=)`, `AssembleItemDocument(rtl=)` |
| `--tables` | already in linecaster | `TablesStep` + `PaddleTableModel` |
| `--formulas`, `--formula-model` | already in linecaster | `FormulasStep` + `PaddleFormulaModel` (29/29 formulas identical, 82e2e7b) |
| `--typography` (heading levels, demotion, headline split, drop capitals, uncertain page numbers) | already in linecaster | `Typography` |
| NFC of the as-written text | linecaster's choice (0.3 kept kraken's decomposed text) | `NormalizeUnicode` |
| `--text reflow/lines` | already in linecaster | `AssembleDocument(text=)`, `AssembleItemDocument(text=)` |
| `--sections` | per item already; per page missing, built | `AssembleItemDocument(sections=)`; `AssembleDocument(sections=)` |
| `--dividers` | per item already; per page missing, built | `AssembleDocument` keeps the item → region map (`extra["docling_region_of"]`); `dividers` on `PageFilesWriter` / `PageExportsWriter` |
| `--furniture` | already in linecaster | `furniture` on the export writers (the items always sit in Docling's furniture layer) |
| `--per-document` | already in linecaster | `AssembleItemDocument` + `ItemExportsWriter`; `ImageFolderReader(item_id=, sequence=)` (built) puts a run's pages into one item in name order |
| `-f md, txt, json` | already in linecaster | `PageFilesWriter`, `PageExportsWriter`, `ItemExportsWriter`; JSON now formatted as docling's `save_as_json` |
| `-f html, doclang` | missing, built | `linecaster.document.export` / `to_html` / `to_doclang` in all three writers |
| `-f hocr, alto, page` | already in linecaster | linecaster's lxml serialisers (not kraken's, by design) |
| `--detail word` | already in linecaster | the serialisers' default (words are the finest level) |
| `--detail line` | missing, built | `PageFilesWriter(detail="line")` (a word-less copy to the serialisers) |
| `--detail glyph` (0.3's default) | not in linecaster, by design | no glyph level in the data model; squiddle's default becomes `word` |
| `--plots` | missing, built | `linecaster.plots.plot_layout`, `PageFilesWriter` format `plot` (`<page>.layout.jpg`) |
| processing settings in ALTO | already in linecaster | `ModelInfo` per step → ALTO `Processing` |
| output naming `<name>.<suffix>.<ext>`, next to the image unless `-o`; per-document stem (folder name, file stem or `document`); `--suffix`; format `auto` = md | squiddle-specific | squiddleocr `cli.py` (writer `suffix=`, a `PageFilesWriter` subclass for "next to the image") |
| status lines (typography and reflow counts), failed pages listed at the end | squiddle-specific | datatrove's stats instead; an in-process exception stops the task (served errors are recorded per page) |

**Parity.** `squiddle ocr` (squiddleocr 0.4, now composed of these blocks) against `squiddle legacy ocr` on the same
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
  it serialises; 0.3 saved its JSON from that same document, so with `doclang` before `json` in `-f` 0.3's
  charspans changed (reflow paragraphs: every row's span restarted at 0). linecaster writes JSON from the
  stored document and `to_doclang` works on a copy, so the order of formats does not matter; the parity runs
  list json before doclang.
- **hocr, alto, page** are linecaster's serialisers, so the files differ by design; read back with linecaster's
  readers, every line on every page has the same text, line box and word boxes (words: NFC text and box),
  with three conventions of kraken's serialiser set aside: kraken writes whitespace runs as words of their
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
    orientation, script classifier, line recognisers, layout and reading order). It would need an engine package
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
  bodies (image bytes included) were checked equal to the drivers' `to_request` on JPEG/PNG/WebP, RGB and grey
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
page rows, then the SDK's own assembly (`linecaster.models.minicpm_ocr.assemble_markdown`, keep footnote and aside_text
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
batches. The lever left is the recogniser's GPU efficiency (8 lines per forward pass in bf16), which
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
