# Glossary

The terms linecaster uses, one meaning each. Where a word means something else elsewhere (in datatrove, Haystack,
everyday use), the **not** column says so. Code, docs and commit messages use these terms and no others; a new
term is added here before it is used.

## Running things

| Term | Meaning | Not |
|---|---|---|
| **block** | One processing unit of a pipeline: a datatrove `PipelineStep`. Blocks are named as role nouns (`LineRecognizer`, `Composer`, `PageJsonlWriter`). | not a "step" (that is a catalog term), not a "component", not a "module" |
| **role** | What a block does, defined by its contract; implementations and strategies of one role are interchangeable. | |
| **family** | A group of roles of one kind: readers, layout, lines, recognition, conversion, text, composition, binding, validation, servers, writers, composites. One subpackage of `linecaster.blocks` each. | |
| **contract** | What a block reads, adds and replaces in the page record (or item record), and its unit. The builder checks contracts before a run. | not a Python type signature |
| **part** | One named piece of the page record (or item record) a contract names: page-level (`image`, `metadata`), or of one transcription (`ocr_new:lines`); the vocabulary is `PARTS` (below). | not a datatrove `Document` field |
| **unit** | What one call of a block or engine processes: `line`, `region`, `page` or `item`. | |
| **per-unit transform**, **stream transform** | The two shapes of a block: a per-unit transform processes one unit per call and its base class owns the loop; a stream transform takes the whole stream and passes each unit on when it is done, possibly out of order (served model blocks). | |
| **condition** | A picklable predicate on the page record with a `describe()`; a block with one (`when=`) processes only the pages it accepts, the others pass unchanged. Blocks sharing a group are **alternatives**: each page goes through one of them. | |
| **composite block** | A named group of blocks with its own outward contract (e.g. `ModularTranscriber`). The builder expands it into its blocks. | |
| **pipeline** | An ordered list of blocks that a stream of pages (or items) passes through, run by an executor. datatrove's sense. | not a graph of components as in Haystack |
| **graph** | The dependencies between a pipeline's blocks, derived from their contracts by the builder: for checking, drawing, and cutting into stages. It is not executed as a graph. | |
| **builder** | The code that turns a pipeline definition into stages: derives the graph, checks it, expands composites, cuts it at unit changes. | |
| **stage** | One datatrove pipeline run as part of a longer computation; stages run one after another and hand over through files (e.g. page records written in item shards, read by the next stage). | not a "phase" |
| **pipeline script** | A self-contained uv script in `pipelines/` (PEP 723 metadata, a lock next to it) that builds one pipeline shape and runs it on every executor. Named as a verb: `harvest.py`, `transcribe_modular.py`, `transcribe_vlm.py`, `bind.py`. | |
| **pipeline id** | A pipeline script's versioned id, its file name plus `.v<n>`: `transcribe_modular.v1`. Recipes name the pipeline they run by it. | |
| **workflow** | The sequence of pipeline scripts for a collection: harvest → transcribe → bind. | not one pipeline; not a GitHub Actions workflow (say "CI workflow" for that) |
| **executor**, **job**, **task**, **worker**, **shard** | datatrove's terms: the executor runs a pipeline as tasks; a job is one launch (one HF Job, one Slurm job); a task is one unit of work with its own rank; workers are tasks running at once; a shard is the part of the input one task reads. | |
| **item shard** | A folder of page records holding every page of a set of items, so that a later stage reads whole items. | not a datatrove shard |
| **backend** | Where a model block's engine runs: `in-process`, `served` (a server reached through saturate), or `chat` (an OpenAI-compatible VLM server). | not the executor |
| **server** | A process that hosts models: `linecaster serve` for engines, vLLM or SGLang for VLMs. Started by the server blocks `ModelServer` and `ChatModelServer`, which go last in a pipeline. | |
| **observer** | A callback at block boundaries (before and after a unit): taps, sampling, progress, tracing. | not a Haystack "hook" |
| **boundary step** | The step the builder puts after a block when a stage has observers: it tells them that each unit left that block and entered the next. It adds no stats. | not a block |
| **tap** | An observer that writes the page records as they pass a given block (`--tap-after`). | |
| **partial run** | A run of part of a pipeline: up to a block (`--until`), or from page records after one (`--after`). | |
| **run folder** | The output folder of a run (`OUT`): `pages/` (the page records), `rejects/`, `logs/`, `traces/`, `run.yaml`, and the files the writers produce. | |
| **run record** | `OUT/run.yaml`: the pipeline as run (every block's settings), the recipe, the command line, the executor and the software, with `pipeline_sha256`. | |
| **reject** | A page that failed a check or a step, written to `rejects/` with the reason. | |
| **trace**, **span** | OpenTelemetry's terms: a trace is one page's (or one task's) path through a run, made of spans, one per operation, with times and attributes. | not telemetry |
| **sample** | The pages that are traced: a fixed share chosen by page id, plus every page that failed. | |

## Parts

What contracts name besides the parts presets produce (`PRODUCES` in `linecaster.catalog.schema`: `regions`,
`reading_order`, `lines`, `baselines`, `text`, `words`, ...); `PARTS` holds them all.

| Part | Meaning |
|---|---|
| `image` | The page image's bytes, as the reader brought them (page-level). |
| `metadata` | The page record's own fields: ids, sequence, the image's record, the metadata (page-level). |
| `line_regions` | Lines assigned to the layout regions and ordered within them (the `LineAssigner`). |
| `hierarchy` | Heading levels, headline splits and drop capitals (the `Typographer`). |
| `nfc` | The as-written layer in one Unicode normalization form (the `UnicodeNormalizer`). |
| `document` | The DoclingDocument of a page (the `Composer`) or of an item (`BindItem`). |

## The catalog

| Term | Meaning | Not |
|---|---|---|
| **catalog** | linecaster's register of models, engines, presets, recipes and evidence, in `src/linecaster/catalog/data/`. | |
| **catalog entry** | One registered thing: a model, a preset, a recipe or an evidence record; a YAML file, with a Markdown sidecar for its prose. | not a "component", not a "document" |
| **step** | A catalog step: what an engine does, e.g. `layout`, `lines`, `recognition`, `tables`, `formulas`, `image`, `normalization`, `typography`, `recomposition`, `composition`. A preset belongs to one step. | not a block |
| **engine** | Code with a versioned id (`kraken.recognition.v1`, `recomposition.unicode.v1`) that implements one step: a class with `Options`, capabilities, `load()` and a call per unit. Built-in engines live in the core; engine packages (`linecaster-kraken`, ...) add more. | not saturate's `Engine` class (its server launcher) |
| **strategy** | An engine of a rule-based step (normalization, typography, recomposition, composition, image). A strategy declares the scripts it covers. | |
| **model** | An upstream artifact with weights (or learned data such as hyphenation patterns), pinned by revision, with its upstream card copied verbatim. | not an engine, not a preset, not a VLM adapter |
| **preset** | A named configuration of one engine for one step: engine id, options, capabilities, and the model it loads if any. Referred to as `id@edition`. | |
| **page preset** | A preset whose unit is `page`: one model reads the whole page (a VLM). `launch.py` can run one directly. | not "a model" |
| **recipe** | A tested combination: a pipeline id, a preset edition per slot, and options, with whole-run evidence. | |
| **slot** | A place in a pipeline script that a preset fills; its name is the step's (`--layout`, `--lines`, `--recognition`, ...). | |
| **adapter** | The code that talks to one VLM family over the OpenAI-compatible API: its request, its prompt handling, its parsing (`linecaster.adapters`). | not an engine package |
| **evidence** | A measurement with its source (own run, leaderboard, model card, vendor benchmark), stored as an evidence record. | |
| **version** | Upstream's name for a release of a model (`v6`, `3.5`). | not an edition |
| **revision** | The exact upstream commit a model is pinned to. | |
| **edition** | linecaster's release number of a preset or recipe: `kraken-ppocrv6-medium@1`. A released edition never changes; its hash covers its YAML. | not a version |
| **code id** | The versioned id of an engine or a pipeline: `<name>.v<n>`. An option added later keeps the id if its default keeps the old behavior. | |
| **schema id** | The format of a YAML file: `linecaster.preset/1`. | |
| **lock** | `catalog.lock`: the hash of every released edition, and the expanded pipeline of every recipe edition. | |

## Pages, items and text

| Term | Meaning | Not |
|---|---|---|
| **item** | Any multi-page unit: a book, an issue, a manuscript, a file. Key `item_id`. | not "book" in generic code, flags or docs |
| **page** | One page of an item, with its image and its named transcriptions. `page_id` is `<item_id>_<sequence:04d>` unless the source has stable ids of its own. | not the step `page` (there is none) |
| **page record** | A page with its image reference, its transcriptions and its metadata (`Page`): what a block reads and adds to while the page passes, and what is stored in `OUT/pages/` as JSONL or Parquet (everything but the image bytes). | not a "page row" |
| **item record** | An item with its pages in order, as the `Binder` passes it on. | |
| **manifest** | An item's list of its pages and their files, in order: an IIIF Presentation manifest or a METS document (also inside OAI-PMH). | not a BagIt checksum manifest |
| **page image** | The image a page's coordinates refer to (`PageImage`): its URI, format, size, hash. | |
| **working image** | The `working-image` preset of the `ImageConverter`: lossless WebP at full resolution, 8-bit sRGB. | not a role |
| **transcription** | Everything read from a page by one source (`Transcription`): regions, lines, words, paragraphs, the document, the steps that made it, and its source. Named per page: `ocr_new` (linecaster's), `ocr_original` (the library's own), `ground_truth`. | not "OCR" (it also holds HTR and ground truth) |
| **region** | An area of a page with a label (`text`, `title`, `table`, ...) from layout. | |
| **line** | One printed or written line: its geometry and, once recognized, its text and words. | |
| **row** | The lines of one region that sit side by side at the same height (`Line.row`), as in typesetting; detection often splits one printed line into several lines on the same row. | never a stored record |
| **word** | The finest unit: its text, box and confidence. linecaster has no glyph level. | |
| **paragraph** | Running text recomposed from a region's rows, with the decisions that made it. Added by the `Recomposer`. | |
| **document** | A DoclingDocument: the composed structure of a page or an item. Added by the `Composer`. | not a datatrove `Document` (say "datatrove document"), not a catalog entry |
| **step info** | One entry per step that worked on a transcription (`StepInfo`): step, engine, preset edition, backend, settings, measurements. | |
| **measurements** | Numbers a step records for a page: seconds, tokens, device, `finish_reason`, in a fixed vocabulary. | not trace attributes |
| **text variant** | A named point on the three text dimensions, written per item: `verbatim_txt`, `readable_txt`, `readable_md`. | not a "version" |
| **character fidelity**, **flow**, **scope** | The three text dimensions: as written → normalized (fidelity); as laid out → flowed (flow); full page → body only (scope). Each transform moves one step on one dimension. | not "axes" |
| **composition** | Building a document from regions and paragraphs (the `Composer`). | not "assembly" |
| **recomposition** | Turning lines back into running text: paragraphs, removed division marks, separators, continuation (the `Recomposer`). | not "reflow" (the old name) |
| **binding** | Gathering an item's pages in order into one item (the `Binder`). | |
| **division mark** | A hyphen the typesetter added where a word was divided at a line end. | not a hyphen that belongs to the word |

## The print shop

The block names follow the roles of a hot-metal print shop, in the order they work. linecaster makes a new,
digital edition of a printed item:

| Print shop | linecaster | Does |
|---|---|---|
| the linecaster (casts whole lines) | `LineRecognizer` | casts the lines anew, as text |
| typographer | `Typographer` | determines the hierarchy: headings and their levels, initials, what is text at all |
| compositor | `Recomposer`, `Composer` | recomposes the running text; makes up the page or item document |
| binder | `Binder` | binds the pages into the item |
