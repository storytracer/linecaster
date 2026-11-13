# Evaluation

linecaster scores transcriptions against ground truths and writes the result as evidence. It ships the scorer, the
normalization lanes, the score pipeline and the formats (`linecaster.benchmark/1`, `linecaster.score/1`,
`linecaster.evidence/2`); it ships no benchmark and no evidence: those live with the evaluation that made them
([catalog](catalog.md#measurements-live-elsewhere)). Any two evidence records with the same benchmark, policy, lanes
and scorer edition are comparable, whatever model, pipeline or machine produced the runs they measure.

```text
ground truth ──import──► transcription (source.kind ground_truth) ─┐
                                                                   ├─ render (one policy) ─ normalize (lanes) ─ count ─► score records ─ aggregate ─► evidence
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
notes, continuations, corrections, illegible spans, each as the [data model](data-model.md) defines them.

Importers in linecaster are generic: ALTO, PAGE-XML and hOCR (`linecaster.formats`, `ground_truth=True`), Docling
JSON (`from_docling`), and text or Markdown with optional header and footer fields. A source with conventions of its
own (a wiki's templates, a project's markup) is imported by the evaluation's own code, which builds the annotations
through `linecaster.data`.

**What a ground truth supports** is recorded in its benchmark (below): which roles it marks, whether it has boxes,
a reading order of blocks, notes, continuations across pages. A metric that needs what it lacks is not computed.

## Rendering both sides

Ground truth and output are rendered under the same [rendering policy](data-model.md#rendering), named in the
benchmark. Two texts per page are scored:

| Text | Layers | Is |
|---|---|---|
| `full` | body, furniture | everything printed on the page, in reading order |
| `body` | body | the page without its furniture (running heads, page numbers, catchwords, signature marks) |

Each is rendered as laid out (lines, `verbatim_txt`'s rules) with the policy's edits for `verbatim_txt`: what a
model writes about a figure (descriptions) is in neither. A ground truth's `corrected` edits are not applied: the
output is compared with what is printed. Its `illegible` spans become U+FFFD, one per character.

## Lanes

A **lane** is a versioned normalization of a rendered text before it is counted, a catalog entry `lane` with
editions (its functional content: the steps, in order). Both sides go through the same lane.

| Lane | Steps |
|---|---|
| `diplomatic@1` | NFC; whitespace runs to one space; trimmed. Case, punctuation, ſ, ligatures and diacritics kept |
| `reading@1` | invisible format characters removed (soft hyphen, zero-width characters, word joiner, BOM); NFKC; quotes and apostrophes to `'`, dashes and hyphens to `-`; a hyphen at a line end joined to the next line; casefolded; whitespace runs to one space; trimmed |
| `alnum@1` | NFC; casefolded; only letters and digits (Unicode categories L and N) kept, each run of anything else one space; trimmed |

NFKC appears only in a lane, never in a text variant: a lane makes two texts comparable, it is not a reading text.

**U+FFFD in the ground truth** marks one illegible character: it matches any one character of the output and is
excluded from both the errors and the reference length.

## Metrics

Per page, per text (`full`, `body`) and per lane:

| Metric | Is |
|---|---|
| `s`, `d`, `i`, `h` | substitutions, deletions, insertions and hits of the codepoint alignment of output against ground truth (Levenshtein, U+FFFD as above); `n = s + d + h` |
| `cer` | `(s + d + i) / n` |
| `token_recall` | the share of the ground truth's words (whitespace tokens of the `reading@1` text, punctuation dropped) the output has, as multisets |
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
sources: `run_id`, `benchmark_sha256`, `policy`, `lane`, `scorer`. Rates are not stored: they are derived from the
counts, so corpus rates are exact.

## Aggregation

- **Corpus rates** pool the counts over the pages and divide once (micro average): `cer = Σ(s + d + i) / Σn`.
- **Intervals**: a percentile bootstrap over items (pages of one item are drawn together), with the seed, the number
  of resamples and the level the benchmark gives; the evidence names all three.
- **Strata**: any page or item field the benchmark names (a collection, a century, a script) gives rates per
  stratum.
- **Eligibility**: a run is scored only on exactly the benchmark's page set; a page the run failed counts as an empty
  output, and the evidence says how many there were. A run that lacks pages of the set is not eligible.

## Benchmarks (`linecaster.benchmark/1`)

A benchmark definition is a YAML file in the evaluation's repository:

| Field | Holds |
|---|---|
| `schema` | `linecaster.benchmark/1` |
| `id`, `edition` | its name and edition; a released edition never changes, its hash covers its functional content |
| `dataset` | the ground truth: `repo@revision`, the transcription's name, the importer |
| `pages` | the page set: a sample rule (`linecaster.data.sample`: seed, items, pages per item, pages) or a list of page ids, and its `sha256` (of the sorted page ids, one per line) |
| `supports` | what the ground truth has: `roles` (a list), `boxes`, `reading_order`, `notes`, `continuations` |
| `policy` | the rendering policy edition both sides are rendered with |
| `texts`, `lanes` | which texts and lanes are scored |
| `metrics` | which metrics, of those the ground truth supports |
| `bootstrap` | `seed`, `resamples`, `level` |
| `strata` | fields to report rates by |

## Evidence (`linecaster.evidence/2`)

One measurement per file, kept by the evaluation:

| Field | Holds |
|---|---|
| `schema` | `linecaster.evidence/2` |
| `preset` or `recipe` | the edition measured, `id@edition` |
| `source` | `own-run`, `card-claim`, `vendor-benchmark` |
| `run` | `uri` (the run folder), `run_id`, `pipeline_sha256`, `record_sha256` (of `run.yaml`) |
| `benchmark` | `id@edition` and its `sha256` |
| `scoring` | `policy`, `lanes`, `scorer` (linecaster's scorer edition), `linecaster` (version and commit) |
| `metrics` | name → `{value, lo, hi, n}`: `cer_full_diplomatic`, `cer_body_alnum`, `recall_header`, ... (`<metric>_<text>_<lane>`, `<metric>_<role>`) |
| `hardware` | `gpu` (model and count), `driver`, `cuda`, `cpu`, from the run record |
| `software` | the server's version (vLLM, ...), the engine packages' versions |
| `date`, `notes` | |

`linecaster.evidence/1` records stay readable; `linecaster evidence check` validates a file of either edition, and
`linecaster scores compare` puts evidence records side by side, only those with the same benchmark edition, policy,
lanes and scorer.

## Run records

A run record (`OUT/run.yaml`) carries what evidence names: `run_id` (stamped on every annotator the run adds),
`pipeline_sha256`, the recipe and preset editions with their hashes, the policy edition, `hardware` (GPU model and
count, driver, CUDA, CPU) and the software versions.
