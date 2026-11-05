# Refactoring plan (working document)

The plan for the restructuring agreed on 2026-11-05. This file is removed when the refactoring is done; its rename
table then lives in `CHANGELOG.md`'s upgrade notes. Terms are the [glossary](../reference/glossary.md)'s, rules the
[conventions](../reference/conventions.md)'.

## Decisions to review (phase 0)

| # | Decision | Proposal |
|---|---|---|
| D1 | The default name of linecaster's own transcription | `ocr` → **`ocr_new`**, next to `ocr_original` (as the EBDC page row and `linecaster.page` already name them) |
| D2 | The catalog step `page` (a VLM reads the whole page) | merged into **`recognition` with unit `page`**: there is no step `page`; `presets/page/` moves to `presets/recognition/`; in `transcribe_vlm.py` the slot `vlm` and flag `--vlm` become `recognition` / `--recognition` |
| D3 | Released editions when the catalog changes format (YAML + Markdown, the hash over YAML only, renamed fields and steps, new pipeline ids) | one **catalog migration** in phase 1: a lock format `linecaster.lock/2`; every edition keeps its number, its hash is recomputed under the new format, and the old hash stays in the lock so existing run records still resolve. Allowed only for changes that keep behavior; anything else is a new edition. This also moves `squiddle@1` to `transcribe_modular.v1` without a `squiddle@2` |
| D4 | Writers that overlap | `PageFilesWriter` + `PageExportsWriter` → **`PageFileWriter`** (one writer for every per-page format, with a naming option for squiddleocr's names); `ItemExportsWriter` → **`ItemDocumentWriter`**; `ItemTextJsonlWriter` + `ItemTextFilesWriter` → **`ItemTextWriter`** (`format="jsonl" \| "files"`) |
| D5 | `--text lines\|reflow` and `--texts DIR` (one letter apart, unrelated) | `--text` becomes the slot **`--recomposition PRESET`** (none: the page stays as laid out); `--texts DIR` becomes **`--item-texts DIR`** |
| D6 | "page row" and "record" (the stored and the in-memory page) next to `Line.row` (the lines side by side at one height) | **page record** for the page, in memory and on disk: `OUT/rows/` → `OUT/pages/`, `PageRowReader` → `PageRecordReader`, `--rows` → `--pages`; **row** only means the visual row, and `Line.row` keeps its name |
| D7 | Where built-in engines live | **`linecaster.engines`** (normalization, typography, recomposition, composition, image, chat); the repository folder `engines/` keeps the engine packages |
| D8 | "Connector" | dropped; inputs are **readers** |

## Phases

Each phase is one branch with tidy commits, ends with squiddleocr's goldens exact and the full suite green, and
brings squiddleocr, the EBDC pilot pipeline and the FineBooks pipeline along. Everything stays in this repository;
splitting engines into their own repository is not part of this refactoring.

### Phase 0: decisions on paper

The glossary, the conventions, `CHANGELOG.md`, this plan with its rename table. Reviewed before code changes.

### Phase 1: renames, layout, catalog format (outputs unchanged)

1. The layout below, with an import rule checked by a test.
2. Blocks as role nouns; engine classes `*Model` → `*Engine`; adapters; modules (tables below).
3. Pipeline scripts and ids; slots and flags; the step vocabulary (D2, D5).
4. American spelling throughout, except copied upstream cards.
5. The catalog as YAML with Markdown sidecars; schemas in `schemas/`; `ruamel.yaml`; the validator; the
   migration (D3).
6. Stale fixes: `--layout-model` in `run.py`; the `blocks.iiif` comment in `pyproject.toml`; the documented but
   nonexistent `linecaster.catalog` entry-point group; CLAUDE.md's description of the engine interface; the README
   anchors.

### Phase 2: tracing, contracts, builder

1. Tracing with OpenTelemetry (conventions, "Tracing"), with the observers it hangs off; measured cost and storage;
   `linecaster traces`.
2. Block contracts; the two block shapes (per-unit transform, stream transform), with a test that only readers
   and writers know about tasks.
3. The builder: graph, checks, `when=` branches with a join check, composite blocks, drawing in `--dry-run`, cutting
   into stages at unit changes.
4. Partial runs (`--until`, `--after`, `--tap-after`), `run_pages()`, `linecaster page IMAGE`.
5. `warm_up()`; per-page failures in-process with `rejects/` and an error budget; failed pages passed on at once;
   the error hierarchy; no `SystemExit` in library code.
6. `to_dict()` on every block; the run record with `pipeline_sha256`; resume refused into a different pipeline;
   expanded recipe pipelines in the lock.
7. Secrets as references (`EnvVar`); the logging convention.

### Phase 3: rule-based steps, recomposition, binding

1. Catalog steps `image`, `normalization`, `typography`, `recomposition`, `composition`, with built-in engines and
   presets; thresholds as options; strategies declare their scripts; presets map scripts to strategies.
2. Data model (new schema version): `Transcription.paragraphs`; `StepInfo` and `Transcription.steps`; the
   measurements vocabulary.
3. One recomposition: `reflow.py` as `recomposition.unicode.v1` with a text-only fallback; `text.py`'s
   `join_lines` removed; `Binder` + `Recomposer`/`Composer` at the item level + the item writers replace
   `BindItem` and `ItemTexts`; `bind.py` writes `texts/<variant>/` and `documents/<format>/`; the `Splitter`.
4. Goldens exact; the change in the readable texts measured on the BHL sample and recorded in NOTES.md.

### Phase 4: backends and families

VLMs as the `chat` backend of `RegionRecognizer`/`PageRecognizer`; `TranscriptionConverter`; `SingleRegionLayout`
as the engine `layout.single-region.v1`; skeletons for IIIF Collections (via pybookget) and PDF items
(`PdfReader`, extra `[pypdfium2]`).

### Phase 5: docs

Generated block pages per family (contract, unit, backends, options, source, derived position, diagram); generated
README tables; tests for current docs and the README snippet; the docstring standard; CLAUDE.md as rules only;
the compatibility statement; evidence tables with hardware and backend; an MkDocs Material site with `llms.txt`.

### Phase 6: tests and engine hygiene

`linecaster.testing` (engine conformance, block contracts, fake CPU engines); pytest markers; per-engine tests;
CPU CI; engines kept independent of core internals, with versions of their own and install hints; a Ray Data
spike.

After phase 3 or at the end: the tag `v0.1.0`, then versioned docs.

## Rename table

### Blocks

| Today | New | Family | Phase |
|---|---|---|---|
| `PageStep` | `PageBlock` | base | 1 |
| `ModelStep` | `ModelBlock` | base | 1 |
| `WorkingImages` | `ImageConverter` (preset `working-image@1` in phase 3) | conversion | 1 |
| `AttachImage` | `ImageFetcher` | conversion | 1 |
| `LayoutStep` | `LayoutDetector` | layout | 1 |
| `SingleRegionLayout` | `LayoutDetector` with the engine `layout.single-region.v1` | layout | 4 |
| `LinesStep` | `LineDetector` | lines | 1 |
| `AssignLinesToRegions` | `LineAssigner` | lines | 1 |
| `RecognitionStep` | `LineRecognizer` | recognition | 1 |
| `ChatRegionStep` | `RegionRecognizer` (backend `chat` in phase 4) | recognition | 1 |
| `ChatPageStep` | `PageRecognizer` (backend `chat` in phase 4) | recognition | 1 |
| `TablesStep` | `TableRecognizer` | recognition | 1 |
| `FormulasStep` | `FormulaRecognizer` | recognition | 1 |
| — | `TranscriptionConverter` | conversion | 4 |
| `NormalizeUnicode` | `UnicodeNormalizer` | text | 1 |
| (inside `text.py`) | `CharacterNormalizer` | text | 3 |
| `Typography` | `Typographer` | composition | 1 |
| (inside `document.py`, `text.py`) | `Recomposer` | composition | 3 |
| `ComposePage` | `Composer` | composition | 1 |
| `BindItem`, `ItemTexts` | `Binder` (+ `Recomposer`, `Composer` at the item level, + item writers) | binding | 3 |
| — | `Splitter` | binding | 3 |
| `ValidatePages` | `PageValidator` | validation | 1 |
| `RejectSink` | `RejectWriter` | writers | 1 |
| `RecipeStamp` | `RecipeStamper` | validation | 1 |
| `ServeModels` | `ModelServer` | servers | 1 |
| `ServeChatModel` | `ChatModelServer` | servers | 1 |
| `PageFilesWriter`, `PageExportsWriter` | `PageFileWriter` (D4) | writers | 1 |
| `ItemExportsWriter` | `ItemDocumentWriter` (D4) | writers | 1 |
| `ItemTextJsonlWriter`, `ItemTextFilesWriter` | `ItemTextWriter` (D4) | writers | 1 |
| `PageRowReader` | `PageRecordReader` (D6) | readers | 1 |
| other readers, `PageJsonlWriter`, `PageParquetWriter`, `ImageFilesWriter` | unchanged | readers, writers | |
| — | `ModularTranscriber` (composite) | composites | 2 |
| — | `PdfReader` (skeleton) | readers | 4 |

### Engines, adapters

| Today | New |
|---|---|
| `KrakenRecognitionModel`, `PaddleLayoutModel`, `PaddleLineModel`, `PaddleRecognitionModel`, `PaddleTableModel`, `PaddleFormulaModel`, `TesseractRecognitionModel` | `…Engine` (ids unchanged) |
| `linecaster.models` | `linecaster.adapters` |
| `ChatModel`, `ChatPreset` | `ChatAdapter`, `ChatPreset` |
| `ChandraOCR`, `DeepSeekOCR`, `Dots`, … (`ADAPTERS`) | `…Adapter`; `ADAPTERS` stays the one registry |

### Pipeline scripts, ids, slots, flags

| Today | New |
|---|---|
| `pipelines/transcribe_chain.py`, id `chain.v1` | `pipelines/transcribe_modular.py`, id `transcribe_modular.v1` |
| `pipelines/transcribe_vlm.py`, id `vlm.v1` | id `transcribe_vlm.v1`; slot `vlm` → `recognition` (D2) |
| `pipelines/harvest.py`, no id | id `harvest.v1` |
| `pipelines/bind.py`, no id | id `bind.v1` |
| `--recognizer` | `--recognition` |
| `--vlm`, `--vlm-endpoint` | `--recognition`, `--recognition-endpoint` (D2) |
| `--text lines\|reflow` | `--recomposition PRESET` (D5) |
| `--texts DIR` | `--item-texts DIR` (D5) |
| `--files`, `--exports` | `--files` with every per-page format (D4) |
| `--rows DIR`, `OUT/rows/` | `--pages DIR`, `OUT/pages/` (D6) |

### Catalog

| Today | New |
|---|---|
| `STEPS = layout, lines, recognition, tables, formulas, page` | `layout, lines, recognition, tables, formulas, image, normalization, typography, recomposition, composition` (D2) |
| `presets/page/` | `presets/recognition/` (D2) |
| `<id>.md` with YAML front matter | `<id>.yaml` + `<id>.md` |
| `models/<id>/model.md` | `models/<id>/model.yaml` + `model.md` |
| `catalog.lock` | lock format `linecaster.lock/2` (D3) |
| "component" (the umbrella word) | "catalog entry" |
| "catalogue" | "catalog" |

### Data model

| Today | New | Phase |
|---|---|---|
| `ModelInfo` | `StepInfo` | 3 |
| `Transcription.model` | `Transcription.steps` | 3 |
| — | `Transcription.paragraphs` (`Paragraph`) | 3 |
| `measurements` (free keys) | a fixed vocabulary | 3 |
| transcription name `ocr` | `ocr_new` (D1) | 1 |

### Modules

| Today | New |
|---|---|
| `transcription/model.py`, `page.py`, `geometry/` | `data/transcription.py`, `data/page.py`, `data/geometry/` |
| `transcription/alto.py`, `pagexml.py`, `hocr.py`, `_xml.py`, `_provenance.py` | `formats/` |
| `document.py` (DoclingDocument building and exports) | `formats/docling.py` (exports); the building moves to `engines/composition.py` (phase 3) |
| `text.py`, `unicode.py`, `reflow.py`, `retyper.py` | `text/variants.py`, `text/unicode.py`, `text/recomposition.py`, `text/typography.py` |
| `images.py`, `plots.py` | `images/convert.py`, `images/plots.py` |
| `blocks/*.py` (17 flat modules) | `blocks/<family>/` |
| `blocks/http.py` | `net/http.py` |
| `backends/` | `backends/in_process.py`, `served.py`, `chat.py` |
| `models/` | `adapters/` |
| `run.py`, `jobs.py`, `ray_executor.py`, `provenance.py` | `runtime/` |
| — | `engines/` (built-in), `tracing/`, `testing/`, `runtime/builder.py` |
| `specs/` | `docs/reference/` |
| `tests/test_*.py` (flat) | `tests/` mirroring `src/linecaster/` |

### Terms in prose

| Today | New |
|---|---|
| chain, the chain pipeline | the modular pipeline (`transcribe_modular`) |
| document assembly, reflow | composition, recomposition |
| text version | text variant |
| axes | dimensions |
| book (generic) | item |
| page row, record | page record (D6) |
| model (for a page preset, an engine class or an adapter) | page preset, engine, adapter |
| connector | reader |
| British spelling | American spelling |
