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
| **contract** | What a block reads, adds, replaces and removes in the page record (or item record), and its unit. The builder checks contracts before a run. | not a Python type signature |
| **part** | One named piece of the page record (or item record) a contract names: page-level (`image`, `metadata`), or of one transcription (`ocr_new:lines`); the vocabulary is `PARTS` (below). | not a datatrove `Document` field |
| **unit** | What one call of a block or engine processes: `line`, `region`, `page` or `item`. | |
| **per-unit transform**, **stream transform** | The two shapes of a block: a per-unit transform processes one unit per call and its base class owns the loop; a stream transform takes the whole stream and passes each unit on when it is done, possibly out of order (served model blocks). | |
| **condition** | A picklable predicate on the page record with a `describe()`; a block with one (`when=`) processes only the pages it accepts, the others pass unchanged. Blocks sharing a group are **alternatives**: each page goes through one of them. | |
| **composite block** | A named group of blocks with its own outward contract (e.g. `ModularTranscriber`). The builder expands it into its blocks. | |
| **pipeline** | An ordered list of blocks that a stream of pages (or items) passes through, run by an executor. datatrove's sense. | not a graph of components as in Haystack |
| **graph** | The dependencies between a pipeline's blocks, derived from their contracts by the builder: for checking, drawing, and cutting into stages. It is not executed as a graph. | |
| **builder** | The code that turns a pipeline definition into stages: derives the graph, checks it, expands composites, cuts it at unit changes. | |
| **stage** | One datatrove pipeline run as part of a longer computation; stages run one after another and hand over through files (e.g. page records written in item shards, read by the next stage). | not a "phase" |
| **pipeline shape** | One way of putting blocks together, with slots for presets: the code in `linecaster.pipelines.<name>` that adds its options, names the engines they ask for and builds its blocks, with its help text, pipeline id and slots. Named like its pipeline script and its pipeline id; a derivative's script imports it the same way. | not the blocks of one run (that is the pipeline) |
| **pipeline script** | A self-contained uv script in `pipelines/` (PEP 723 metadata, a lock next to it) that gives one pipeline shape its environment and its command line, and runs it on every executor. Named as a verb: `harvest.py`, `transcribe_modular.py`, `transcribe_vlm.py`, `bind.py`. | |
| **pipeline id** | A pipeline script's versioned id, its file name plus `.v<n>`: `transcribe_modular.v1`. Recipes name the pipeline they run by it. | |
| **workflow** | The sequence of pipeline scripts for a collection: harvest → transcribe → bind. | not one pipeline; not a GitHub Actions workflow (say "CI workflow" for that) |
| **executor**, **job**, **task**, **worker**, **shard** | datatrove's terms: the executor runs a pipeline as tasks; a job is one launch (one HF Job, one Slurm job); a task is one unit of work with its own rank; workers are tasks running at once; a shard is the part of the input one task reads. | |
| **item shard** | A folder of page records holding every page of a set of items, so that a later stage reads whole items. | not a datatrove shard |
| **backend** | Where a model block's engine runs: `in-process`, `served` (a server reached through saturate), or `chat` (an OpenAI-compatible VLM server). | not the executor |
| **server** | A process that hosts models: `linecaster serve` for engines, vLLM or SGLang for VLMs, a service for a page engine. Started by the server blocks `ModelServer`, `ChatModelServer` and `ServiceServer`, which go last in a pipeline. | |
| **service** | The server a page engine talks to that is neither `linecaster serve` nor a chat server: a vendor's page pipeline behind its own HTTP API, in the vendor's image (Falcon-OCR, OXR-1.0), or the vLLM a vendor's package attaches to (surya-ocr). A page preset's `serve` block names it; `ServiceServer` starts it. | not an operating-system service |
| **observer** | A callback at block boundaries (before and after a unit): taps, sampling, progress, tracing. | not a Haystack "hook" |
| **boundary step** | The step the builder puts after a block when a stage has observers: it tells them that each unit left that block and entered the next. It adds no stats. | not a block |
| **tap** | An observer that writes the page records as they pass a given block (`--tap-after`). | |
| **partial run** | A run of part of a pipeline: up to a block (`--until`), or from page records after one (`--after`). | |
| **run folder** | The output folder of a run (`OUT`): `pages/` (the page records), `rejects/`, `logs/`, `traces/`, `run.yaml`, and the files the writers produce. | |
| **run record** | `OUT/run.yaml`: the pipeline as run (every block's parameters, `to_dict()`), the recipe, the command line, the executor and the software, with `pipeline_sha256` (the hash of the functional parameters). | |
| **resource** | A remote file of an item or of one of its pages (a catalogue record, an API's item JSON, a manifest, OCR, an image), with a kind (`marcxml`, `item-json`, ...): fetched as served by `ResourceReader` and kept as a raw copy, `<kind>/<item>/<name>.<ext>`, with a fetch record. | not a datatrove `Media` |
| **HTTP policy**, **host entry** | How a run's requests go out, from one YAML file (`--http-policy`, `linecaster.net.policy`): settings for every host at its root (rate limits, proxies or direct, User-Agent, deadline, retries, the broker, statuses that pause the requests and that stop the run), and a host entry under `hosts:` for each host that differs, which replaces the root's fields it names. The run's own options go between the root and the host entries; each host's settings get their own fetcher. | not several policies |
| **broker** | A shared folder (any `DataFolder`: local, S3, ...) through which workers across tasks, runs and machines agree on who uses which shared resource and what is unavailable until when, with leases and marks (`linecaster.broker`, `--broker`, default `OUT/logs/broker`; [broker](broker.md)). Proxies are its first kind of resource. | not a message broker (no server, no queue) |
| **lease** | A worker's claim on one resource in the broker (`<kind>/<id>/leases/`): it holds the resource while it renews the lease within the lease time (180 s); one worker holds a resource at a time, and a crashed worker's leases expire on their own. | not a lock with a server |
| **mark** | A note in the broker that something holds for a resource in a scope until a time (`<kind>/<id>/marks/<scope>/`), written once and never changed, deleted by whoever sees it expired: a proxy's block at a host (scope the host), a broken proxy (scope `*`). | |
| **worker identity**, **worker slot** | Who holds leases in the broker: a datatrove worker as a slot of its machine (`<machine>-<n>`), not a process. A process claims a free slot of its machine at its first use (its search starting at its executor's worker index, so processes started together do not race) and hands it over when it ends; the next process in the slot is the same worker and goes on with its leases (on Ray every task is a new process). | not a process, not a task |
| **proxies per worker** | How many proxies of a list a worker holds at a time (`proxies_per_worker`, per host in an HTTP policy, `linecaster.net.proxies`): by default `share`, a fair share of the proxies not blocked (the free ones divided by the live workers), rebalanced as workers come and go; `1`, one, swapped for a free one when it is blocked; or up to N, claimed one by one. The run's default worker count follows it (sharing them, one worker per available proxy up to one per CPU; with `1` or N one per available proxy, divided by N; at most 64 with OUT on object storage). | not proxies per task |
| **proxy block** | A proxy left out for a host until a set time because the host turned it away (a 429 until its `Retry-After`, a block page, a status in `blacklist_on`): a mark in the broker. The proxy's owner stops using it there at once, and whoever claims it later sees the mark. | not a block of a pipeline |
| **pause** | A time in which a fetcher (one per worker and host settings) sends no request, and its requests wait instead of failing. Three things start one: a status in the host's `pause_on` (429 by default) on a direct connection, until the response's `Retry-After` has passed, after which the request that got it is tried again (`linecaster.net.http.Pause`; beyond `max_pause` the run stops); the breaker during an outage; and, with a proxy list, no proxy usable for the host (every one the worker holds blocked there, none free to claim) until a block ends or another worker gives one back (beyond `max_pause` the run stops). Other workers' fetchers go on. | not a stop of the run |
| **breaker** | A fetcher's guard against an outage (`linecaster.net.http.Breaker`): when most recent attempts got a server error it pauses the fetcher's requests, sends a probe now and then, and ends the pause with the first answer that is not a server error. | not the pause after a 429 |
| **reject** | A page that failed a check or a step, written to `rejects/` with the reason; it stays in the page records with its errors. | |
| **warm-up** | What a block loads before its first unit (`warm_up()`): an engine, a server, a client's secrets. Timed as its own stat. | |
| **error budget** | The share of a task's pages a block may fail on before the task fails (`--max-page-errors`, default 1 % of at least 100 pages). | |
| **functional parameter**, **operational parameter** | A block parameter that can change what a run writes (functional), or only where things are and how the work runs (operational: folders, ports, endpoints, windows, worker counts). `pipeline_sha256` covers the functional ones. | |
| **describe mode** | Building a pipeline shape's blocks in the current process without its engines, for its description and hash (`linecaster.runtime.run.describe`). | not `--dry-run`, which runs in the script's environment |
| **secret reference** | `EnvVar("NAME")`: a credential named by its environment variable, read in the task, never stored in a pipeline or a record. | |
| **trace**, **span** | OpenTelemetry's terms: a trace is one page's (or one task's) path through a run, made of spans, one per operation, with times and attributes. | not telemetry |
| **sample** | The pages that are traced: a fixed share chosen by page id, plus every page that failed. | |
| **trace context** | A page's W3C `traceparent` (`doc.metadata["trace"]`), given at the reader's boundary: the page's spans are its children, and a served block sends it with the page's request. | not "the current span" |
| **task span** | A span of the task's own work, traced for every task: the task, a block's warm-up, a server start, a reader's file, a writer's flush. | |
| **gap** | The time a block had no page in it between its first page and its last: it waited for its input (`linecaster traces`). | |

## Parts

What contracts name besides the parts presets produce (`PRODUCES` in `linecaster.catalog.schema`: `regions`,
`reading_order`, `lines`, `baselines`, `text`, `words`, ...); `PARTS` holds them all.

| Part | Meaning |
|---|---|
| `image` | The page image's bytes, as the reader brought them (page-level). |
| `metadata` | The page record's own fields: ids, sequence, the image's record, the metadata (page-level). |
| `transcription_file` | A library's own transcription delivered with the page, as a file's bytes (a document media: ALTO, PAGE-XML, hOCR or text; page-level); the `TranscriptionConverter` reads it into a transcription. |
| `line_regions` | Lines assigned to the layout regions and ordered within them (the `LineAssigner`). |
| `hierarchy` | Heading levels, headline splits and drop capitals (the `Typographer`). |
| `nfc` | The as-written layer in one Unicode normalization form (the `UnicodeNormalizer`). |
| `paragraphs` | The running text recomposed from the rows, with its decisions (the `Recomposer`). |
| `normalized` | The normalized texts of lines and paragraphs (the `CharacterNormalizer`). |
| `document` | The DoclingDocument of a page (the `Composer`) or of an item (`Composer(unit="item")`). |

## The catalog

| Term | Meaning | Not |
|---|---|---|
| **catalog** | linecaster's register of models, engines, presets and recipes, in `src/linecaster/catalog/data/`. | not a data repository: it holds no measurements |
| **catalog entry** | One registered thing: a model, a preset or a recipe; a YAML file, with a Markdown sidecar for its prose. | not a "component", not a "document" |
| **step** | A catalog step: what an engine does, e.g. `layout`, `lines`, `recognition`, `tables`, `formulas`, `image`, `normalization`, `typography`, `recomposition`, `composition`. A preset belongs to one step. | not a block |
| **engine** | Code with a versioned id (`kraken.recognition.v1`, `recomposition.unicode.v1`) that implements one step: a class with `Options`, capabilities, `load()` and a call per unit. Built-in engines live in the core; engine packages (`linecaster-kraken`, ...) add more. | not saturate's `Engine` class (its server launcher) |
| **strategy** | An engine of a rule-based step (normalization, typography, recomposition, composition, image). A strategy declares the scripts it covers. | |
| **script** | A writing system, named by its ISO 15924 code (`Latn`, `Hebr`, `Arab`): Unicode's `Script` property. A by-script engine routes each decision to the strategy for the script around it; `*` stands for every script. | not a pipeline script |
| **model** | An upstream artifact with weights (or learned data such as hyphenation patterns), pinned by revision, with its upstream card copied verbatim. | not an engine, not a preset, not a VLM adapter |
| **preset** | A named configuration of one engine for one step: engine id, options, capabilities, and the model it loads if any. Referred to as `id@edition`. | |
| **page preset** | A preset whose unit is `page`: one model reads the whole page (a VLM, or a page engine). `launch.py` can run one directly. | not "a model" |
| **page engine** | An engine of the recognition step whose unit is the page: it reads the whole page and returns its transcription, in the pipeline's process or behind a server (`indra.recognition.v1`, `surya.recognition.v1`, and the clients of a vendor's service, `falcon.recognition.v1`, `oxr.recognition.v1`). `PageRecognizer` runs it. | not a chat preset (`chat.v1`) |
| **recipe** | A tested combination: a pipeline id, a preset edition per slot, and options. | |
| **slot** | A place in a pipeline script that a preset fills; its name is the step's (`--layout`, `--lines`, `--recognition`, ...). | |
| **adapter** | The code that talks to one VLM family over the OpenAI-compatible API: its request, its prompt handling, its parsing (`linecaster.adapters`). | not an engine package |
| **evidence** | A measurement of a preset or recipe edition with its source (own run, model card, vendor benchmark), as an evidence record (`linecaster.evidence/1`), kept by an evaluation in its own repository. | not a catalog entry |
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
| **item record** | An item with its pages in order, as the `Binder` passes it on (`doc.metadata["item"]`, `linecaster.blocks.base.item`); the item-unit `Recomposer`, `CharacterNormalizer` and `Composer` read it, the item writers write from it, the `Splitter` turns it back into pages. | |
| **manifest** | An item's list of its pages and their files, in order: an IIIF Presentation manifest or a METS document (also inside OAI-PMH). | not a BagIt checksum manifest |
| **page image** | The image a page's coordinates refer to (`PageImage`): its URI, format, size, hash. | |
| **working image** | The `working-image` preset of the `ImageConverter`: lossless WebP at full resolution, 8-bit sRGB. | not a role |
| **transcription** | Everything read from a page by one source (`Transcription`): regions, lines, words, paragraphs, the document, the steps that made it, and its source. Named per page: `ocr_new` (linecaster's), `ocr_original` (the library's own), `ground_truth`. | not "OCR" (it also holds HTR and ground truth) |
| **region** | An area of a page with a label (`text`, `title`, `table`, ...) from layout. | |
| **reading order** | The rank in which a page's regions are read (`Region.reading_order`), from the layout model when it learned one (PP-DocLayoutV3), otherwise computed by linecaster. | not the order of `Transcription.lines`, which is the processing order |
| **XY-cut**, **XY-Cut++** | The two ways linecaster computes a reading order for a layout model that has none: XY-cut splits the page recursively at whitespace gaps; XY-Cut++ (Liu et al., 2025) first masks titles, visuals and cross-layout regions, cuts the rest, then matches the masked regions back to their neighbours (`linecaster.data.geometry`, the layout option `reading_order`). | |
| **cross-layout region** | A text region that spans several columns (longer than 1.3 × the median region and overlapping two or more others horizontally), which XY-Cut++ masks before cutting. | not a region label |
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
| **splitting** | Passing an item record's pages on as pages again, with what the item-level steps added (the `Splitter`). | |
| **division mark** | A hyphen the typesetter added where a word was divided at a line end. | not a hyphen that belongs to the word |
| **decision** | One choice a recomposition made at a row end, with its reason from a fixed vocabulary: a division mark removed, a hyphen kept, a paragraph break, a continuation. Recorded on the paragraph. | |

## Tests

| Term | Meaning | Not |
|---|---|---|
| **engine API** | What an engine package may import from linecaster besides the data model: `linecaster.engines.api` (the `Engine` protocol, `Capabilities`, the weight helpers). | not the HTTP routes of `linecaster serve` |
| **fake engine** | A deterministic CPU engine of `linecaster.testing` for tests, one per model step, registered under `fake.<step>.v1` by `register_fakes()` only. | never in a catalog preset |
| **conformance check** | `check_engine` (the engine protocol) or `check_block` (a block's contract against what it does, its `to_dict()`, pickling, `warm_up()` and failed pages), from `linecaster.testing`. | not a parity check |
| **marker** | A pytest marker of linecaster's tests: `gpu`, `network`, `slow`. Tests marked `gpu` or `network` skip where the device or the network is missing. | |
| **CI workflow** | `.github/workflows/ci.yml`: the core's tests and checks on a CPU, on every push and pull request to main. | not a workflow |

## Docs and changes

| Term | Meaning | Not |
|---|---|---|
| **derivative** | A project built on linecaster: its own pipelines, blocks or engines (squiddleocr). | not a fork |
| **generated docs** | The files `linecaster docs` writes from code, docstrings and the catalog when the site is built: the catalog's and the blocks' pages, the site's index and changelog, and `llms.txt`. Never edited by hand and not in git. | not the reference docs (`docs/reference/`, hand-written) |
| **block page** | The generated page of one block (`docs/blocks/<family>/<Block>.md`): its contract, backends, catalog step and presets, position, options, behavior and example. | |
| **breaking change** | A change after which code, a command line, a stored file or a catalog reference that worked before stops working or means something else ([compatibility](compatibility.md)). | |
| **upgrade note** | The entry in `CHANGELOG.md` for a breaking change: what changed, who is affected, what to do. | |

## The print shop

The block names follow the roles of a hot-metal print shop, in the order they work. linecaster makes a new,
digital edition of a printed item:

| Print shop | linecaster | Does |
|---|---|---|
| the linecaster (casts whole lines) | `LineRecognizer` | casts the lines anew, as text |
| typographer | `Typographer` | determines the hierarchy: headings and their levels, initials, what is text at all |
| compositor | `Recomposer`, `Composer` | recomposes the running text; makes up the page or item document |
| binder | `Binder` | binds the pages into the item (the `Splitter` takes them apart again) |
