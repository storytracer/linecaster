# The catalog: models, presets, recipes, policies, conventions, normalizations, strategies

The catalog describes every model Linecaster can run, how it runs it, and the tested combinations. Its entries live in one folder, `src/linecaster/catalog/data/`, shipped with
linecaster; `linecaster.catalog` reads, validates and resolves them.

```
src/linecaster/catalog/data/
  models/<id>/model.yaml, model.md        # + upstream/<revision>/ (the upstream card, verbatim)
  presets/<step>/<id>.yaml, <id>.md       # one folder per step (STEPS)
  recipes/<id>.yaml, <id>.md
  policies/<id>.yaml
  conventions/<format>/<id>.yaml, <id>.md # one folder per format; the prose is required
  normalizations/<id>.yaml                # one rule each
  strategies/<id>.yaml                    # named lists of normalizations
  catalog.index                           # generated: every entry's hash
src/linecaster/catalog/schemas/<kind>.json        # generated from the Pydantic models
```

## What the catalog holds

The catalog and its docs are organized by nine kinds: engines and pipelines (code, by versioned id) and
seven kinds of catalog entry (models, presets, recipes, policies, conventions, normalizations, strategies; a YAML
file each). The kinds of entry are one table in the code (`linecaster.catalog.registry.KINDS`: each kind's files,
format, id rule, index table and prose rule), so loading, the index and the checks of prose are the same for all.

| Kind | Is | Named | Lives in |
|---|---|---|---|
| engine | code that implements one step: runs a model, or applies rules | versioned id: `kraken.recognition.v1`, `typography.ratios.v1` | `engines/<engine>/` (a package each); `chat.v1` and the rule-based engines in linecaster (`linecaster.engines`) |
| model | one upstream artifact at pinned revisions, with its card | slug: `kraken-ppocrv6-medium` | `models/<id>/model.yaml` |
| preset | an engine, a model pin and the engine's options, ready to use | slug: `kraken-ppocrv6-medium` | `presets/<step>/<id>.yaml` |
| pipeline | code: a shape with slots and the run-anywhere command line | versioned id: `transcribe_modular.v1` (the script's name) | `pipelines/<name>.py` |
| recipe | a named combination: a pipeline, a preset per slot, options | slug: `squiddle` | `recipes/<id>.yaml` |
| policy | a [rendering policy](data-model.md#rendering): which annotations go into which layer of a rendering, and whose count where several annotators gave one | slug: `page-layers` | `policies/<id>.yaml` |
| conventions | what one public source's markup means: rules an importer applies, each a match and a decision; may extend one other entry | slug: `enwikisource` | `conventions/<format>/<id>.yaml` |
| normalization | one named change of a text, applied when a text is written, never stored | slug: `long-s` | `normalizations/<id>.yaml` |
| strategy | a transcription strategy: normalizations in order, to write texts or to compare them (a lane) | slug: `latin-historic`, `alnum` | `strategies/<id>.yaml` |

Besides these: the **index** (`catalog.index`: every entry's hash) and the **run record** (`OUT/run.yaml`, and per
page each `Annotator` of the page record: what a run resolved).

## Ids and versions

| Term | Whose | Meaning | Example |
|---|---|---|---|
| `version` | upstream | what upstream calls it, verbatim, never parsed | `PP-OCRv6 medium`, `Chandra 2` |
| `revision` | upstream | the exact identity of the files | HF commit, version DOI, git commit, sha256 |
| `.v<n>` | linecaster | the contract of an engine's options or a pipeline's slots and options | `transcribe_modular.v1` |
| `schema` | linecaster | the format of a YAML file | `linecaster.preset` |
| release | linecaster | the package version: it versions the catalog's entries too (release versioning) | `0.10.0` |

- Slugs (models, presets, recipes, policies): lowercase `[a-z0-9.-]`. They may contain upstream names
  (`deepseek-ocr-2`), never our versions. Ids are unique across presets and recipes, so a name means one
  thing.
- Code ids (`CODE_ID`): lowercase dotted names ending in `.v<n>`. An incompatible change is a new id
  (`.v2`); the old one stays registered. Adding an option is compatible when its default keeps the old
  behavior; changing a default, removing or renaming an option is not.
- A reference is an entry's `id`. What it does is identified by the hash of its functional content (the
  index; run records store it with the entry's settings). A reference from before 0.10, `id@edition`, resolves to
  this release's entry with an `EditionWarning` (`linecaster.catalog.registry.split_ref`).
- A tag or branch is resolved to a commit when a model is pinned; the tag is kept as `tag:` for information.
  Zenodo: the version DOI identifies the files, the concept DOI is information. Downloads without a commit:
  the file's sha256 is the revision.

## Files

A catalog entry is a YAML file, the data, validated strictly by `linecaster.catalog.schema` (unknown
keys are errors), and a Markdown file of the same name next to it, the prose for people (why these settings,
limitations, changes), without front matter. Tools read only the YAML; the docs generator also includes the
prose. The prose is optional, except for presets and recipes with `support: core` and conventions. The index
is YAML only, and so is an evidence record (kept outside the catalog, [below](#measurements-live-elsewhere)). Bulk data (page records,
exports) is JSON Lines or Parquet, not catalog data.

| Format | Schema id | JSON Schema |
|---|---|---|
| model | `linecaster.model` | `schemas/model.json` |
| preset | `linecaster.preset` | `schemas/preset.json` |
| recipe | `linecaster.recipe` | `schemas/recipe.json` |
| policy | `linecaster.policy` | `schemas/policy.json` |
| conventions | `linecaster.conventions` | `schemas/conventions.json` |
| normalization | `linecaster.normalization` | `schemas/normalization.json` |
| strategy | `linecaster.strategy` | `schemas/strategy.json` |
| evidence (not catalog data; its schema ships here) | `linecaster.evidence/3` (`/2` and `/1` are read too) | `schemas/evidence-3.json`, `-2`, `-1` |
| benchmark (not catalog data) | `linecaster.benchmark/2` (`/1` is read, upgraded) | `schemas/benchmark-2.json` |
| run record (`OUT/run.yaml`, not catalog data) | `linecaster.run-record/1` | `schemas/run-record-1.json` |
| page record, document (data, not catalog data) | `linecaster.page/5`, `linecaster.document/2` | `schemas/page-5.json`, `schemas/document-2.json` |

Catalog entries carry no version in their schema id: the release versions them. The data formats keep their own
versions ([compatibility](compatibility.md)).

Every YAML file names its format twice: its first line is `# yaml-language-server: $schema=<relative path to
src/linecaster/catalog/schemas/<kind>.json>` (for editors), and its field `schema` holds the schema id (for
tools). The JSON Schemas are generated from the Pydantic models (`linecaster catalog schemas`); the test suite
fails when a committed one differs from a fresh one.

YAML has 1.2 semantics, read with `ruamel.yaml` through `linecaster.catalog.yamlio`: only `true` / `false` are
booleans (`NO` stays Norwegian), and a duplicate key is an error. Values that look like numbers or versions are
quoted (`"1.0"`). Commands that write a file back (`pin`) keep its comments.

### Model (`models/<id>/model.yaml`)

| Field | Meaning |
|---|---|
| `id`, `version` | our slug; upstream's name, verbatim |
| `source` | `kind` (`hf`, `zenodo`, `git`, `url`) and `ref` (repo id, concept DOI, repository URL, download URL) |
| `pins` | one entry per upstream revision: `revision`, `tag`, `doi`, `pinned` (date), `files` (name → `sha256:<hex>`), `card`, `card_sha256`, `license_file` |
| `license` | SPDX id where there is one, else the license's own name |
| `languages`, `scripts` | ISO 639-3 (`mul` for many), ISO 15924 |
| `params` | parameter count, as upstream states it |
| `derived_from` | `ref` and `relation` (`mirror`, `converted`, `quantized`, `finetuned`) |

The upstream card is always copied, verbatim, at the pinned revision, whatever its license: Hugging Face
`README.md`, the HTRMoPo record, a repository README; a separate license file next to it. Its sha256 is in the
pin. Cards are never edited; license, languages and scripts in `model.yaml` are taken from them where they say.
A new upstream revision is a new entry in `pins`, with its own `upstream/<revision>/` folder. Model entries
are written by `linecaster catalog pin`.

### Preset (`presets/<step>/<id>.yaml`)

| Field | Meaning |
|---|---|
| `id`, `step` | the step must match the folder |
| `model` | `id` and `revision` of a model pin |
| `submodels` | further pins of a multi-model engine, by role |
| `engine` | the engine's id: `engine: kraken.recognition.v1` |
| `options` | the engine's options (its `Options` model) |
| `settings` | prompts, sampling and other request settings (chat presets; `repair`: the repair pass's `max_tokens`, 0 for off, and `temperature`) |
| `labels` | native layout label → region label, from which the layout step classifies each region's content role (the native label stays the region's `label`); unmapped labels are `text` |
| `by_script` | a by-script engine's strategies: ISO 15924 script code → preset `id` of the same step, and `"*"` → the default for every other script (required) |
| `serve` | the server it runs on: `server` (`vllm`, `sglang`, `linecaster`, `vendor`), `version` (vLLM: linecaster's, `VLLM_VERSION`, 0.30.0, unless the preset names another), `image` (for HF Jobs; vLLM: that release's `vllm/vllm-openai` image unless named), `flags`, `env`, `revision_flag`, `pin_ignore`, `server_packages`, `draft` (speculative decoding); a vendor's service also `command`, `health`, `weights_dir` ([page engines](#page-engines-and-their-services)) |
| `capabilities` | `unit` (`line`, `region`, `page`, `item`) and `produces` (the parts it adds, vocabulary `PARTS`) |
| `provenance` | `derived_from` (sources of the settings, each at a commit or revision), `authored_by`, `created` |
| `support`, `superseded_by` | see Support |

### Recipe (`recipes/<id>.yaml`)

| Field | Meaning |
|---|---|
| `id` | |
| `pipeline` | the pipeline it fills: `pipeline: transcribe_modular.v1` |
| `presets` | slot → preset `id` |
| `options` | the pipeline's options, by name (`squiddle`'s `text`: the item texts it writes, `<strategy>:<format>`) |
| `provenance`, `support`, `superseded_by` | as for presets |

A recipe's environment and entry point is its script `recipes/<id>.py` (see Pipelines, recipes and `launch.py`); a
recipe a derivative runs lives in this catalog too (`squiddle`).

### Policy (`policies/<id>.yaml`)

| Field | Meaning |
|---|---|
| `id` | |
| `description` | what the policy is for (prose, not part of its functional content) |
| `rules` | the rules, the first that matches wins: `role`, `production`, `status`, `motivation` (each left out: any) and `to`, the layer (`body`, `furniture`, `background`, `invisible`, `notes`, `metadata`, `none`); without a match, the role's default layer |
| `precedence` | per scheme (`role`, `heading_level`, ...) or `order`: the steps or annotator names whose annotations count first; the latest annotator otherwise |
| `tables`, `markdown` | what counts as a table when written out; the Markdown a rendering writes |

A policy entry is a `linecaster.data.policy.RenderingPolicy` with a `schema` and a `description` (`PolicyDoc`); the
[data model](data-model.md#rendering) says what it decides. The catalog ships `page-layers`, the policy a block
renders with unless it is given another (`DEFAULT_POLICY_REF`; in code without the catalog,
`linecaster.data.DEFAULT_POLICY`). Blocks and pipelines name a policy by `id` (`--policy`);
`linecaster.catalog.registry.rendering_policy` resolves it. A policy decides layers, never text: what a text is
written as is its strategy's.

### Normalization (`normalizations/<id>.yaml`)

One concern, one rule (`linecaster.text.normalize` for the rules on characters, `linecaster.document.strategy` for
those on a document's structure). A normalization is applied when a text is written or compared, never stored in a
record.

| Field | Meaning |
|---|---|
| `id`, `description` | |
| `scripts`, `languages` | the ISO 15924 scripts it is meant for (`*` any); BCP 47 tags (a language-specific one is never in a default) |
| `use` | `output` (a text written), `comparison` (a lane), or both |
| `subsumes` | normalizations whose effect this one includes (`nfkc`: `nfc`, `long-s`, `ligatures`), for the conventions check of scoring |
| `rule` | exactly one: on characters `unicode` (`NFC`, `NFKC`), `map` (a table; the longest key first), `patterns` (regular expressions), `case` (`fold`, `lower`), `keep` (only these characters), `whitespace` (`collapse`), `latex` (`text`: each LaTeX formula as the characters it prints); on the document `edits` (the source's corrections, expansions, regularizations applied), `divided_words: source` (a word the source marks as divided written whole), `division_marks: unicode-marks` (squiddleocr's rule, the document's words as its lexicon), `flow` (the rows of a block joined: by a space, or none where Unicode's line breaking joins the words; a row ending in an unresolved division mark joined without a space, the mark kept) |

The catalog ships the normalizations of the strategies below and of the lanes: `nfc`, `nfkc`, `long-s`,
`ligatures`, `r-rotunda`, `superscript-e`, `quotes`, `dashes`, `invisible`, `whitespace`, `casefold`, `lowercase`,
`latex-text`, `markup`, `html-tags`, `letters-digits`, `letters-marks-digits`, `ascii-letters-digits`, `editors-corrections`,
`editors-expansions`, `editors-regularizations`, `divided-words`, `unicode-marks`, `flow`. None is applied unless
a strategy names it: dividing words, dehyphenating, modernizing letter forms are a strategy's choice, never a default.

### Strategy (`strategies/<id>.yaml`)

| Field | Meaning |
|---|---|
| `id`, `description` | `literal` is built in (no normalization: the text as read) and is no file |
| `use` | `output` (a text written: `--text latin-historic:md`) or `comparison` (a scoring lane) |
| `normalizations` | the normalizations by id, in the order they apply |

`Catalog.strategy(ref)` resolves `literal`, a strategy's id, or an unnamed strategy: normalizations and strategies
joined by `+` (`latin-historic+unicode-marks+flow`), each strategy its normalizations. The catalog ships
`latin-historic` (`nfc`, `long-s`, `ligatures`, `r-rotunda`, `superscript-e`) for output and the lanes `diplomatic`,
`reading`, `alnum`, `alnum-nonmark` and `ascii-alnum` for comparison, `diplomatic` the default lane
([evaluation](evaluation.md)).

## Measurements live elsewhere

linecaster is not a data repository: the catalog holds no measurements, and neither do the docs. An evaluation
(a derivative's, an evaluation project's) keeps its own records, in its own repository, and names what it measured
by id and hash. linecaster provides the format and the tooling to produce them:

- **The evidence format** (`linecaster.evidence/3`, `linecaster.catalog.Evidence`, `schemas/evidence-3.json`): one
  measurement per file, `preset: id` or `recipe: id` with its hash, `context` (for a preset measured inside a
  pipeline: the rest of it), `source` (`own-run`, `card-claim`, `vendor-benchmark`), `dataset` (`repo@revision`, or
  a description for claims), `metrics`, `date`, `hardware`, `software` (linecaster commit, server version,
  `backend`: `in-process` or `served`), `run`, `notes`. Claims are never measurements.
- **What a measurement names:** the run record (`OUT/run.yaml`: the recipe and its hash, every block's
  parameters, `pipeline_sha256`, and `catalog`: every entry the run used, with its settings and hash) and the recipe
  and presets stamped on every annotator of every page.
- **What it measures:** the page records (every transcription with its annotators' `measurements`: seconds, tokens,
  device), the traces (`linecaster traces OUT`: time per block and page) and the per-page and per-item files.
- **Ground truth and reference transcriptions:** `ManifestReader(existing_ocr=True)` and the
  `TranscriptionConverter` read a library's own ALTO, PAGE-XML, hOCR or text into a named transcription
  (`ocr_original`, `ground_truth`, ...) of the page record, next to `ocr_new`; the writers turn page records into
  datasets (JSON Lines or Parquet page records, ALTO, PAGE-XML, hOCR, text).

- **Scoring** (`linecaster.scoring`, the [evaluation](evaluation.md)): ground truths imported as transcriptions,
  rendered under the same rendering policy as the output they are compared with, compared through lanes
  (comparison strategies), scored per page into score records (`linecaster.score/1`) and aggregated into one
  evidence record, which names the run, the benchmark (`linecaster.benchmark/2`), the policy, the scorer (the
  linecaster release) and each lane by id and hash. A benchmark
  definition lives with the evaluation, like its evidence; linecaster ships the format, never a benchmark.
  `linecaster score RUN TRUTH --benchmark FILE` scores a run (score records and an evidence record, by default in
  `RUN/scores/`), `linecaster evidence check FILES` validates evidence records and `linecaster evidence compare
  FILES` puts those scored the same way side by side.

## Release versioning: the index

The catalog is versioned by the linecaster release, as a library's code is: entries carry no edition, there is no
lock of released editions and no catalog migration. What an entry does is identified by the hash of its functional
content (`canonical_sha256`):

- **a preset's**: `step`, the model pin and every submodel pin (`id`, `revision`, `files`), `engine`, `options`,
  `settings`, `labels`, `by_script` (each strategy's id with its hash) and `serve`. Only what the YAML file states
  counts, so a new optional schema field changes no hash; the prose, provenance, support level and capabilities are
  not part of it;
- **a recipe's**: its pipeline, each slot's preset with its hash and the options it states; the index also keeps
  `pipeline_sha256`, the hash of the pipeline its script builds from them (below);
- **a policy's**: everything but its `description`;
- **conventions'**: the format, the resolved rules (each rule's id, match, decision, fields, who and place) and the
  normalizations the transcription embodies (`transcription`);
- **a normalization's**: its rule; **a strategy's**: its normalizations, each with its hash, and its use.

`linecaster catalog index` writes every entry's hash to `catalog.index` (committed, never edited by hand);
`linecaster catalog verify` fails when it is stale. So a change of an entry's behaviour is a visible line in a
review's diff, and the release's CHANGELOG names every entry whose hash changed (**Changed outputs**). A run is
reproducible by its release (`linecaster==0.10.0` reruns 0.10.0's entries) and by its run record, which lists every
entry it used with its settings and hash (`catalog`: kind, id, sha256, settings). Model pins (revision and file
hashes) stay as they were: they identify weights, not behaviour of ours.

### A recipe's expanded pipeline

A recipe names a pipeline id, presets and options; what runs is the pipeline its script builds from them.
`catalog index` builds each recipe's pipeline (its pipeline script with `--recipe id` on placeholder folders,
in-process, one task) and records its `pipeline_sha256`, the hash a run record of that recipe names; `verify` builds
it again, so a block, a parameter or a default that changed in code shows in the index.

Building it needs no engine: the **describe mode** (`linecaster.runtime.run.describe`) builds the recipe's pipeline
shape (`linecaster.pipelines`) in the current process, and blocks and backends import no engine before
`warm_up()`; a preset whose engine is not installed names the engine's class from the repository's engine packages
(`catalog.code`). So `verify` runs in the core environment, and its hash is the one a run of the pipeline script
with its engines records.

### Conventions (`conventions/<format>/<id>.yaml`)

What one public source's markup or export means (a wiki's templates and classes, a TEI customization, a
repository's PAGE-XML profile), declaratively, in the format `linecaster.conventions` (`linecaster.markup`). Its
Markdown sidecar is required, with the headings `## Source`, `## How the markup works`, `## Not in the rules` and
`## Open questions`: what the rules cannot say neatly.

| Field | Meaning |
|---|---|
| `id` | |
| `format` | the format whose importer applies it (`html`, `xml`, `json`, `text`, ...); its folder |
| `extends` | the parent entry, by id: the entry starts from the parent's resolved rules |
| `description`, `source` | what it is for and what it was written against (prose, not functional) |
| `rules` | each: `id`; `match` (`kind: tree` with a CSS selector and the conditions `text`, `style`, `inside`, `not_inside`; `kind: json` with a JSONPath, RFC 9535; `kind: text` with a regular expression); `decision` and its `params` (`linecaster.markup.decisions`: `remove` with a reason, `invisible`, `unwrap`, `block` with a role, `cell`, `picture`, `caption`, `note`, `edit`, `language`, `format`, `break`, `continues`, `runs_on`, `describe`); `by` (`people`, who marked it in the source, or `rule`); `before`/`after` a rule id; `why`, `decided`, `open` |
| `disable` | a parent's rule id → why this source does not use it |
| `transcription` | the normalizations the source's transcription already embodies (normalization ids: `long-s` when it writes ſ as s); a child's list replaces its parent's. Importers copy it into `Source.normalized`; scoring warns where a lane does not apply one ([evaluation](evaluation.md#conventions)) |

**Layering.** A child's rule with a parent's id replaces it where it stands (or moves it, with `before`/`after`), a
new id is added at the end (or before/after a rule), `disable` removes the parent's; every entry of a chain has the
same format. `Catalog.conventions(ref)` resolves the chain into a `ResolvedConventions`: the rules in order, the
chain (`mediawiki>enwikisource`), the normalizations of its transcription (the nearest entry's) and the hash of what
the rules do (format, matches, decisions, fields, who, the transcription's normalizations; not the documentation). An importer records both in its annotator (`conventions`, `conventions_sha256`): two readings applied
the same rules when the hashes are equal.

**Checks** (`linecaster catalog verify`): resolvable; every decision applied by its format's importer; the
transcription's normalizations known; its prose and headings; across the children of one parent: a rule all of them
repeat belongs in the parent (promotion), an override equal to what it replaces is redundant.

Conventions are the one kind of entry that names a source: they are declarative, opt-in (nothing applies them
unless a run or ground truth names them), say what a source's markup means rather than what one dataset
counts, hold no copied pages (tests use fixtures written for them), and keep the source's name inside the entry.

## Steps, capabilities, labels

Steps (`STEPS`): `layout`, `lines`, `recognition`, `tables`, `formulas`, whose engines run models, and the
rule-based steps (`RULE_STEPS`) `image` (the working image), `typography` (the hierarchy from type sizes),
`recomposition` (the paragraphs of the rows: structure, no text),
`composition` (the document) and `import` (a source document read into a transcription: the importers). Recognition reads a `unit` (`capabilities.unit`): `line` (kraken, PaddleX,
Tesseract), `region` (a VLM per layout region) or `page` (a VLM or a page engine reads the whole page: a **page preset**, which
`launch.py` runs by name); a rule-based engine reads a `page` or an `item` (the pages of one item, in order).
`OCRD_STEPS` maps the steps to OCR-D's functional steps for METS agents where OCR-D has one (`image`:
`preprocessing/optimization`, `typography`: `layout/segmentation/classification`, `composition`:
`layout/analysis`); the others are post-processing (`recognition/post-correction`).

What depends on the code belongs to the engine (`capabilities` on the class), e.g. kraken's word boxes with
confidences. What depends on the weights belongs to the model or preset: languages, scripts, output format.

## Engines

An engine is a class registered under its id in the entry-point group `linecaster.engines`
(`"kraken.recognition.v1" = "linecaster_kraken:KrakenRecognitionEngine"`), or one of linecaster's own
(`BUILTIN_ENGINES`): `chat.v1` (VLM presets, served only: `SERVED_ONLY`; the `Chat` backend), the single-region
layout and the rule-based engines. It declares
`engine_id`, `step`, `Options` (a Pydantic model whose fields have descriptions; the docs come from it) and
`capabilities`, and takes the pin as `weights` (and `submodel_weights`), fetched and checked by
`linecaster.catalog.fetch`. Engine packages carry code only; their presets and models are in this catalog.

`chat.v1`'s `Options` (`linecaster.adapters.ChatAdapter.Options`) are what a run may set over a chat preset's
settings (`Chat(..., overrides=...)`, `--set recognition.<option>=<value>`): `max_tokens`, `temperature` and
`top_p` over `settings.sampling`, `repair_max_tokens` and `repair_temperature` over `settings.repair` (the
[repair pass](glossary.md); off unless `repair_max_tokens` is above 0, which must then be larger than `max_tokens`;
a list of rising caps is one repair pass each; `lightonocr-3-0.8b` sets `[8192, 12288]`, the other presets leave it
off), and `repetition_detection` over `settings.sampling.repetition_detection` ([repetition detection](glossary.md):
on by default wherever the preset's server is vLLM 0.17.0 or later, `false` off, `true` the defaults,
`repetition_detection.<field>=<value>` for one of `min_pattern_size`, `max_pattern_size`, `min_count`; refused
for another server).

**Engine packages** (`engines/<engine>/`: `linecaster-kraken`, `linecaster-paddlex`, `linecaster-tesseract`,
`linecaster-indra`, `linecaster-surya`, `linecaster-services`) have
versions of their own and a range of linecaster releases they work with (`linecaster>=0.8,<0.10`), and import from
linecaster only the data model (`linecaster.data`) and the engine API (`linecaster.engines.api`): the `Engine`
protocol, `Capabilities`, and the weight helpers `weights_of` (a model pin as `weights`), `hf_file` and
`hf_snapshot` (a Hugging Face pin's files, checked) and `model_entry` (a model's catalog entry);
`tests/test_import_rule.py` reads the packages with `ast` and fails on any other import. They are not on PyPI: a
preset whose engine is not installed is a `CatalogError` that names the package that provides it and the pipeline
scripts whose environments install it (`catalog.code.install_hint`). Each package has its tests in
`engines/<engine>/tests/` (conformance through `linecaster.testing.check_engine`, and its own units), run in an
environment that has it (`uv run tests/test_engines_catalog.py engines/<engine>/tests`; the page engines'
packages: `uv run tests/test_page_engines_catalog.py engines/<engine>/tests`, the environment of
`pipelines/transcribe_page.py`).

### Page engines and their services

A page engine is an engine of the recognition step whose unit is the page (`capabilities.unit: page`): it gets the
page image and returns the page's transcription, text-only, its raw output verbatim as a raw output (`RawOutput`),
as a chat preset's completion is kept. `PageRecognizer` runs it like any model block (`InProcess`, or `Served` through
`linecaster serve`); `pipelines/transcribe_page.py` is its pipeline. Where the engine talks to a **service**, its
preset's `serve` block names it and `ServiceServer` starts it in the task:

| `serve.server` | The service | Fields |
|---|---|---|
| `vllm` | `vllm serve <the model pin, fetched> --host --port <flags> --served-model-name <the Hugging Face id>`, for an engine package that attaches to vLLM (`surya.recognition.v1`) | `version`, `image`, `flags` |
| `vendor` | a vendor's page pipeline in its own image (`falcon.recognition.v1`, `oxr.recognition.v1`): the image's entrypoint | `image` (by digest), `command` (the entrypoint), `env`, `health` (loopback URLs that must answer 200, in order), `weights_dir` (where the model pin is downloaded first, when the image reads the weights from a folder) |

The engine's `endpoint` option (where its service is) is operational: presets leave it to its default (the service's
loopback port), a pipeline sets it for a running service (`--recognition-endpoint`), and the pipeline's hash leaves
it out.

### The single-region layout

`layout.single-region.v1` (`linecaster.engines:SingleRegionLayoutEngine`, preset `single-region`) is a layout
engine without a model: one region covering the page image (label `text`, classified as a paragraph, id `page`; both
options), alone in a reading order, by an annotator of kind `rule` and step `layout`. It has the model engines' call (`__call__(image, transcription)`), so
`LayoutDetector("single-region")` runs it, and like the rule-based engines it is built in and runs in the
pipeline's process only. `pipelines/transcribe_modular.py --layout single-region` reads a page as one region.

### Rule-based engines

The engines of the rule-based steps (**strategies**) live in `linecaster.engines`, are pure Python and run in the
pipeline's process only (`IN_PROCESS_ONLY`; `linecaster serve` refuses them): `image.webp-lossless.v1`,
`typography.ratios.v1`, `recomposition.unicode.v1`, `composition.linked.v1` and the by-script engine
`recomposition.by-script.v1`. None of them changes a text: they add structure (headings, paragraphs, links), and a
strategy writes the text when it is written. Each has no weights; its
`Options` turn the rules' thresholds into options whose defaults are the values the rules have always had, and it
declares `scripts`: the ISO 15924 scripts it covers (`Latn`, `Hebr`, ...), `"*"` for all. The rules themselves stay
in `linecaster.text`, `linecaster.images` and `linecaster.formats`; the engines are thin.

The call per unit (`linecaster.engines.base`): page unit `__call__(t: Transcription, **options) -> Transcription`;
item unit `__call__(pages: list[Transcription], **options) -> list[Transcription]` (an item's pages in order; a page
is an item of one page); the image step takes and returns the image's bytes (`__call__(data, **options) -> (bytes,
info)`). Options given to a call override the engine's for that call. Each call appends an annotator (`Annotator`,
kind `rule`) with its `engine` id, its options as `settings` and its counts as `measurements`; the block that runs
it adds the preset and its hash, `seconds` and `datetime`. Composition is the exception: it renders the set
as a document (`linecaster.document`) and adds no annotator and no annotation. Its item unit is `item_document(pages, name, ...)`:
an item's document is no transcription.

Their blocks take a preset (`id`) or an engine spec (`InProcess("module:Class", **options)`), with `options`
over either, like model blocks but without a backend choice: `ImageConverter(output_folder, preset)` (`image`),
`Typographer(preset)` (`typography`), `Recomposer(preset,
unit="page"|"item")` (`recomposition`), `Composer(preset, unit="page"|"item")` (`composition`). The presets of the
`squiddle` recipe's rules: `working-image`, `ratios`,
`unicode-recomposition`, `linked-composition`. Running text or the page as laid out is the presence of a
`Recomposer`: the `Composer` composes from paragraphs when there are, else from lines (diplomatic composition).

### Scripts and dispatch

A preset whose engine is a by-script engine names its strategies in `by_script`: an ISO 15924 code per script that
needs its own rules, `"*"` for every other script.

```yaml
id: hebrew-latin-recomposition
step: recomposition
engine: recomposition.by-script.v1
by_script:
  Hebr: hebrew-recomposition
  "*": unicode-recomposition
```

`engine_spec` resolves them into the engine's `strategies` (each strategy's engine, options, id and hash).
The engine (`ScriptDispatch`) routes each decision to the strategy of the script around it: for a decision at a row
end (a division mark, the separator between two rows) the script of the last character before the row end that has
one, else of the first after it (characters of the scripts Common and Inherited, such as spaces, hyphens, digits and
combining marks, have none). A script without a strategy of its own goes to `"*"`. Scripts are
Unicode's `Script` property, matched with the `regex` package's `\p{Script=...}`. `verify` checks that every
strategy is a preset of the same step and covers its script. (These by-script strategies are presets of a step;
transcription strategies, the catalog kind, are another thing.)

## Pipelines, recipes and `launch.py`

Every pipeline script declares `PIPELINE`, its id: its file name with `.v<n>` (`harvest.v1`,
`transcribe_modular.v1`, `transcribe_vlm.v1`, `transcribe_page.v1`, `bind.v1`). A script with slots also declares `SLOTS` (slot →
option; the option is the step's name: `--layout`, `--lines`, `--recognition`, ...; the rule-based steps are slots
too: `transcribe_modular.v1` has `--typography`, `--recomposition` and `--composition`, `bind.v1`
`--recomposition` and `--composition`; a slot left empty leaves its step out, e.g. no recomposition: the page stays
as laid out). It has no default presets: the user fills every slot, or names a recipe (`--recipe id`), with single
flags on top recorded as overrides in the run record (`recipe`: the id, the pipeline id, the hash and the
overrides). The texts a run writes are no slot: `--text <strategy>:<format>` names each (a recipe may name them in
its `options`).

The recipe: `squiddle` (`transcribe_modular.v1`: PP-DocLayoutV3, PP-OCRv6 line detection and kraken's PP-OCRv6
recognition, tables, formulas and the rule-based steps). The item stage (`bind.v1`) has no recipe: its presets are
named (`--recomposition unicode-recomposition --composition linked-composition`, and the texts with `--text`). A
recipe has its script,
`recipes/<id>.py` ([architecture](architecture.md#recipe-scripts)): its environment, with exactly the engine packages
its presets need, and its entry point. `recipes/squiddle.py` is the environment with kraken;
`pipelines/transcribe_modular.py` leaves kraken out.

`uv run launch.py NAME IMAGES OUT [options]` launches a recipe or a page preset by name: a recipe runs its script
`recipes/<id>.py`, a page preset the pipeline script of its kind (`transcribe_vlm.v1` for chat page presets,
`transcribe_page.v1` for page engines' presets), each in its own environment, with `--recipe` or `--recognition`. `serve` and `ray` pass through for recipes. A preset that is one step
of a pipeline gets a hint instead: the pipeline, the flag and the recipes that use it.

## Support

`core` (maintained, validated), `experimental` (works, may change), `legacy` (kept resolvable;
`superseded_by:` names the replacement).

## Commands

| Command | Does |
|---|---|
| `linecaster models [--step STEP]` | lists the presets (and the recipes) |
| `linecaster catalog pin ID --hf REPO [--revision REV]` | pins a Hugging Face model: model entry, card, file hashes |
| `linecaster catalog pin ID --github OWNER/NAME --revision COMMIT --file F [--tag T]` | pins files of a GitHub repository |
| `linecaster catalog index` | writes `catalog.index`: every entry's hash, and each recipe's pipeline hash |
| `linecaster catalog verify` | checks the files (schema lines, prose next to its YAML file), the JSON Schemas against the models, cards, pins, the index (stale: a failure), conventions, recipes and their expanded pipelines |
| `linecaster catalog show REF` | the resolved functional content of a preset or recipe, with its hash |
| `linecaster catalog schemas [--out DIR]` | regenerates the JSON Schemas (default `src/linecaster/catalog/schemas/`) |
| `linecaster docs [--out docs] [--readme README.md]` | writes the generated docs (the catalog's pages among them; not in git, written before the site is built) |

The catalog's generated pages are grouped by kind: `docs/catalog/{engines, models, presets/<step>, pipelines,
recipes, policies, conventions, normalizations, strategies}/` and an index. Engine and pipeline pages are read from the source (`linecaster.catalog.code`, with
`ast`), so the engines need not be installed. The pages quote no measurements.
