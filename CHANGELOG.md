# Changelog

All notable changes to linecaster. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
each release lists upgrade notes first, then additions, changes, deprecations, removals and fixes. Versions follow
the tags; the first is `v0.1.0`.

## Unreleased

### Upgrade notes

The refactoring in `docs/plan/refactoring.md` lands in phases; each phase's renames are listed here. There are no
compatibility aliases: old imports, flags and ids fail.

**Phase 1: layout and names**

- Packages: `linecaster.transcription`, `linecaster.page` → `linecaster.data` (data model) and `linecaster.formats`
  (ALTO, PAGE, hOCR; `formats.docling` was `linecaster.document`); `text.py`, `unicode.py`, `reflow.py`,
  `retyper.py` → `linecaster.text.variants`, `.unicode`, `.recomposition`, `.typography`; `images.py`, `plots.py` →
  `linecaster.images`; `run`, `jobs`, `ray_executor`, `provenance` → `linecaster.runtime.*` (`run.rows()` →
  `run.pages()`); `linecaster.models` → `linecaster.adapters`; `blocks/http.py` → `linecaster.net`; blocks by
  family under `linecaster.blocks.<family>` (old modules `filters`, `media`, `models`, `serve`, `texts`,
  `document`, `readers`, `writers` are gone); `specs/` → `docs/reference/`.
- Blocks: `PageStep` → `PageBlock`, `ModelStep` → `ModelBlock`, `WorkingImages` → `ImageConverter`, `AttachImage`
  → `ImageFetcher`, `LayoutStep` → `LayoutDetector`, `LinesStep` → `LineDetector`, `AssignLinesToRegions` →
  `LineAssigner`, `RecognitionStep` → `LineRecognizer`, `ChatRegionStep` → `RegionRecognizer`, `ChatPageStep` →
  `PageRecognizer`, `TablesStep` → `TableRecognizer`, `FormulasStep` → `FormulaRecognizer`, `NormalizeUnicode` →
  `UnicodeNormalizer`, `Typography` → `Typographer`, `ComposePage` → `Composer`, `ValidatePages` → `PageValidator`,
  `RejectSink` → `RejectWriter`, `RecipeStamp` → `RecipeStamper`, `ServeModels` → `ModelServer`, `ServeChatModel`
  → `ChatModelServer`, `PageRowReader` → `PageRecordReader`; writers: `PageFilesWriter` + `PageExportsWriter` →
  `PageFileWriter` (`text_fallback=False` is the old `PageExportsWriter`), `ItemExportsWriter` →
  `ItemDocumentWriter`, `ItemTextJsonlWriter` + `ItemTextFilesWriter` → `ItemTextWriter(format=...)`. Datatrove
  display names changed with them (stats and logs).
- Engines: `…Model` → `…Engine` (`KrakenRecognitionEngine`, `PaddleLayoutEngine`, ...); ids unchanged. Adapters:
  `ChatModel` → `ChatAdapter`, each VLM adapter `X` → `XAdapter`.
- Pipeline scripts: `transcribe_chain.py` → `transcribe_modular.py`; ids `chain.v1` → `transcribe_modular.v1`,
  `vlm.v1` → `transcribe_vlm.v1`, new `harvest.v1`, `bind.v1`.
- Flags: `--recognizer` → `--recognition`; `--vlm`, `--vlm-endpoint` → `--recognition`, `--recognition-endpoint`;
  `--texts` → `--item-texts`; `--exports DIR` → `--files DIR --formats md,txt,json --naming squiddleocr
  --furniture`; `--rows` → `--pages`.
- Stored output: the default transcription `ocr` → `ocr_new`; page records in `OUT/rows/` → `OUT/pages/`; item text
  fidelity `normalised` → `normalized`; typography measurement `levelled` → `leveled`. Page records written before
  phase 1 keep `ocr`; read them with `transcription="ocr"`.
- Catalog: no step `page` (page presets are step `recognition`, unit `page`, under `presets/recognition/`); entries
  are `<id>.yaml` with prose in `<id>.md`; YAML is read as YAML 1.2 with `ruamel.yaml` (replaces PyYAML); lock format
  `linecaster.lock/2`. Edition numbers are unchanged; 20 hashes were recomputed (the page presets and `squiddle@1`),
  so files stamped by a recipe carry the new hash; old hashes still resolve (`previous_sha256`).
- American spelling throughout (e.g. `normalize`, `NORMALIZE_MAP`, `quantize_confidence`, `COLORS`).

**Phase 2: contracts and the builder**

- Pipeline scripts check their pipeline before they launch: a pipeline whose contracts do not fit exits with code 2
  and lists every problem. Own blocks without a `contract()` pass unchecked.
- With `--tasks` over 1, a binder after the page blocks (`--item-texts`) cuts the run into two stages: page records
  in item shards (`OUT/pages/<shard>/`), then the item stage; their logs are `OUT/logs/pages/` and
  `OUT/logs/items/`. One stage logs to `OUT/logs/` as before.
- `--dry-run` prints the plan under `plan` and the Mermaid graph after the JSON.

### Added

- Block contracts (`contract()`, `Part`, `Contract`, `PARTS`), the builder (`linecaster.runtime.builder`: `build`,
  `Plan`, checks, branches with `when=`/`group=`, composites, stages, `run_pages`), observers
  (`linecaster.runtime.observers`), the composite `ModularTranscriber`, the error classes (`linecaster.errors`),
  partial runs (`--until`, `--after`, `--tap-after`), `--page IMAGE` and `linecaster page`;
  `docs/reference/pipelines.md`.
- `docs/reference/glossary.md` and `docs/reference/conventions.md`.
