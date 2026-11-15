# Plan: transcription strategies (linecaster 0.10.0)

Branch `text-strategies`. A breaking release: every change below ships together as 0.10.0, with upgrade notes.
Agreed with the maintainer on 2026-11-15; this file goes when the branch is merged (its decisions move to NOTES.md).

## The principle

Nothing changes text silently. A record holds what the source or the engine said; every change to that text is a
named, versioned normalization, chosen by whoever asks for a text, recorded with the text, and applied the same way to
everything that is compared.

## What changes, in one table

| Today | After |
|---|---|
| Three fixed text variants written by default (`verbatim_txt`, `readable_txt`, `readable_md`) | No text by default; texts on request as `<strategy>:<format>` (`literal:txt`, `latin-historic@1:md`) |
| "verbatim", "as written", "diplomatic" for the unnormalized text | **literal**: the readings exactly as given, lines as laid out, no edit applied (not even NFC) |
| "readable"/"reading" text | **normalized** text: a normalization strategy applied to the literal text |
| A normalization step writes `normalized` edits into the record; an NFC step writes `nfc` edits | Normalizations applied when a text is written; the record keeps readings and the source's own edits only |
| Division marks removed by default in three places (recomposition, document builder, `reading@1`) | Only by a named normalization: from the source's markup, or a named method a recipe chooses |
| Scoring lanes: Python functions, a separate system | Lanes are normalization strategies built from the same normalizations, applied to both sides |
| CER counts Unicode code points | CER counts grapheme clusters (unit a named setting) |
| A ground truth does not say how it was transcribed | It declares the normalizations it embodies; scoring warns when the strategy does not match them |
| ALTO's `SUBS_CONTENT` ignored | Read as `joined` edits, as Wikisource's `{{hws}}`/`{{hwe}}` |

## 1. Catalog: two new kinds

- **`normalization`** (`linecaster.normalization/1`): one concern, one rule set, versioned and released like
  policies and conventions (`release`, `verify`, lock table, docs page, prose with *What it does* / *Scope*).
  Fields: `id`, `edition`, `description`, `scripts` (ISO 15924; `*` for any), `languages` (BCP 47, empty for none:
  a language-specific normalization is never part of a default), `use` (`output`, `comparison` or both: casefolding
  and dropping punctuation are for comparison only), and the rule itself, one of:
  - `unicode: NFC | NFKC`;
  - `map:` a character table (`ſ: s`); `superscript-e` is a small pattern rule (`map` with combining sequences);
  - `edits: [corrected, expanded, regularized]`: apply the source's own edits of those kinds;
  - `divided-words: source`: join a word divided across lines or pages where the source marks it (`joined` edits);
  - `division-marks: <method>`: resolve the remaining marks by a named method; the first method is today's rule,
    `unicode-marks` (squiddleocr's reflow rule, with the document's words as lexicon), now opt-in;
  - `flow`: a block's rows joined into running text (UAX #14 separators), continued blocks joined across regions
    and pages;
  - comparison rules: `casefold`, `markup` (today's `MARKUP` list), `alnum` (letters, marks, digits), `whitespace`.
  The first entries: `nfc`, `nfkc`, `long-s`, `ligatures`, `r-rotunda`, `superscript-e` (from today's
  `NORMALIZE_MAP`), `editors-corrections`, `editors-expansions`, `editors-regularizations`, `divided-words`,
  `unicode-marks`, `flow`, `casefold`, `markup`, `alnum`, `ascii-alnum`, `whitespace`, `invisible` (soft hyphen,
  zero-width characters).
- **`strategy`** (`linecaster.strategy/1`): an ordered list of normalizations at pinned editions, and what it is
  for (`use`). `literal` is the built-in empty strategy (no entry needed, nothing to version). First entries:
  - `latin-historic@1`: `nfc, long-s, ligatures, r-rotunda, superscript-e` (today's preset, split into its parts;
    no flow, no division marks: a recipe adds what it wants);
  - the lanes as strategies, `use: comparison`: `diplomatic@1` (`nfc, whitespace`), `reading@2` (today's
    `reading@1` without its hyphen join), `alnum@1`, `alnum@2` (the default), `ascii-alnum@1`. `reading@1` stays as
    a released strategy (its hyphen join written as `division-marks: line-end-hyphen`, comparison only), so old
    evidence keeps resolving.
- Ad hoc mixing without a catalog entry: `--text md:nfc+long-s+flow+divided-words` builds an unnamed strategy from
  released normalizations; the output's record lists them with their editions and hashes.
- The internal by-script `Strategy` class (`engines/base.py:78`) is renamed `ScriptStrategy` to free the word.

## 2. The record: what the source said, nothing more (`linecaster.page/5`)

- `text_of(line)` returns the reading. `AS_WRITTEN` goes; a caller that wants edits applied names a strategy.
- Writers removed: the `normalization` step (`engines/normalization.py`, `blocks/text/normalizer.py`, the preset
  `latin-historic@1` as a preset), the NFC step (`text/unicode.py`, `UnicodeNormalizer`, its unconditional insertion
  in `transcribe_modular`), `normalized` and `nfc` edits. The data model keeps the edit kinds the sources write:
  `corrected`, `expanded`, `regularized`, `joined`.
- The drop capital: typography's `joined` whole-line edit (letter glued to its line) becomes structure: the drop
  capital region is linked to the line it begins (`part_of`), and `flow` writes the letter with it. Literal text
  keeps it where it stands.
- `Paragraph` keeps its structure (rows, decisions, continuation links) and loses `text`: paragraph text is made at
  output. The recomposition step finds paragraphs and continuations only; it no longer removes division marks (it
  still records, as a `Decision`, that a row ends with one, which `unicode-marks` reads).
- linecaster-mediawiki: `link_pages` no longer writes whole-line edits (`join_divided_words` moves into core as the
  `divided-words` normalization, paired at output).
- Upgrade (`linecaster.data.upgrade`, page/4 → page/5): `nfc` and `normalized` edits and whole-line `joined` edits
  from linecaster's own steps are dropped (they are derived; a strategy makes them again), `Paragraph.text` dropped.
- Ground truth declares its conventions: `Source.normalized` (new, optional): the normalizations the transcription
  already embodies (Wikisource: `long-s`, `ligatures`, `divided-words` within a page, …). A conventions entry states
  them (`transcription:` field) and its importer copies them into each record. `enwikisource@5` declares them.
- ALTO: the importer reads `SUBS_TYPE`/`SUBS_CONTENT` (HypPart1/HypPart2) as span `joined` edits with the whole
  word; the writer writes them back.

## 3. Output: texts by strategy and format

- One path for every text: records → `DocumentBuilder` (structure only: blocks, layers, tables, sections; each
  block's text literal, its rows as `\n`) → the strategy, block by block (spans move with the text, as
  `_moved` does now) → the serializer (`txt`, `md`, `html`, `json`). The variant code (`text/variants.py`,
  `ItemTextWriter`'s variants, `data/page.py` `Text`) goes; its NFC-on-everything with it.
- Defaults: a run writes the document as JSON (literal: the structure and the readings) and the files it was asked
  for. `--text <strategy>:<format>` (repeatable) on `bind` and `transcribe_modular` replaces `--variants`,
  `--item-texts`, `--no-texts`; the page writer's `md`/`txt` fallback becomes `literal`.
- Every written text names its strategy (and each normalization's edition and hash) in the run record and in the
  file's metadata where the format has room (JSON, HTML `<meta>`).
- A division mark that no normalization resolves, under `flow`: the rows are joined **without a space and the mark
  kept** (`de-pends`, `inter-crossing`): no character lost, no guess. *(Decision for the maintainer: the alternative
  is to keep the row break.)*
- `ItemDocumentWriter` passes the policy's Markdown rules (it ignores them now).

## 4. Scoring

- `normalize(text, strategy)` from the strategy's normalizations; lanes resolve through the catalog. Score rows name
  the strategy with its edition; the rate key keeps the edition (`cer_page_alnum@2`, fixing `run.py:98`, where
  `alnum@1` and `alnum@2` overwrite each other); a bare id resolves to its latest edition in benchmarks too.
- Which text is scored is a strategy too: the benchmark names the output strategy (default `literal`) and the lane.
  Today OCR output is scored line by line as laid out; that stays the default, now stated.
- `token_recall` follows the benchmark's lane (it is fixed to `reading@1`). Score records carry `scorer`.
- **Grapheme clusters:** `edit_counts` aligns sequences of grapheme clusters (uniseg, already a core dependency;
  rapidfuzz takes sequences), U+FFFD positions by cluster. The unit is a benchmark setting (`unit: grapheme |
  codepoint`, default `grapheme`) and part of the benchmark's hash and of `same_scoring`. NOTES.md's exact parity with
  two outside evaluations holds with `unit: codepoint`, which stays available for that.
- **The conventions check:** when the ground truth declares `Source.normalized`, scoring checks that the lane
  (applied to both sides) includes each of them or one that subsumes it (`nfkc` ⊇ `ligatures`, `alnum` ⊇
  `whitespace`); a missing one is a warning in the score record (`conventions: [...]`) and on the console, not an
  error.

## 5. Recipes, presets, engines

- `squiddle@3`: recomposition (paragraphs only), and its texts named (`literal:txt`, `latin-historic@1+flow+
  unicode-marks:md` as squiddleocr wrote them). `unicode-recomposition@2` without mark removal.
- **One-time exception to "released editions never change"** *(decision for the maintainer)*: `squiddle@2`,
  `latin-historic@1` (preset) and `unicode-recomposition@1` name engines that go (`normalization.*`, the
  mark-removing recomposition). As with Docling in 0.9.0, they leave the catalog and its lock; old run records name
  them and resolve with 0.9.x. The alternative is keeping the engines as legacy, which keeps the silent paths alive.
- Engine packages: `linecaster>=0.10,<0.11`, minor bumps; linecaster-mediawiki 0.2.0 (`link_pages` without edits,
  `enwikisource@5`).

## 6. Words and docs

- "verbatim" → "literal" (text), "readable"/"reading text" → "normalized"; "diplomatic" stays only as the lane
  `diplomatic@1`. "As written" and "as laid out" stay as plain words for the character and flow dimensions.
- Rewritten: glossary (text variant → transcription strategy, normalization, strategy, lane), data-model.md (page/5,
  no NFC rule: "All text is NFC" goes from README, docs/index.md, data-model.md), serialization.md, evaluation.md
  (lanes are strategies, grapheme unit, conventions check), catalog.md (two kinds), pipelines.md, the generated
  pages. CHANGELOG 0.10.0 with upgrade notes first; NOTES.md entry for the decision and its evidence (the
  dehyphenation measurement on Wikisource's 10,067 words).

## 7. Order of work, each step tested and committed

1. Catalog kinds `normalization` and `strategy` (schemas, release, verify, docs pages), the first entries, and the
   normalization functions with tests (each against a hand-made case; `latin-historic@1` against today's
   `NORMALIZE_MAP` on its own table).
2. Scoring on strategies: lanes rebuilt, **parity first** (every existing scoring test and the NOTES.md parity cases
   give the same numbers with `unit: codepoint`), then the grapheme unit, the fixed rate keys, `token_recall`,
   `scorer`.
3. The record: page/5, `text_of` = reading, the steps that wrote derived edits removed, the upgrade, drop capitals as
   links, `Paragraph.text` gone, recomposition without mark removal.
4. Output: strategy application on documents (spans moved), the writers and pipeline options, `literal` defaults.
   Parity: `literal:txt` equals today's `verbatim_txt` except NFC and drop capitals; `latin-historic@1+flow+
   unicode-marks` equals today's `readable_*` on the test fixtures and a sample of 40 items (differences listed).
5. ALTO `SUBS_CONTENT`; `divided-words` in core; linecaster-mediawiki 0.2.0; `Source.normalized`, `enwikisource@5`,
   the conventions check.
6. Recipes and presets (`squiddle@3`), docs, CHANGELOG, NOTES; full tests, `catalog verify`, the docs build.
7. Release 0.10.0 when the maintainer says so; then wikisource-cp-gt moves to it (its items written with a named
   strategy: `divided-words`, `flow`), a separate step.

## Decisions for the maintainer

1. An unresolved division mark under `flow`: join without a space, keeping the mark (`de-pends`), or keep the row
   break?
2. Remove `squiddle@2`, the `latin-historic@1` preset and `unicode-recomposition@1` from the catalog (a one-time
   exception, as with Docling), or keep their engines as legacy?
3. The kind names `normalization` and `strategy`.
