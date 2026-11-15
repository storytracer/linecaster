# Evaluation

linecaster scores transcriptions against ground truths and writes the result as evidence. It ships the scorer, the
lanes (comparison strategies of the catalog), the score pipeline and the formats (`linecaster.benchmark/2`,
`linecaster.score/1`, `linecaster.evidence/3`); it ships no benchmark and no evidence: those live with the evaluation
that made them ([catalog](catalog.md#measurements-live-elsewhere)). Any two evidence records with the same benchmark,
policy, output strategy, lanes (by hash), unit and scorer are comparable, whatever model, pipeline or machine
produced the runs they measure.

```text
ground truth ──import──► transcription (source.kind ground_truth) ─┐
                                                                   ├─ render (one policy, one output strategy) ─ lanes ─ count ─► score records ─ aggregate ─► evidence
run's page records ─────► transcription (ocr_new) ─────────────────┘
```

Scoring is `linecaster.scoring` (import-light, like `linecaster.data`); its alignment needs the extra
`linecaster[rapidfuzz]`.

## Ground truth

A ground truth is a transcription like any other, stored in the page record under its name (`ground_truth`, or
the dataset's), with `source.kind = "ground_truth"`, `source.dataset` (`repo@revision`), `source.record` (the row
or file it came from) and `source.sha256`. Its annotator is of kind `human` (people transcribed or checked it; their
review in `settings.review`: `transcribed`, `proofread`, `validated`, or the source's own word) or `file` (a
delivered file whose making is unknown). It holds what its source has and no more: roles, boxes, reading order,
notes, continuations, corrections, illegible spans, each as the [data model](data-model.md) defines them, and,
in `source.normalized`, the normalizations its transcription already embodies (from its conventions' `transcription`:
a source that writes ſ as s embodies `long-s`).

Ground truth is read by **importers**, the engines of the `import` step, which `TranscriptionImporter` runs and
`pipelines/import_transcriptions.py` runs over a source's documents into page records: ALTO, PAGE-XML, hOCR, plain
text, HTML and DoclingDocuments (the `docling` extra) in linecaster (`import.*.v1`, presets `alto-import`, ...), and formats that need
more in engine packages (MediaWiki wikitext: `linecaster-mediawiki`). A source with conventions of its own (a wiki's
templates and classes, a project's markup) is read with its **conventions**, a catalog entry its importer applies:
each rule a match in the format's standard and a decision in the data model's vocabulary (what is text, what is a
role, a note, an edit, what is removed and why). The importer records the conventions' chain and hash, the coverage
(what no rule handled) and, for a source text, where every line comes from (`Zone.anchor`). No source needs code of
an evaluation's own any more.

**What a ground truth supports** is recorded in its benchmark (below): which roles it marks, whether it has boxes,
a reading order of blocks, notes, continuations across pages. A metric that needs what it lacks is not computed.

## Rendering both sides

Ground truth and output are rendered under the same [rendering policy](data-model.md#rendering), named in the
benchmark. Two texts per page are scored:

| Text | Layers | Is |
|---|---|---|
| `full` | body, furniture | everything printed on the page, in reading order |
| `body` | body | the page without its furniture (running heads, page numbers, catchwords, signature marks) |

Each is the page's literal text as laid out (its lines' readings in reading order, tables as Markdown or HTML),
then the benchmark's **output strategy**'s rules on characters (`output`, default `literal`: nothing changed): what
a model writes about a figure (descriptions) is in neither. A ground truth's `corrected` edits are not applied: the
output is compared with what is printed. Its `illegible` spans become U+FFFD, one per character.

## Lanes

A **lane** is a comparison strategy (a catalog `strategy` with `use: comparison`, [catalog](catalog.md#strategy-strategiesidyaml)):
normalizations both sides go through before they are counted, named by id and recorded with its hash. A benchmark
that names no lanes is scored in `diplomatic` (`DEFAULT_LANE`): the comparison with the fewest assumptions, NFC and
whitespace only (so that two encodings of the same text, and a text written in printed lines against one written in
paragraphs, are equal), case, punctuation, ſ, ligatures, diacritics and markup kept; every other lane adds decisions.

| Lane | Normalizations |
|---|---|
| `diplomatic` (default) | NFC; whitespace runs to one space, trimmed. Case, punctuation, ſ, ligatures and diacritics kept |
| `reading` | markup removed (special tokens, box arrays, HTML tags of a fixed list, Markdown headings, bullets and rules, LaTeX macros, and the characters `` ` * \| ~ { } $ \ ``); NFKC; invisible format characters removed; quotes and dashes unified; casefolded; whitespace collapsed. No hyphen at a line end is joined: that is a strategy's choice, never a lane's |
| `alnum` | markup removed; NFKC (ſ to s, ligatures split, superscript digits to digits); invisible format characters removed; casefolded and NFKC again; only letters, combining marks and digits of any script kept, each run of anything else one space |
| `alnum-nonmark` | NFC; casefolded; only letters and digits kept (0.9's `alnum@1`) |
| `ascii-alnum` | HTML tags removed; lowercased; only the ASCII letters and digits kept (accented letters, ſ and ligatures separate words) |

A lane from before 0.10 (`alnum@2`, `diplomatic@1`, ...) is read as today's (`alnum`, `alnum-nonmark` for `alnum@1`;
`reading@1` without its hyphen join) with a warning. NFKC appears only in a lane, never in an output text: a lane
makes two texts comparable, it is not a reading text.

### Conventions

A ground truth that declares the normalizations its transcription embodies (`source.normalized`) is checked against
each lane: a declared normalization that neither the lane nor the output strategy's rules on characters apply,
themselves or through one that `subsumes` it (`nfkc` subsumes `nfc`, `long-s`, `ligatures`), is a difference the
comparison counts that is the ground truth's convention, not the output's error. Each score record names those
(`conventions`), and the run warns once per lane (`ConventionsWarning`, and on the console of `linecaster score`).
English Wikisource scored in `alnum`, for example: `r-rotunda` and `divided-words` (Wikisource rejoins words divided
at a line end; the output as read does not).

**U+FFFD in the ground truth** marks one illegible character: it matches any one character of the output and is
excluded from both the errors and the reference length.

## Metrics

Per page, per text (`full`, `body`) and per lane:

| Metric | Is |
|---|---|
| `s`, `d`, `i`, `h` | substitutions, deletions, insertions and hits of the alignment of output against ground truth (Levenshtein, U+FFFD as above), in the benchmark's `unit`: grapheme clusters (the default: a base letter with its combining marks is one character) or codepoints; `n = s + d + h` |
| `cer` | `(s + d + i) / n` |
| `token_recall` | the share of the ground truth's words (whitespace tokens of the lane's text) the output has, as multisets |
| `over_extraction` | the share of the output's words the ground truth does not have |

Per page and role, where the ground truth marks the role (no boxes needed):

| Metric | Is |
|---|---|
| `role_words_true`, `role_words_output`, `role_words_both` | the words (as for `token_recall`) the ground truth puts in the role, those the output puts there, and their multiset intersection; precision and recall per role follow |

Per page, where both sides have boxes: regions matched one to one by IoU (greedy, highest first, IoU ≥ 0.5), and a
confusion table of their roles (`role_true`, `role_output`, `count`), with the unmatched on either side as `none`.

Per page, always: the output's `finish_reason`s, whether it was repaired, its errors, `seconds` and tokens (from its
annotators' measurements), so that truncation and cost are read next to the scores.

## Score records (`linecaster.score/1`)

One row per page, text and lane, in `OUT/scores/*.parquet`: `page_id`, `item_id`, `text`, `lane`, `s`, `d`, `i`,
`h`, `n`, `token_recall` counts, `over_extraction` counts, the role word counts as a map, the confusion rows as a
list, the page's flags (`finish_reason`, `repaired`, `error`) and measurements, and the ids that tie the row to its
sources: `run_id`, `benchmark_sha256`, `policy`, `output`, `lane`, `unit`, `scorer`, and `conventions` (the
conventions check). Rates are not stored: they are derived from the
counts, so corpus rates are exact.

## Aggregation

- **Corpus rates** pool the counts over the pages and divide once (micro average): `cer = Σ(s + d + i) / Σn`.
- **Intervals**: a percentile bootstrap over items (pages of one item are drawn together), with the seed, the number
  of resamples and the level the benchmark gives; the evidence names all three.
- **Strata**: any page or item field the benchmark names (a collection, a century, a script) gives rates per
  stratum.
- **Eligibility**: a run is scored only on exactly the benchmark's page set; a page the run failed counts as an empty
  output, and the evidence says how many there were. A run that lacks pages of the set is not eligible.

## Benchmarks (`linecaster.benchmark/2`)

A benchmark definition is a YAML file in the evaluation's repository:

| Field | Holds |
|---|---|
| `schema` | `linecaster.benchmark/2` (`/1` is read, upgraded: its lanes by today's names, `unit: codepoint`) |
| `id`, `edition` | its name and edition (the evaluation's own versioning); its hash covers its functional content |
| `dataset` | the ground truth: `repo@revision`, the transcription's name, the importer |
| `pages` | the page set: a sample rule (`linecaster.data.sample`: seed, items, pages per item, pages) or a list of page ids, and its `sha256` (of the sorted page ids, one per line) |
| `supports` | what the ground truth has: `roles` (a list), `boxes`, `reading_order`, `notes`, `continuations` |
| `policy` | the rendering policy both sides are rendered with |
| `texts`, `lanes` | which texts and lanes are scored |
| `output` | the output strategy both texts are written with (`literal` by default) |
| `unit` | `grapheme` (default) or `codepoint`: what a character error counts; part of the hash |
| `metrics` | which metrics, of those the ground truth supports |
| `bootstrap` | `seed`, `resamples`, `level` |
| `strata` | fields to report rates by |

## Evidence (`linecaster.evidence/3`)

One measurement per file, kept by the evaluation:

| Field | Holds |
|---|---|
| `schema` | `linecaster.evidence/3` |
| `preset` or `recipe` | what was measured, by id (the run record has its hash) |
| `source` | `own-run`, `card-claim`, `vendor-benchmark` |
| `run` | `uri` (the run folder), `run_id`, `pipeline_sha256`, `record_sha256` (of `run.yaml`) |
| `benchmark` | `id@edition` and its `sha256` |
| `scoring` | `policy`, `output` and each of `lanes` by id and `sha256`, `unit`, `scorer` (the linecaster that scored, version and commit) |
| `metrics` | name → `{value, lo, hi, n}`: `cer_full_diplomatic`, `cer_body_alnum`, `recall_header`, ... (`<metric>_<text>_<lane>`, `<metric>_<role>`) |
| `hardware` | `gpu` (model and count), `driver`, `cuda`, `cpu`, from the run record |
| `software` | the server's version (vLLM, ...), the engine packages' versions |
| `date`, `notes` | |

`linecaster.evidence/1` and `/2` records stay readable, upgraded when read (their lanes by today's names, `unit:
codepoint`, marked not comparable with evidence/3 where a hash is missing); `linecaster evidence check` validates a
file of any version, and `linecaster evidence compare` puts evidence records side by side, only those scored the same
way (benchmark, policy, output strategy, lanes by hash, unit).

## Run records

A run record (`OUT/run.yaml`) carries what evidence names: `run_id` (stamped on every annotator the run adds),
`pipeline_sha256`, the recipe and every catalog entry the run used with its settings and hash (`catalog`: presets,
policy, conventions, the strategies its texts were written by), `hardware` (GPU model and count, driver, CUDA, CPU)
and the software versions.
