# linecaster 0.10.0: transcription strategies, release versioning, data-format rules

Branch `text-strategies` in `/home/seb/dev/linecaster` (from `main` at v0.9.3; its first commit holds the earlier
draft `PLAN-text-strategies.md`, which step 0 replaces with this plan). One breaking minor release; nothing is released
until the maintainer says so.

## Context

Measuring Wikisource's 10,067 page-break words showed that linecaster dehyphenates by default with a rule nobody chose
(94.5 % of compounds divided at their own hyphen wrongly joined in the document builder), and that text is changed
silently in several places: NFC and drop-capital edits in every "as written" text, `normalized` edits stored in
records, three fixed text variants written by default, a hyphen join inside the `reading@1` lane. Discussing it, the
maintainer decided (2026-11-15):

- **Transcription strategies:** `literal` (the readings exactly as given: no edit, not even NFC, lines as laid out)
  or a **strategy** (an ordered list of named **normalizations**, mixed and matched). Normalizations are applied when
  a text is written, never stored in the record. No text is written by default. No dehyphenation by default: a
  division mark is resolved only by the source's markup or a named method a recipe chooses; one that nothing resolves
  under `flow` is joined without a space, the mark kept (`de-pends`).
- **Terms:** "verbatim" → literal, "readable/reading" → normalized; "diplomatic" stays only as the lane `diplomatic`.
- **Scoring:** lanes become strategies built from the same normalizations, applied to both sides; CER counts grapheme
  clusters (the unit a setting); ground truth declares the normalizations it embodies and scoring warns on a
  mismatch; ALTO's `SUBS_CONTENT` is read as the source's divided words. No PUA/MUFI work.
- **Release versioning for the catalog** (as Haystack does): no editions, no immutable lock, no catalog migrations;
  the linecaster release is the version; run records name every entry used with its resolved settings and content
  hash; a committed index of entry hashes makes behaviour changes visible in review; old `id@N` references resolve
  to today's entry with a warning; model pins (revision + file hashes) stay.
- **Data formats keep their own versions:** up only on an incompatible change; readers upgrade every older version
  on load; writers write the current one; every data file names the linecaster that wrote it.
- The old `squiddle@2`, `latin-historic` preset and `unicode-recomposition@1` simply change or go (0.9.x reproduces
  0.9.x runs).

## Design

### Catalog (release-versioned)
- Entry ids carry no edition (`squiddle`, `alnum`, `page-layers`, `enwikisource`); the YAML `edition` field goes.
  `registry.split_ref` (`catalog/registry.py:56`) still accepts `id@N`, drops the edition and warns once
  ("editions are gone: `alnum@2` resolves to this release's `alnum`"); every other `@` splitter
  (`adapters/__init__.py:570`, `blocks/base/model.py:50`, `tracing/__init__.py:264`) goes through it.
- **Content hash:** the existing `functional`/`recipe_functional`/`policy_functional`/`conventions_functional` +
  `canonical_sha256` (`registry.py:51,284-401`) stay as the identity of an entry's resolved settings.
- **The lock goes** (`catalog.lock`, `LockEntry`/`Lock` `schema.py:450-470`, `lock-2.json`, `release()`,
  `previous_sha256`, `--migrate-pipeline`, `--commit`, `by_sha256` over old hashes). In its place a generated
  **`catalog/data/catalog.index`** (YAML: kind, id → sha256; recipes also `pipeline_sha256`), written by
  `linecaster catalog index`; `verify` fails when it is stale, so a PR that changes an entry's behaviour shows it in
  the index diff. `verify` keeps every non-edition check (schemas, prose headings, engines exist, conventions
  resolvable, pipelines buildable).
- Conventions: `extends: mediawiki` (no edition); `markup/resolve.py` chains `mediawiki>enwikisource`.
- **Run record** (`runtime/record.py`, stays `run-record/1`: an added field): `catalog: [{kind, id, sha256,
  settings}]` for every entry the run used (recipe, each slot's preset, policy, conventions, strategies, lanes).
  Annotators keep `preset`/`preset_sha256`, `conventions`/`conventions_sha256` (refs without editions).
- `apply_recipe` (`run.py:1123`) resolves through the registry, not the lock.
- CHANGELOG convention: upgrade notes say *who is affected* and *what to do*; a **Changed outputs** section lists
  every catalog entry whose index hash changed in the release.

### Data formats
- Rule (CLAUDE.md, compatibility.md): a data format's version rises only on an incompatible change (a field removed,
  renamed or its meaning changed); added optional fields keep it. Readers upgrade any older version on load; writers
  write the current one.
- Every data file names its writer: `producer: {linecaster, commit}` on page records and documents; parquet metadata
  for `score` and `sample`; evidence already has `scoring.linecaster`.
- Published JSON schemas (`schema.py:485 FORMATS`, `linecaster catalog schemas`) gain `page` and `document`.
- Versions in this release: **page/5** (`Paragraph.text` and `ParagraphRow.charspan` gone; derived `nfc`,
  `normalized` and linecaster's own whole-line `joined` edits dropped on upgrade; `Source.normalized`; `producer`),
  **document/2** (block text literal; source edits as spans; `strategy` and `producer` fields; reader checks the
  version and reads document/1 as it is, flagged), **evidence/3** and **benchmark/2** (strategies by id + sha256,
  the counting unit; evidence/2 and benchmark/1 upgraded on read: lanes by name, `unit: codepoint`, marked
  not comparable to evidence/3 when hashes are missing). `run-record/1`, `score/1`, `sample/1`, `broker/1` keep their
  versions.

### Normalizations and strategies (two new catalog kinds)
- **`normalization`** (`linecaster.normalization/1` file format): `id`, `description`, `scripts`, `languages` (a
  language-specific one is never in a default), `use` (`output`/`comparison`/both), `subsumes` (ids it implies, for
  the conventions check), and one rule: `unicode: NFC|NFKC`, `map` (character table; `superscript-e` a sequence
  table), `edits: [corrected|expanded|regularized]` (apply the source's edits), `divided-words: source`,
  `division-marks: unicode-marks` (squiddleocr's rule, the document as lexicon; opt-in only), `flow`, `casefold`,
  `markup`, `alnum`, `ascii-alnum`, `whitespace`, `invisible`.
- **`strategy`** (`linecaster.strategy/1`): ordered normalization ids, `use`. Built-in `literal` (empty, no entry).
  Ad hoc: `nfc+long-s+flow` names an unnamed strategy; the run record lists its parts.
- First entries: the normalizations above; strategies `latin-historic` (`nfc, long-s, ligatures, r-rotunda,
  superscript-e`, from `NORMALIZE_MAP` `text/variants.py:47`) and the lanes `diplomatic`, `reading` (no hyphen
  join), `alnum` (today's `alnum@2`, the default), `alnum-nonmark` (today's `alnum@1`), `ascii-alnum`.
- Implementation: `linecaster/text/normalize.py` (rule types, string-level functions with an offset map) and
  `linecaster/document/strategy.py` (`apply(document, strategy) -> Document`: character rules on block texts and
  cells, `edits`/`divided-words` from source-edit spans, `division-marks`, then `flow`; spans and `Cell.formulas`
  moved through every change). The offset mapping generalizes `document/builder.py _moved` into
  `linecaster/text/offsets.py`. The pairing in `engines/mediawiki/.../items.py join_divided_words` moves here.
- The by-script `Strategy` class (`engines/base.py:78`) becomes `ScriptStrategy`.

### The record and the document
- `Transcription.text_of(line)` = the reading; `AS_WRITTEN` goes (`data/transcription.py:317`).
- Removed writers of derived text: the normalization step (`engines/normalization.py`, `blocks/text/normalizer.py`,
  preset `latin-historic`), the NFC step (`text/unicode.py`, `blocks/text/unicode.py`, its insertion at
  `pipelines/transcribe_modular.py:128`), recomposition's mark removal (`text/recomposition.py` `reflow_rows`/`join`;
  it keeps paragraph structure and records a row-end mark as a `Decision`), the builder's `resolve_mark`
  (`document/builder.py:191`), typography's drop-capital `joined` edit (becomes a `part_of` link; `flow` writes the
  letter with its line), linecaster-mediawiki's whole-line edits (`link_pages` writes links only).
- `DocumentBuilder` builds structure only: block text literal (rows as `\n`, continued pieces as further rows),
  formatting/formula/language spans, and source edits (`corrected`, `expanded`, `regularized`, `joined`) as spans
  with their text (document/2).

### Output
- `text/variants.py`, `ItemTextWriter`'s variants and `data/page.py Text` go. One writer per scope
  (`blocks/writers/items.py`, `files.py`): records → `DocumentBuilder` → `strategy.apply` → serializer
  (`document/serialize.py`, the policy's Markdown rules passed everywhere).
- Defaults: the document JSON (literal). `--text <strategy>:<format>` (repeatable) on `bind` and
  `transcribe_modular` replaces `--variants`, `--item-texts`, `--no-texts`; the page writer's md/txt fallback is
  `literal`. Each text names its strategy in the run record and in the file where the format allows (JSON, HTML meta).

### Scoring
- Lanes are `use: comparison` strategies resolved by the catalog; `scoring/lanes.py` becomes a thin adapter.
- The scored text: the benchmark's output strategy (default `literal`) applied to the document, rendered by layer
  (full/body), then the lane on both sides.
- `edit_counts` (`scoring/counts.py`) aligns grapheme clusters (uniseg) by default, `unit: codepoint` available;
  the unit is part of the benchmark hash and of `comparable`.
- Fixes: rate keys keep the full id (`scoring/run.py:98`); bare ids accepted (`benchmark.py:94`); `token_recall`
  follows the lane (`metrics.py:21`); score records carry `scorer` (the linecaster version; `SCORER` constant goes).
- **Conventions check:** with `Source.normalized` on the ground truth, each declared normalization must be in the
  lane or subsumed by one of it (`subsumes`); otherwise a warning in the score record (`conventions`) and on the
  console.

### Importers and conventions
- ALTO (`formats/alto.py` reader `:534`, writer `:130`): `SUBS_TYPE`/`SUBS_CONTENT` (HypPart1/2) read as span
  `joined` edits and written back.
- Conventions entries gain `transcription: [normalization ids]`; importers copy it into `Source.normalized`.
  `enwikisource` declares Wikisource's (`long-s`, `ligatures`, `divided-words` within a page, …).
- Engine packages: `linecaster>=0.10,<0.11`, minor bumps; linecaster-mediawiki 0.2.0.

## Steps (each: code, tests, `pytest` + engine tests + `catalog verify` green, one commit)

0. Replace `PLAN-text-strategies.md` with this plan; branch hygiene.
1. **Release versioning of the catalog:** editions out of the files, schemas, refs, CLI, docs generator; the lock out,
   `catalog.index` in; legacy `@N` resolution with a warning; run record `catalog` list; tests rewritten
   (`tests/catalog/test_catalog.py` and ~44 files that name editions). Check: every recipe and preset resolves, every
   pipeline builds, the index lists all 74 entries with today's hashes.
2. **Data-format rules:** `producer` on page records and documents (and parquet metadata), page/document JSON
   schemas published, version checks in every reader, the rule written into CLAUDE.md and compatibility.md.
3. **Normalizations and strategies:** the two kinds (schema, load, verify, index, docs pages), the first entries,
   `text/normalize.py`, `text/offsets.py`; each normalization tested on hand-made cases; `latin-historic` reproduces
   `variants.normalize` on its table.
4. **Scoring on strategies:** lanes rebuilt; **parity first** — every scoring test and NOTES.md's outside-evaluation
   parity cases give identical numbers with `unit: codepoint`; then the grapheme unit, the fixes, evidence/3 and
   benchmark/2 with upgrade on read.
5. **The record, page/5:** `text_of` = reading, the derived-text writers removed, recomposition without mark
   removal, drop capitals as links, `Paragraph.text` gone, upgrade 4→5, `Source.normalized`.
6. **Document/2 and output:** the builder (structure, literal text, edit spans), `strategy.apply`, the writers,
   `--text`, defaults, variants removed. **Parity:** `literal:txt` equals today's `verbatim_txt` minus NFC and drop
   capitals; `latin-historic+flow+unicode-marks:md` equals today's `readable_md` on the fixtures and 40 random items,
   every difference listed and explained.
7. **Divided words and conventions:** `divided-words` in core, ALTO `SUBS_CONTENT`, linecaster-mediawiki 0.2.0,
   `transcription` in conventions, `enwikisource` declares it, the conventions check in scoring.
8. **Recipes, packages, docs:** `squiddle` (paragraphs only; texts `literal:txt` and
   `latin-historic+flow+unicode-marks:md`), `unicode-recomposition` without mark removal, engine package ranges,
   docs (glossary, catalog.md, compatibility.md, data-model.md, serialization.md, evaluation.md, pipelines.md,
   README, CLAUDE.md rules), CHANGELOG 0.10.0 (upgrade notes, Changed outputs), NOTES.md (the decisions and the
   dehyphenation measurement).
9. **Stop for the maintainer:** report; release 0.10.0 only on their word. The wikisource-cp-gt dataset moves to
   0.10 afterwards as its own step (items written with `divided-words+flow`).

## Verification
- After every step: `uv run pytest -q` (core), the mediawiki engine tests with wikitextprocessor, `linecaster catalog
  verify`, and from step 3 the docs build (`linecaster docs`, the site build).
- Parity scripts (kept under `tests/` where small, else in NOTES.md with their numbers): catalog resolution before/after
  (step 1), scoring numbers before/after with `unit: codepoint` (step 4), literal/normalized texts against 0.9.3's
  variants (step 6), the Wikisource items: `divided-words+flow` on 0.10 against the dataset's current items Markdown
  on a sample of items (step 7).
- End to end: a small `bind` and `transcribe_modular` run on the test fixtures writing `literal:txt`,
  `latin-historic:md`, and a benchmark scored with `alnum` and `reading`, its run record showing every catalog entry
  with its hash.

## Critical files
`catalog/registry.py`, `catalog/schema.py`, `catalog/docs.py`, `catalog/data/**`, `cli.py`, `runtime/record.py`,
`runtime/run.py`, `data/transcription.py`, `data/upgrade.py`, `data/policy.py`, `document/{builder,model,serialize}.py`,
new `document/strategy.py`, new `text/{normalize,offsets}.py`, `text/{variants,recomposition,unicode,typography}.py`,
`engines/{normalization,recomposition,base}.py`, `blocks/text/*`, `blocks/writers/{items,files}.py`,
`pipelines/{bind,transcribe_modular}.py`, `scoring/{lanes,counts,metrics,run,benchmark,evidence,render}.py`,
`formats/alto.py`, `markup/{model,resolve}.py`, `engines/mediawiki/src/linecaster_mediawiki/{items,reader,importer}.py`,
`engines/*/pyproject.toml`, docs and CLAUDE.md.
