# Evaluation

linecaster scores transcriptions against ground truths and writes the result as evidence. It ships the scorer, the
lanes (comparison strategies of the catalog), the score pipeline and the formats (`linecaster.benchmark/2`,
`linecaster.score/1`, `linecaster.evidence/3`); it ships no benchmark and no evidence: those live with the evaluation
that made them ([catalog](catalog.md#measurements-live-elsewhere)). Any two evidence records with the same benchmark,
policy, output strategy, lanes (by hash), unit, word and element metrics are comparable, whatever model, pipeline
or machine produced the runs they measure.

```text
ground truth ──import──► transcription (source.kind ground_truth) ─┐
                                                                   ├─ render (one policy, one output strategy) ─ elements ─ lanes ─ count ─► score records ─ aggregate ─► evidence
run's page records ─────► transcription (ocr_new) ─────────────────┘
                                                                   └─ export ─► an external benchmark's files ─► its own evaluation
```

## Ground truth, benchmarks and evaluations

| What | Is | Where it lives |
|---|---|---|
| a source | transcriptions made or checked by people, in their own format (PAGE-XML, TEI, wikitext, a benchmark's JSON) | the source |
| conventions | what a public source's markup means, declaratively (`linecaster.conventions`) | linecaster's catalog |
| page records | the neutral exchange format: a ground truth imported into linecaster's data model, or a run's output | the dataset (`linecaster truth publish`), the run |
| rendering policy, output strategy, lanes | how both sides are rendered, written and compared | linecaster's catalog |
| the scorer | page and element metrics, strata, aggregation | linecaster (`linecaster.scoring`) |
| a benchmark | a definition: a ground truth, its page set, the policy, lanes, metrics (`linecaster.benchmark/2`; `linecaster benchmark init`) | the evaluation |
| an evaluation | the runs scored under a benchmark, their score records and evidence | the evaluation's own repository |
| an external benchmark | another project's ground-truth format, scorer and dataset (OmniDocBench) | that project; linecaster imports its ground truth and exports to it |

linecaster holds the tools and the formats; ground truths, benchmarks and evidence are data and live elsewhere. An
external benchmark's code never runs inside linecaster: its ground truth is read by an importer, so linecaster's
scorer can score models on its pages, and a ground truth and a run are written as its files by an exporter, so its own
evaluation scores them unchanged ([export](#export-to-omnidocbench-linecaster-export-omnidocbench)).

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
a reading order of components, notes, continuations across pages. A metric that needs what it lacks is not computed.

## Rendering both sides

Ground truth and output are rendered under the same [rendering policy](data-model.md#rendering), named in the
benchmark. Two texts per page are scored:

| Text | Layers | Is |
|---|---|---|
| `full` | body, furniture | everything printed on the page, in reading order |
| `body` | body | the page without its furniture (running heads, page numbers, catchwords, signature marks) |

Each is the page's literal text as laid out (its lines' readings in reading order, tables as Markdown or HTML, a
formula region as `$LaTeX$` in place of its lines, as a ground truth writes a formula),
then the benchmark's **output strategy**'s rules on characters (`output`, default `literal`: nothing changed): what
a model writes about a figure (descriptions) is in neither, unless the policy puts it in the body
(`page-layers-described`: after its region, one per line). A ground truth's `corrected` edits are not applied: the
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
| `reading` | formulas as the characters they print (`latex-text`: `$\frac{1}{2}$` as `1⁄2`, which NFKC makes of `½` too; `$\alpha$` as `α`; sub- and superscripts as their characters); markup removed (special tokens, box arrays, HTML tags of a fixed list, Markdown headings, bullets and rules, LaTeX macros, and the characters `` ` * \| ~ { } $ \ ``); NFKC; invisible format characters removed; quotes and dashes unified; casefolded; whitespace collapsed. No hyphen at a line end is joined: that is a strategy's choice, never a lane's |
| `typographic` | `reading`, with international typography folded as Omni Parse Bench's comparison fold does: superscript digits after a digit set apart before NFKC (`1,240¹` as `1,240 1`); after markup is removed, checkboxes as `☒` and `☐` (`[x]`, `✔`, `[ ]`, `□`), footnote markers `[1]` and `[^a]` as their label after a space, a bullet glyph starting a line and leaders (runs of three or more dots, dashes, underscores, `=` or `*`) as a space; after quotes and dashes, `typography` (low quotes, guillemets, primes, the minus sign, special spaces, arrows, the fraction slash, `…`, a middle dot between digits as `.`) and `cjk-punctuation` (`。、「」【】（）`… as ASCII); casefolded; whitespace collapsed. No hyphen at a line end is joined (`line-end-hyphens` is opt-in by name, `typographic+line-end-hyphens`), and language-specific letters stay (`typographic+romanian-comma-below`) |
| `alnum` | formulas as the characters they print (`latex-text`); markup removed; NFKC (ſ to s, ligatures split, superscript digits to digits); invisible format characters removed; casefolded and NFKC again; only letters, combining marks and digits of any script kept, each run of anything else one space |
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
| `token_recall` | the share of the ground truth's words (the benchmark's tokenizer on the lane's text, below) the output has, as multisets |
| `over_extraction` | the share of the output's words the ground truth does not have |

Per page and role, where the ground truth marks the role (no boxes needed):

| Metric | Is |
|---|---|
| `role_words_true`, `role_words_output`, `role_words_both` | the words (as for `token_recall`) the ground truth puts in the role, those the output puts there, and their multiset intersection; precision and recall per role follow |

**Words.** The word metrics cut the lane's text into words by the benchmark's tokenizer (`words`,
`linecaster.scoring.tokens`); a word with an illegible character is left out:

| Tokenizer | Words |
|---|---|
| `whitespace` | runs between whitespace, everything but letters, combining marks, format characters, digits and the underscore a boundary: a word keeps its combining marks (Devanagari vowel signs, Arabic vowel marks, Hebrew points, Thai vowels) and its joiners (the zero-width non-joiner and joiner, the Mongolian vowel separator), while the zero width space separates words; a text without spaces (Chinese, Japanese, Thai) is one word per run |
| `uax29` (default) | Unicode's word boundaries (UAX #29): Chinese ideographs, Hiragana and Thai one word per character (Unicode leaves those scripts to a dictionary), Katakana runs whole, the other scripts by their own boundaries |
| `characters` | grapheme clusters with a letter, mark or digit |

Role words are each line's words written as the scored texts are: its illegible spans as U+FFFD, then the output
strategy, then the first lane and the tokenizer.

Per page, where both sides have boxes: regions matched one to one by IoU (greedy, highest first, IoU ≥ 0.5), and a
confusion table of their roles (`role_true`, `role_output`, `count`), with the unmatched on either side as `none`.

Per page, always: whether the output is missing, its error and the `finish_reason` of its last annotator that
recorded one, so that missing, failed and truncated pages are read next to the scores.

## Elements

The page metrics compare one string per page, so an output that reads every paragraph right but puts them in another
order, or cuts a paragraph in two, is charged as if it misread. The element metrics compare content where it is, as
OmniDocBench does: each side is cut into elements, the ground truth's elements are matched to the output's, and each
match is compared on its own; the reading order is scored apart (`metrics: [elements, tables, formulas,
reading_order]`, the default with the page metrics).

**Elements** (`linecaster.scoring.elements`), in each side's reading order: a region's run of lines (its text, as
the texts render it: illegible spans as U+FFFD), a table (by `table_kind`: data tables are tables, the rest text,
unless the benchmark's `elements.tables` is `all`), a formula (a formula region, or a line that is a display
formula), a description where the policy scores it (`page-layers-described`). An output without regions (a model's
Markdown) is cut into its lines, with the components that span lines
recognized: an HTML table, a pipe table, a `$$…$$` or `\[…\]` formula, a `#` heading. Each element records its role,
kind, layer, and the writing system and classifications that hold for it.

**Matching** (`linecaster.scoring.matching`): both sides' contents written by the output strategy and the matching
lane (`elements.lane`, default `alnum`: letters, marks and digits of any script, so markup, punctuation and
formula notation do not keep a match apart), as units (grapheme clusters by default), so it works the same in
every script. An element's candidates are the elements of the other side sharing the most n-grams of units; its home
is the candidate it lies in or holds the most (containment: one minus the edit distance of the shorter aligned
against the best stretch of the longer, over its length; at least `elements.containment`, default 0.5), ties broken
by similarity, then by position. Short elements (`elements.short`, default 4 units) need that similarity instead. The
homes' connected components are the **match groups**: `one`, `split` (one ground-truth element, several output
elements), `merge`, `many`, `missed` (no partner), `extra`; past `elements.max_cells` aligned units a page is one
group (`page`). The matching is deterministic.

**Counts.** A group's sides are compared as wholes, each joined with spaces in its order, and the edits are
attributed to the ground-truth elements they fall in (`edit_counts_by`, summing to the group's counts): the element
score forgives the order between groups. It is no bound on the page score: a wrong match costs, and tables are
compared by their cells' text where the page texts write them as HTML or Markdown. A missed element counts all
deletions; an extra element all insertions; extra text is never free.

| Metric | Is |
|---|---|
| `element_cer` | `Σ(s + d + i) / Σn` over the elements |
| `element_ned` | `Σ(s + d + i) / Σm`, `m = max(n, h + s + i)`: normalized edit distance, at most 1 |
| `teds`, `teds_s` | per ground-truth table, the tree-edit-distance similarity (Zhong et al., 2020) to the output table of its group, of content and structure or structure alone (`linecaster.scoring.teds`, from the tables' cells; 0 without one) |
| `table_recall` | the share of ground-truth tables the output gives as tables |
| `table_precision` | the share of the output's tables that are in a group with a ground-truth table |
| `formula_cer`, `formula_ned` | per ground-truth formula, the edit distance of the cleaned LaTeX (`linecaster.text.formulas.clean`, without spaces) to the output's in its group |
| `order_kendall` | of the pairs of matched ground-truth elements (those of regions the ground truth's order ranks, where it has one: furniture it leaves unordered is not ordered), the share the output puts the other way round (`linecaster.scoring.order`) |
| `order_edit` | the edit distance between the ground truth's order of its matched elements and the output's, over their number: OmniDocBench's reading-order measure |

The element rates are per text and lane (`element_cer_full_diplomatic`); the formula and order rates are for the
first text and lane. Element rows (`elements.parquet`, beside the score records) hold one row per element, text and
lane: `level` (`element`), `side` (`truth` or `output`), `element`, `index`, `kind`, `role`, `layer`, `group`,
`match`, the counts, `teds`, `teds_s`, `table_kind`, `as_table`, `latex_*` and `attributes`.

## Strata

Rates by strata are a run's rates on part of what was compared (`linecaster.scoring.strata`). The element rates are
always given by `role` and `kind`; a benchmark's `strata` adds dimensions:

- of an element: `role`, `kind`, `layer`, `match` (its group's kind), `table_kind`, and any scheme it records:
  `language`, `script`, `direction` (the writing system that holds for it), its region's classifications (a tag such
  as `degraded`);
- of a page (`pages:<dimension>` in the result): `slice` and any scheme the page records, for the page rates.

Only recorded values count: what records none is in the stratum `unrecorded`, never given an inferred value.

## Score records (`linecaster.score/1`)

One row per page, text and lane, in `OUT/scores/*.parquet`: `page_id`, `item_id`, `text`, `lane`, `unit`, `words`
(the tokenizer), `s`, `d`, `i`, `h`, `n`, the word counts `words_true`, `words_output`, `words_both`, the page's flags
(`missing`, `error`, `finish_reason`), and the ids that tie the row to its sources: `run_id`, `benchmark`,
`benchmark_sha256`, `policy`, `output`, `scorer`, and `conventions` (the conventions check). Rates are not stored: they are derived from the
counts, so corpus rates are exact. Element rows are in `OUT/scores/elements.parquet` ([elements](#elements)).

## Aggregation

- **Corpus rates** pool the counts over the pages and divide once (micro average): `cer = Σ(s + d + i) / Σn`.
- **Intervals**: a percentile bootstrap over items (pages of one item are drawn together), with the seed, the number
  of resamples and the level the benchmark gives; the evidence names all three.
- **Strata**: rates by role and kind of element, and by the dimensions the benchmark names ([strata](#strata)).
- **Eligibility**: a run is scored only on exactly the benchmark's page set; a page the run failed counts as an empty
  output, and the evidence says how many there were. A run that lacks pages of the set is not eligible.

## Scoring many pages (`pipelines/score.py`)

`linecaster score` scores a run in one process. `pipelines/score.py` (the pipeline `score.v1`) scores the same way over
many tasks, here (`--workers`) or on a Ray cluster (`--on ray`), like every other pipeline:

    uv run pipelines/score.py RUN/scores --pages RUN/pages --truth TRUTH --benchmark benchmark.yaml --tasks 32

Each task scores a share of the run's page records (`PageScorer`: its pages' ground truth read in one pass, only
their lines decoded) and writes their score records and page summaries (`ScoreWriter`: `OUT/records`, `OUT/pages`).
When every task is done, the driver puts them together (`linecaster.scoring.run.aggregate`): the pages the run lacks
are scored as empty outputs, then the rates, intervals and conventions check as above, into `OUT/scores.parquet` and
`OUT/evidence.yaml`. The score records are the ones `linecaster score` writes, page for page. With more tasks than
page-record files, the tasks share each file (every k-th record each), so any number of tasks has work.

## Benchmarks (`linecaster.benchmark/2`)

A benchmark definition is a YAML file in the evaluation's repository:

| Field | Holds |
|---|---|
| `schema` | `linecaster.benchmark/2` (`/1` is read, upgraded: its lanes by today's names, `unit: codepoint`) |
| `id`, `edition` | its name and edition (the evaluation's own versioning); its hash covers its functional content |
| `dataset` | the ground truth: `repo@revision`, the transcription's name, the importer |
| `pages` | the page set: a list of page ids, or a sample rule (`linecaster.data.sample`: seed, items, pages per item, pages, and `stratify`, `per_stratum`, `splits`, `split`) applied to the ground truth when no ids are listed, and its `sha256` (of the sorted page ids, one per line) |
| `supports` | what the ground truth has: `roles` (a list), `boxes`, `reading_order`, `notes`, `continuations` |
| `policy` | the rendering policy both sides are rendered with |
| `texts`, `lanes` | which texts and lanes are scored |
| `output` | the output strategy both texts are written with (`literal` by default) |
| `unit` | `grapheme` (default) or `codepoint`: what a character error counts; part of the hash |
| `words` | the word metrics' tokenizer: `uax29` (default), `whitespace` or `characters`; part of the hash where it is not the default (so benchmarks that name none keep theirs) |
| `metrics` | which metrics, of those the ground truth supports; default the element metrics (`elements`, `tables`, `formulas`, and `reading_order` where the ground truth supports it) and the page metrics `cer`, `token_recall`, `over_extraction` |
| `elements` | how elements are cut and matched: `lane`, `tables` (`data` or `all`), `containment`, `short`, `ngram`, `candidates`, `stop`, `max_cells` ([elements](#elements)); part of the hash when element metrics are named |
| `bootstrap` | `seed`, `resamples`, `level` |
| `strata` | dimensions to report rates by ([strata](#strata)) |

## Evidence (`linecaster.evidence/3`)

One measurement per file, kept by the evaluation:

| Field | Holds |
|---|---|
| `schema` | `linecaster.evidence/3` |
| `preset` or `recipe` | what was measured, by id (the run record has its hash) |
| `source` | `own-run`, `card-claim`, `vendor-benchmark` |
| `run` | `uri` (the run folder), `run_id`, `pipeline_sha256`, `record_sha256` (of `run.yaml`) |
| `benchmark` | `id@edition` and its `sha256` |
| `scoring` | `policy`, `output` and each of `lanes` by id and `sha256`, `unit`, `words` (the tokenizer and the version of the word metrics' rules: 1 dropped combining marks and format characters, 2 keeps them; absent: whitespace, 1), `elements` (with element metrics: the version of the element scorer's rules, `linecaster.scoring.ELEMENTS_VERSION`, and the matching lane by id and `sha256`), `scorer` (the linecaster that scored, version and commit) |
| `metrics` | name → `{value, lo, hi, n}`: `cer_full_diplomatic`, `cer_body_alnum`, `role_recall_header`, ... (`<metric>_<text>_<lane>`, `role_precision_<role>`, `role_recall_<role>`) |
| `slices` | slice → `{definition, pages, metrics}`: CER and word recall on the pages whose ground truth has data tables (`tables`, `linecaster.scoring.tables`), formulas (`formulas`), or neither (`plain`); `linecaster.scoring.slices` |
| `strata` | dimension → value → `{pages, elements, metrics}` ([strata](#strata)) |
| `hardware` | `gpu` (model and count), `driver`, `cuda`, `cpu`, from the run record |
| `software` | the server's version (vLLM, ...), the engine packages' versions |
| `date`, `notes` | |

`linecaster.evidence/1` and `/2` records stay readable, upgraded when read (their lanes by today's names, `unit:
codepoint`, marked not comparable with evidence/3 where a hash is missing); `linecaster evidence check` validates a
file of any version, and `linecaster evidence compare` puts evidence records side by side, only those scored the same
way (benchmark, policy, output strategy, lanes by hash, unit, word metrics, element metrics).

## Export to OmniDocBench (`linecaster export omnidocbench`)

linecaster runs no external benchmark's code: it writes a ground truth and a run in the benchmark's formats, and the
benchmark's own evaluation scores them, where and how its owners run it. For OmniDocBench (opendatalab/OmniDocBench,
its end-to-end evaluation):

    linecaster export omnidocbench OUT --truth TRUTH/pages --pages RUN/pages [--ids IDS] [--tables data] [--strategy nfc]

`OUT` holds `truth.json` (OmniDocBench's ground-truth JSON), `predictions/<page id>.md` (a page the run lacks or failed
on: an empty prediction), `export.yaml` (what was exported and with what) and a `README.md` naming OmniDocBench's own
command; OmniDocBench runs in an environment of its own (Python before 3.12).

**The formats** (`linecaster.formats.omnidocbench`): the ground truth's regions in reading order become its
elements, their roles its categories (paragraphs `text_component`, headings `title`, running heads and feet `header`
and `footer`, page numbers `page_number`, footnotes `page_footnote`, captions `figure_caption`, tables `table` with
their HTML, formula regions `equation_isolated`); a line a formula fills (an equation number may follow) is its own
`equation_isolated`, an inline formula stays in its text as `$…$`. No boxes are written: OmniDocBench scores by
text and order. A run's page is Markdown: components in reading order, a heading `#` at its level, tables as HTML,
formula regions `$$…$$`; a transcription without regions (a VLM's completion) as the model wrote it. Pages carry
the attributes `tables` (data tables) and `formulas` (`yes`/`no`, the [slices](#aggregation)), by which OmniDocBench
groups its page results.

**Which tables are tables** (`--tables`, default `data`; `linecaster.scoring.tables`), on both sides alike: a table is
`data` (printed as a table: at least two rows and two columns of filled cells, text or numbers alike), `contents` (a
table of contents or an index laid out as a table: entries with page, chapter or section references, the references
rising or the entries in alphabetical order) or `layout` (one row, one column or one cell, one column in practice, a
brace grouping lines). Only data tables are written as tables; the others are their text. `--tables all` writes every
table as a table. `--strategy` applies an output strategy to every text of both sides (`nfc` puts both in one form).

**What OmniDocBench measures** (at 7ddb8df): its text score keeps only letters, digits and CJK ideographs (`\w`), so
combining marks (Devanagari vowel signs, Arabic vowel marks, Hebrew points, Thai vowels), punctuation and spaces are
not compared, and nothing is put in NFC; predicted text that matches no ground-truth element and predicted tables that
match no ground-truth table are not counted; captions and footnotes are matched but not scored; its "overall" needs
its formula metric CDM (TeX Live) and pages with tables and formulas. Its reading-order distance is not 0 for a page
against itself where its matching splits or merges components. Its results are another view than linecaster's own
scoring, not one of its lanes; for scripts with combining marks linecaster's scoring is the measure.

## Checking a ground truth (`linecaster truth check`)

    linecaster truth check TRUTH [--transcription ground_truth] [--ids FILE] [--json OUT]

reads a ground truth's page records (a folder, local or fsspec; JSON Lines, gzipped or not, or Parquet) and reports,
per page and in total (`linecaster.scoring.truth`: `check_page`, `check`, `render`):

| Reported | Is |
|---|---|
| `lines`, `lines_with_text`, `empty_lines` | the lines, those whose reading has text, those without (no reading, or an empty one) |
| `regions`, `regions_with_box`, `boxes_outside` | the regions, those with a box, and the zones whose box lies outside the image (by more than half a pixel; the source's image size, else the page image's; none without a size) |
| `reading_order`, `unranked_regions`, `unranked_lines` | `none`, `partial` or `complete`: every region and line ranked (by an order of regions, a region's lines with it; by an order of lines, each line) |
| `conventions`, `unmapped` | the conventions its importer applied, with their hash, and what no rule of them handled (the importer's `unmapped` measurement) |
| `characters`, `illegible_characters` | the readings' characters (code points) and those with `status` `illegible` (a span, a word or a line); in total their share |
| `language`, `script`, `direction`; `languages`, `scripts`, `directions` | the value recorded on the page (`Transcription.language("")`, ...), and every value recorded anywhere on it; in total the pages without one |
| `roles`, `statuses` | the regions' content roles and the statuses, with counts |
| `tables`, `table_kinds`, `formulas` | tables with cells by kind (`linecaster.scoring.tables`: `data`, `contents`, `layout`); formulas of regions and inline (of a span) |
| `notes`, `continuations` | note regions (footnotes, endnotes) and `note_of` links; `continues` links |
| `normalized` | the normalizations the source declares it embodies |

In total also the pages whose texts are the same (whitespace aside: `duplicates`) and what the ground truth supports
(below). The text report names at most ten pages of each problem; `--json` writes everything
(`linecaster.truth-check/1`). A check changes nothing: what it finds is fixed in the source or its import.

## Benchmark definitions from the data (`linecaster benchmark init`)

    linecaster benchmark init TRUTH OUT.yaml [--id ID] [--transcription ground_truth] [--dataset REPO@REVISION]
        [--importer IMPORTER] [--sample N] [--sample-items M] [--sample-per-item K] [--seed S]
        [--stratify SCHEME] [--per-stratum K] [--split NAME:FRACTION ...] [--in-split NAME]

writes a `linecaster.benchmark/2` definition, validated, of the ground truth's pages (`linecaster.scoring.truth.benchmark`):

- `pages`: the page ids, sorted, with their `sha256`; every page, or the sample's (a sample rule, below), and then the
  rule too (`pages.rule`);
- `supports` from the data, as `truth check` finds it: `roles` every content role a region has, `boxes` where every
  region has a box, `reading_order` where every page is ordered (partly or completely), `notes` where a note region or
  link is, `continuations` where a `continues` link is;
- `dataset`: `--dataset`, else the one the sources name (all pages one); `importer`: `--importer`, else the import
  annotator's preset or engine, else the source's format;
- `lanes`: `diplomatic` and `reading`; with `--stratify`, its scheme as the benchmark's `strata`; the other fields their
  defaults.

Comment lines above it say where it was made from, the metrics the data supports besides the defaults
(`role_words` with roles, `confusion` with boxes) and, for each script recorded (a `script`, else the script subtag of a
`language`: `zh-Hans`), what the lanes and the tokenizer do with it: a script written without spaces is cut into words
by `uax29`, the default; a script whose letters take combining marks is counted by grapheme cluster, the default; a
right-to-left script is compared in the order stored. The definition is the evaluation's to edit and keep.

## Samples: strata and splits (`linecaster.data.sample`)

The sample rule (`linecaster.sample/1`) takes two optional parts; a rule without them selects, and is written and
hashed, as before:

- **splits**: named fractions of the items (`--split test:0.2 --split train:0.8`, `SampleRule(splits=..., split=...)`).
  An item is in the split where `H(f"split\t{seed}\t{item_id}") / 2**64` falls among the fractions' running sums, in
  their order: every page of an item in one split, the same split whatever else is listed, another split for another
  seed (`split_of`). A sample takes one split (`split`; `--in-split`, else the first named) and the rule's limits
  within it.
- **strata**: a page value (`stratify`) the caller supplies per page (`select(..., strata=...)`: a mapping of page ids
  or a function of the item and page id; `linecaster.scoring.truth.page_values`: a scheme recorded on the page,
  `metadata.<key>`, `source.<field>`), each value's pages a stratum sampled apart by the rule: `per_stratum` pages
  of each, or `pages` shared in proportion to the strata's pages (largest remainders, ties by the value), or the
  rule's `items` and `per_item` in each. The strata's pages together come in the order of the rule's hashes; a page
  without a value is in the stratum `""`. A stratified sample reads the whole listing.

Both are recorded in the rule (`stratify`, `per_stratum`, `splits`, `split`), and a sample's record
(`Sample.record()`) names the split hash (`split_hash`) where splits were used.

## Publishing a ground truth (`linecaster truth publish`)

    linecaster truth publish TRUTH OUT [--transcription ground_truth] [--images FOLDER | --no-images]
        [--split NAME:FRACTION ...] [--seed S] [--license LICENSE] [--name NAME] [--shard-pages 1000]

writes a ground truth's page records as a dataset the Hugging Face Hub reads (`linecaster.scoring.publish`):
`OUT/data/<split>-<n>-of-<m>.parquet`, one row per page, and a dataset card, `OUT/README.md`.

| Column | Holds |
|---|---|
| `id`, `item_id` | the page's ids |
| `image` | the page image (the Hub's `Image` feature: `bytes`, `path`): from `--images` (the file of the image's name, else of the page id), else read from the record's `image.uri`; none where it is not found |
| `text` | the transcription's literal text, as laid out (`Transcription.text`) |
| `language`, `script` | the values recorded on the page |
| `page` | the page record as JSON (`linecaster.page/N`) |

The card's front matter has the license the records record (an extension field or metadata key `<ns>__license`;
several: `other`), else `--license`, else `other`; the languages recorded (their primary subtags); the task category
`image-to-text`; the size category; and the splits as data files (by item, as above; default every page in
`train`). Its body lists the sources (`source.dataset` with page counts), the conventions with their hashes, the
languages, scripts and directions recorded with page counts, what the ground truth supports, the normalizations it
embodies (`source.normalized`), the counts, the splits, the columns, and the linecaster that wrote it.

## Run records

A run record (`OUT/run.yaml`) carries what evidence names: `run_id` (stamped on every annotator the run adds),
`pipeline_sha256`, the recipe and every catalog entry the run used with its settings and hash (`catalog`: presets,
policy, conventions, the strategies its texts were written by), `hardware` (GPU model and count, driver, CUDA, CPU)
and the software versions.
