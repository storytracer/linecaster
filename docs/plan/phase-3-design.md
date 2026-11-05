# Phase 3 design (working document)

Interfaces for phase 3 of [the plan](refactoring.md): rule-based steps as catalog engines, recomposition as a role of
its own, binding. Removed with the plan when the refactoring is done; what remains true moves to
`docs/reference/`. Terms are the [glossary](../reference/glossary.md)'s.

## Parity is the constraint

Every output that exists today must come out byte-identical after this phase, given the equivalent presets:

- the squiddle recipe's page outputs (`compare_goldens.py`: 60/60 pages, 1560/1560 lines) and squiddleocr's goldens
  test (`SQUIDDLE_GOLDENS=1 uv run pytest tests/test_chain.py -k goldens` in squiddleocr);
- `Composer(text="reflow")` and `Composer(text="lines")` documents and their exports (md, txt, html, doclang, json)
  per page;
- `BindItem` item documents (reflow and lines, with sections, dividers, furniture) and `ItemTexts` text variants.

The only planned output changes: (a) the provenance lists step entries for the rule-based steps too (ALTO/PAGE
processing steps, transcription JSON), (b) the readable text variants once they are made from the recomposition
instead of `text.py`'s simpler flow (measured, §5), (c) the page record schema version.

## 1. Data model (page record schema `linecaster.page/2`)

- `ModelInfo` → `StepInfo`, `Transcription.model` → `Transcription.steps`; `StepInfo` gains `engine: str | None`
  (the engine's code id). Rule-based steps add a `StepInfo` like model steps (step, engine, preset and its sha256,
  settings, measurements).
- `Paragraph` (new), `Transcription.paragraphs: list[Paragraph]`: `id`, `region_id`, the line spans it consists of
  (enough for the Composer to build exactly the provenance boxes the DocumentBuilder builds today), `text` (flowed,
  as-written fidelity), `normalized` (set by the CharacterNormalizer, else None), `continues_from` / `continues`
  (across regions and, at the item level, pages), and `decisions` (each removed division mark, kept hyphen,
  paragraph break and continuation with its reason, in a small fixed vocabulary).
- `Line.normalized: str | None` (set by the CharacterNormalizer).
- Measurements: a fixed vocabulary (`linecaster.data.MEASUREMENTS`: key → meaning), covering today's keys
  (`seconds`, `datetime`, `device`, `prompt_tokens`, `completion_tokens`, `finish_reason` with a literal set,
  the typography counts `leveled`, `demoted`, `split`, `drop_capitals`, `numbers_dropped`, the recomposition counts
  `continuations`, `marks_removed`, ...); a test fails on an unknown key written by linecaster code.
- `PageRecordReader` upgrades `linecaster.page/1` records (`model` → `steps`) and pre-phase-1 ones, as today.
- The serializers (ALTO, PAGE, hOCR) read `steps`; `from_*` produce it. The JSON schemas of the data model, if
  published, are regenerated.

## 2. Rule-based steps in the catalog

- New catalog steps: `image`, `normalization`, `typography`, `recomposition`, `composition` (add to `STEPS`, the
  docs generator, `OCRD_STEPS` where a mapping exists).
- Built-in engines in `linecaster.engines` (pure Python, in-process only; registered in `BUILTIN_ENGINES`):
  `image.webp-lossless.v1`, `normalization.latin-historic.v1`, `typography.ratios.v1`, `recomposition.unicode.v1`,
  `composition.docling.v1`. Each has `Options` (today's constants become options with today's values as
  defaults: `DEMOTE`, `SPLIT`, `LEVELS`, `PAGE_NUMBER_MIN_CONF`, ...), capabilities (`unit`, `produces`), and
  `scripts` (the Unicode scripts it covers, `"*"` for all). The logic stays in `text/`, `images/` and
  `formats/docling.py`; engines are thin.
- Engine protocol for rule-based steps: page unit `__call__(t: Transcription, **options) -> Transcription`; item unit
  `__call__(pages: list[Transcription], **options) -> list[Transcription]` (the pages of one item in order).
- Presets (YAML + Markdown sidecar): `working-image`, `latin-historic`, `ratios`, `unicode-recomposition`,
  `docling-composition`, each edition 1, reproducing today's behavior.
- Script dispatch: a preset may name `by_script: {<ISO 15924 code>: <preset ref>}` with a default; the engine
  `recomposition.by-script.v1` (and `normalization.by-script.v1`) picks the strategy per decision from the script
  of the characters around it (the `regex` package's `\p{Script=...}`; add it as a core dependency). With one
  strategy for all scripts today, this is exercised by tests with a fake second strategy.

## 3. Blocks

- `ImageConverter(output_folder, preset=...)` on `image.webp-lossless.v1`; `CharacterNormalizer` (new) on
  `normalization.*`; `Typographer` on `typography.*`; `Recomposer` (new, page or item unit) on `recomposition.*`;
  `Composer` (page or item unit) on `composition.*`; all take a preset ref or an engine spec, like model blocks, and
  run in-process (no backend choice). `UnicodeNormalizer` (NFC) stays a block without an engine.
- `Composer` builds the document from `paragraphs` when a Recomposer ran, else from lines (diplomatic: today's
  `text="lines"`). The DocumentBuilder's recomposition moves into the recomposition engine; the Composer keeps the
  structure (labels, headings, sections, furniture, dividers, region map).
- `Binder` (page → item): gathers an item's pages in order into one item document (`Item` record: item id, page
  records in sequence order); replaces the gathering part of `BindItem`/`ItemTexts`. `Splitter` (item → page): the
  pages of an item document, each with what the item-level steps added (paragraph continuations).
- Writers: `ItemTextWriter` renders the text variants from the item record (`verbatim_txt` from lines as laid out,
  pages joined with a form feed; `readable_txt`/`readable_md` from the paragraphs' normalized text, body only);
  `ItemDocumentWriter` writes the item document's exports. `BindItem`, `ItemTexts` and `text.py`'s `join_lines`
  and block flow are removed.

## 4. Pipelines

- `transcribe_modular.py`: `--text lines|reflow` becomes the slot `--recomposition PRESET` (none: as laid out) plus
  `--composition PRESET`, `--typography PRESET`, `--normalization PRESET` slots; `--item-texts` keeps working through
  the builder's stage cut (Binder in the item stage).
- `bind.py`: Binder → Recomposer(unit=item) → CharacterNormalizer → Composer(unit=item) → `ItemTextWriter` to
  `OUT/texts/<variant>/` and `ItemDocumentWriter` to `OUT/documents/<format>/`, each switchable off; slots for the
  rule-based presets; a recipe `item-texts@1` (pipeline `bind.v1`) for the default combination.
- The `squiddle` recipe names the rule-based presets that reproduce it; behavior is unchanged (goldens), so its
  edition is migrated (lock `previous_sha256`, `catalog release --migrate-pipeline`) rather than renumbered.

## 5. Measuring the readable texts

The readable text variants change: they come from the recomposition (geometry, Unicode rules, the document as
lexicon) instead of `join_lines`. Measure on the BHL ground truth (`~/data/bhl-ocr-eval`, the whole items where
available) before and after: number of paragraphs, division-mark decisions that differ, and CER of `readable_txt`
against the ground truth text where one exists; record the result in NOTES.md as a dated entry, facts only.
