# Glossary

The terms linecaster uses, one meaning each. Where a word means something else elsewhere (in datatrove, Haystack,
everyday use), the **not** column says so. Code, docs and commit messages use these terms and no others; a new
term is added here before it is used.

## Running things

| Term | Meaning | Not |
|---|---|---|
| **block** | One processing unit of a pipeline: a datatrove `PipelineStep`. Blocks are named as role nouns (`LineRecognizer`, `Composer`, `PageJsonlWriter`). An HTTP server's refusal is a *block* too, always named with its host or proxy (below, **block (HTTP)**). | not a "step" (that is a catalog term), not a "component", not a "module" |
| **role** | What a block does, defined by its contract; implementations and strategies of one role are interchangeable. | |
| **family** | A group of roles of one kind: readers, layout, lines, recognition, conversion, composition, binding, validation, servers, writers, composites. One subpackage of `linecaster.blocks` each. | |
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
| **run folder** | The output folder of a run (`OUT`): `pages/` (the page records), `rejects/`, `logs/`, `traces/`, `run.yaml`, with a sample `sample.parquet` (and from manifests `manifests/`), and the files the writers produce. | |
| **sample** | The pages a run reads when it is given a sample rule (`--sample N`, `--sample-per-item K`, `--sample-items M`, `--sample-seed S`; `linecaster.data.sample`): chosen from the ids of the input's listing before any image is read, by item rank and page rank, cut after M items, K pages per item and N pages. The same input and options give the same sample whatever the tasks; it goes to `OUT/sample.parquet` and the run record. | not the trace sample; not a preset's `sampling` (decoding settings) |
| **item rank** | An item's place in the sample order (1-based): the items with pages ordered by `H(f"{seed}\t{item_id}")`, ties by id; `H` is the first 8 bytes of the SHA-256 as an unsigned big-endian integer. | |
| **page rank** | A page's place within its item in the sample order (1-based): ordered by `H(f"{seed}\t{item_id}\t{page_id}")`, ties by id. | not the page's sequence |
| **run record** | `OUT/run.yaml`: the pipeline as run (every block's parameters, `to_dict()`), the recipe, the command line, the executor and the software, with `pipeline_sha256` (the hash of the functional parameters). | |
| **resource** | A remote file of an item or of one of its pages (a catalogue record, an API's item JSON, a manifest, OCR, an image), with a kind (`marcxml`, `item-json`, ...): fetched as served by `ResourceReader` and kept as a raw copy, `<kind>/<item>/<name>.<ext>`, with a fetch record. | not a datatrove `Media` |
| **HTTP policy**, **host entry** | How a run's requests go out, from one YAML file (`--http-policy`, `linecaster.net.policy`, [http](http.md#the-http-policy)), in three levels: settings for every request at its root (rate limits, retries, deadline, User-Agent, what blocks and what stops the run, `max_pause`), the proxy path's own section (`proxies:`: the list, proxies per worker, how long a blocked or broken proxy is left out), and a host entry under `hosts:` for each host that differs, whose fields replace the root's. The run's own options go between the root and the host entries; each host's settings get their own fetcher. | not several policies |
| **broker** | A shared folder (any `DataFolder`: local, S3, ...) through which workers across tasks, runs and machines agree on who uses which shared resource and what is unavailable until when, with leases and marks (`linecaster.broker`, `--broker`, default `OUT/logs/broker`; [broker](broker.md)). Proxies are its first kind of resource. | not a message broker (no server, no queue) |
| **lease** | A worker's claim on one resource in the broker (`<kind>/<id>/leases/`): it holds the resource while it renews the lease within the lease time (180 s); one worker holds a resource at a time, and a crashed worker's leases expire on their own. | not a lock with a server |
| **mark** | A note in the broker that something holds for a resource in a scope until a time (`<kind>/<id>/marks/<scope>/`), written once and never changed, deleted by whoever sees it expired (past its `keep`, if it has one: kept readable that long after its end, for a proxy's doubling): a proxy's block at a host (scope the host), a broken proxy (scope `*`). | |
| **worker identity**, **worker slot** | Who holds leases in the broker: a datatrove worker as a slot of its machine (`<machine>-<n>`), not a process. A process claims a free slot of its machine at its first use (its search starting at its executor's worker index, so processes started together do not race) and hands it over when it ends; the next process in the slot is the same worker and goes on with its leases (on Ray every task is a new process). | not a process, not a task |
| **proxies per worker** | How many proxies of a list a worker holds at a time (`per_worker` in an HTTP policy's `proxies:` section, per host or at the root, `linecaster.net.proxies`): by default `share`, a fair share of the proxies not blocked (the free ones divided by the live workers), rebalanced as workers come and go; `1`, one, swapped for a free one when it is blocked; or up to N, claimed one by one. The run's default worker count follows it (sharing them, one worker per available proxy up to one per CPU; with `1` or N one per available proxy, divided by N; at most 64 with OUT on object storage). | not proxies per task |
| **block (HTTP)** | A host turning an IP away: a response in the host's `block_on` (429 by default; with `html` there, an HTML page where another format was expected), whether through a proxy or direct, since the server only sees an IP ([http](http.md#blocks)). Through proxies the proxy is left out for that host (a mark in the broker, until `Retry-After`, else 60 s doubling up to `block_ttl`) and the request goes on through another; direct the worker's requests to the host pause. A block is never an attempt. | not a block of a pipeline, not a failed attempt |
| **broken proxy** | A proxy that failed attempts itself (a proxy error, no connection to it) `broken_after` times in a row (3 by default): left out for every host (a mark with scope `*`), first for `broken_ttl` (300 s), doubling, at most `block_ttl`. A slow server's timeout does not count. | not a blocked proxy (that is the host's refusal) |
| **pause** | A time in which a fetcher (one per worker and host settings) sends no request to a host, or with the breaker none at all, and its requests wait instead of failing. Three things start one: a block on a direct connection, for that host, until the response's `Retry-After` has passed, else 60 s doubling while the blocks repeat, after which the request that got it is tried again (`linecaster.net.http.Pause`); the breaker during an outage; and, with a proxy list, no proxy usable for the host (every one the worker holds blocked there, none free to claim) until a block ends or another worker gives one back. The blocks' pauses and the waits for a proxy count toward the host's `max_pause` since its last successful response, and beyond it the run stops ([http](http.md#max_pause)). Other hosts' requests and other workers' fetchers go on. | not a stop of the run |
| **unexpected HTML** | A successful response (2xx) with an HTML page where an image, XML, JSON or a manifest was expected (an error page served with 200, a soft 404, a login page after a redirect): by default a failed attempt, retried and traced `200-html` (`linecaster.net.http.UnexpectedHTML`); a block or a stop where the host's policy has `html` in `block_on` or `stop_on`. | not an error status with an HTML body (a 503 page is a 503) |
| **breaker** | A fetcher's guard against an outage (`linecaster.net.http.Breaker`): when most recent attempts got a server error it pauses the fetcher's requests, sends a probe now and then, and ends the pause with the first answer that is not a server error. | not the pause after a block |
| **reject** | A page that failed a check or a step, written to `rejects/` with the reason; it stays in the page records with its errors. | |
| **image warning** | A fault of an image file that it is read around, recorded and logged as a WARNING but not failing it (`linecaster.images.image_warnings`): a PNG's optional (ancillary) chunk with a wrong checksum, left out when read (as libpng and browsers do); what Pillow warns about while reading (e.g. corrupt EXIF); EXIF that cannot be read; an ICC profile that cannot be applied. In a resource's fetch record and a converted page's image as `warnings`. | not an error: a fault that keeps the pixels from being read (a damaged header, a truncated file) fails the resource or rejects the page |
| **warm-up** | What a block loads before its first unit (`warm_up()`): an engine, a server, a client's secrets. Timed as its own stat. | |
| **error budget** | The share of a task's pages a block may fail on before the task fails (`--max-page-errors`, default 1 % of at least 100 pages). | |
| **functional parameter**, **operational parameter** | A block parameter that can change what a run writes (functional), or only where things are and how the work runs (operational: folders, ports, endpoints, windows, worker counts). `pipeline_sha256` covers the functional ones. | |
| **describe mode** | Building a pipeline shape's blocks in the current process without its engines, for its description and hash (`linecaster.runtime.run.describe`). | not `--dry-run`, which runs in the script's environment |
| **secret reference** | `EnvVar("NAME")`: a credential named by its environment variable, read in the task, never stored in a pipeline or a record. | |
| **trace**, **span** | OpenTelemetry's terms: a trace is one page's (or one task's) path through a run, made of spans, one per operation, with times and attributes. | not telemetry |
| **trace sample** | The pages that are traced: a fixed share chosen by page id (`--trace-sample`), plus every page that failed. | not the sample a run reads |
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
| `paragraphs` | The paragraphs of the rows, with the decisions that made them (the `Recomposer`): structure, no text. |
| `document` | The document of a page (the `Composer`) or of an item (`Composer(unit="item")`, `linecaster.document`): a rendering that travels with the datatrove document (`doc.metadata["document"]`), not stored in the page record. |

## The catalog

| Term | Meaning | Not |
|---|---|---|
| **catalog** | linecaster's register of models, engines, presets, recipes, rendering policies and conventions, in `src/linecaster/catalog/data/`. | not a data repository: it holds no measurements |
| **catalog entry** | One registered thing: a model, a preset, a recipe, a rendering policy or a conventions entry; a YAML file, with a Markdown sidecar for its prose (required for conventions). | not a "component", not a "document" |
| **step** | A catalog step: what an engine does, e.g. `layout`, `lines`, `recognition`, `tables`, `formulas`, `image`, `typography`, `recomposition`, `composition`, `import`. A preset belongs to one step. | not a block |
| **engine** | Code with a versioned id (`kraken.recognition.v1`, `recomposition.unicode.v1`, `import.alto.v1`) that implements one step: a class with `Options`, capabilities, `load()` and a call per unit (an image and a transcription, a transcription, or, for an importer, a source document). Built-in engines live in the core; engine packages (`linecaster-kraken`, `linecaster-mediawiki`, ...) add more. | not saturate's `Engine` class (its server launcher) |
| **transcription strategy**, **strategy** | How a text is written from the record: `literal` (the readings exactly as given, nothing changed, not even NFC) or a strategy of the catalog, normalizations in order (`latin-historic`; `nfc+long-s+flow` names an unnamed one). Applied when a text is written or compared, never stored. A text is `<strategy>:<format>` (`literal:txt`). | not a by-script strategy |
| **normalization** | One named change of a text, one rule each (a catalog entry: `long-s`, `nfc`, `flow`, `unicode-marks`, `divided-words`); a strategy names them. Nothing is normalized unless a strategy says so. | not Unicode normalization only |
| **literal** | The strategy that changes nothing: the readings as the source or model gave them, rows as laid out. A document as the builder makes it is literal. | not "diplomatic" (a lane) |
| **by-script strategy** | The engine a by-script engine routes a script's decisions to (a preset of the same step, `by_script`). Such a strategy declares the scripts it covers. | not a transcription strategy |
| **importer** | An engine of the `import` step: it reads a source document (`SourceDocument`: a file, a record, a wiki page's wikitext) into a transcription, a ground truth by default. `TranscriptionImporter` runs it. | not a reader block, which brings pages into a pipeline |
| **conventions** | A catalog entry (`conventions/<format>/<id>.yaml`, `linecaster.conventions`) that says what one public source's markup means, as rules an importer applies: each a match and a decision. An entry may extend one other, by id, and names the normalizations its source's transcription embodies (`transcription`); its Markdown sidecar is required. | not code: a source's own code never lives in linecaster |
| **match** | Where a convention's rule points, by its format family's standard (its **match kind**): a CSS selector on an HTML or XML tree (`tree`), a JSONPath on JSON (`json`), a regular expression on text (`text`). | |
| **decision** | What a convention's rule says the matched thing is, format-neutral and in the data model's vocabulary (`remove` with a reason, `block` of a role, `note`, `edit`, `cell`, ...); each importer applies the decisions it understands. | not a recomposition `Decision` (a paragraph's join) |
| **coverage** | What an importer's conventions handled on a page: matches per rule, and what no rule matched (an element's classes), in the importer annotator's measurements. | |
| **script** | A writing system, named by its ISO 15924 code (`Latn`, `Hebr`, `Arab`): Unicode's `Script` property. A by-script engine routes each decision to the strategy for the script around it; `*` stands for every script. | not a pipeline script |
| **model** | An upstream artifact with weights (or learned data such as hyphenation patterns), pinned by revision, with its upstream card copied verbatim. | not an engine, not a preset, not a VLM adapter |
| **preset** | A named configuration of one engine for one step: engine id, options, capabilities, and the model it loads if any. Referred to by its `id`. | |
| **page preset** | A preset whose unit is `page`: one model reads the whole page (a VLM, or a page engine). `launch.py` can run one directly. | not "a model" |
| **page engine** | An engine of the recognition step whose unit is the page: it reads the whole page and returns its transcription, in the pipeline's process or behind a server (`indra.recognition.v1`, `surya.recognition.v1`, and the clients of a vendor's service, `falcon.recognition.v1`, `oxr.recognition.v1`). `PageRecognizer` runs it. | not a chat preset (`chat.v1`) |
| **recipe** | A tested combination: a pipeline id, a preset per slot, and options (the texts it writes among them). | |
| **slot** | A place in a pipeline script that a preset fills; its name is the step's (`--layout`, `--lines`, `--recognition`, ...). | |
| **repair pass** | A further request for a page whose VLM completion stopped at its cap (`finish_reason` `length`): the same request with a larger cap and the repair temperature. `repair_max_tokens` gives the caps, one per pass, rising (a number: one pass); a pass is sent only while the one before stopped at its cap. The page keeps the first completion that finished, else its first. Each request of a page is a **pass**, recorded as a raw output of the transcription with its number (`pass`); `kept` says which one the annotations were parsed from. | not a retry of a failed request |
| **grounding** | A VLM's mode that labels and locates every block of the page as it transcribes it (LightOnOCR-3's `grounding` prompt: a placeholder with label and box before each block). linecaster makes one region per block, with page furniture classified as header, footer or page number; what the model writes about a figure is a description, kept apart from the text. | not a layout step: one completion holds the layout and the text |
| **repetition detection** | vLLM's guard against a completion that loops (`repetition_detection` of a request, vLLM 0.17.0 and later): the server ends a completion whose last tokens repeat a pattern of `min_pattern_size` to `max_pattern_size` tokens `min_count` times in a row, with `finish_reason` `repetition`. Such a page is not sent to a [repair pass](glossary.md). On by default for presets served by vLLM 0.17.0 or later; linecaster's defaults: 8 to 100 tokens, 16 times (a run of one token is stopped after 128). | not a repetition penalty or an n-gram logits processor, which change sampling on every page |
| **adapter** | The code that talks to one VLM family over the OpenAI-compatible API: its request, its prompt handling, its parsing (`linecaster.adapters`). | not an engine package |
| **evidence** | A measurement of a preset or recipe with its source (own run, model card, vendor benchmark), as an evidence record (`linecaster.evidence/3`) that names the run, the benchmark, the policy and the scoring it measured with (lanes and their hashes, the unit); kept by an evaluation in its own repository. | not a catalog entry |
| **version** | Upstream's name for a release of a model (`v6`, `3.5`). | not a release |
| **revision** | The exact upstream commit a model is pinned to. | |
| **release versioning** | The catalog is versioned by the linecaster release: entries carry no edition; what an entry does is identified by the hash of its functional content (`catalog.index`), and a run record lists every entry it used with its settings and hash. A reference from before 0.10 (`id@edition`) resolves to the release's entry with a warning. | not an edition |
| **code id** | The versioned id of an engine or a pipeline: `<name>.v<n>`. An option added later keeps the id if its default keeps the old behavior. | |
| **schema id** | The format of a YAML file: `linecaster.preset`. | |
| **index** | `catalog.index`: every catalog entry's hash, and each recipe's pipeline hash; generated by `linecaster catalog index`, committed, checked by `verify`. A change in it is a change of behaviour. | |

## Pages, items and text

| Term | Meaning | Not |
|---|---|---|
| **item** | A named, ordered container of one or more pages: the input names it and gives its id (`item_id`) and the pages' order (`sequence`). linecaster assumes nothing about what an item is or how its pages came about (a scanned book, an issue, a PDF, a folder of images). | not "book" in generic code, flags or docs; never "document": in datatrove and in the data-processing pipelines that filter and deduplicate text datasets a document is one record of the stream (in linecaster a page, or an item after the `Binder`); not "object" or "container" |
| **page** | One page of an item, with its image and its named annotation sets. `page_id` is `<item_id>_<sequence:04d>` unless the source has stable ids of its own. | not the step `page` (there is none) |
| **page record** | A page with its image reference, its annotation sets and its metadata (`Page`): what a block reads and adds to while the page passes, and what is stored in `OUT/pages/` as JSONL or Parquet (everything but the image bytes). | not a "page row" |
| **item record** | An item with its pages in order, as the `Binder` passes it on (`doc.metadata["item"]`, `linecaster.blocks.base.item`); the item-unit `Recomposer` and `Composer` read it, the item writers write from its document, the `Splitter` turns it back into pages. | |
| **manifest** | An item's list of its pages and their files, in order: an IIIF Presentation manifest or a METS document (also inside OAI-PMH). | not a BagIt checksum manifest |
| **page image** | The image a page's coordinates refer to (`PageImage`): its URI, format, size, hash. | |
| **working image** | The `working-image` preset of the `ImageConverter`: lossless WebP at full resolution, 8-bit sRGB. | not a role |
| **annotation** | One thing an annotator said about a page: a zone, a reading, a table, a formula, a classification, a description, an edit, a link, a reading order or a range, with its annotator, the raw output it was parsed from and what it was derived from. Never changed after it is added. | not a Python type annotation; not "observation" |
| **annotation set** | Everything one source said about one page (`AnnotationSet`): its source, annotators, raw outputs and annotations. Named per page. | not IIIF's AnnotationPage (a page of a list) |
| **transcription** | An annotation set that also holds text (`Transcription`): readings, tables, formulas, paragraphs, edits. Named per page: `ocr_new` (linecaster's), `ocr_original` (the library's own), `ground_truth`. | not "OCR" (it also holds HTR and ground truth) |
| **annotator** | One thing that worked on an annotation set (`Annotator`): a model step, a rule-based step, a delivered file, or people; with its engine, preset and recipe and their hashes, run, settings and measurements, and the linecaster that added it. | not a Python generator |
| **raw output** | One request's answer, verbatim (`RawOutput`): a completion as the model wrote it, or an engine's native result, with its finish reason and tokens. | not a parsed annotation |
| **motivation** | Why an annotation was made, one per class: `segmenting`, `transcribing`, `classifying`, `describing`, `editing`, `linking`, `ordering`, `structuring` (the W3C Web Annotation term; `transcribing` is exported to IIIF as `supplementing`). | |
| **zone** | A place on the page image an annotator found (`Zone`): a region or a line, with an id, a box and a polygon. | not a TEI `zone` element, though named after it |
| **shape** | Geometry without an annotator of its own (`Shape`): a word, a glyph, a cell. | |
| **region** | A zone from a layout step, with the annotator's own label; what it is comes from classifications. | not a "block" |
| **reading** | What a recognizer read on one line (`Reading`): its text, alternatives, words and glyphs. | not a reading order; not the `reading@1` lane |
| **glyph** | One character of a word with its box and confidence, from engines with character positions. | |
| **classification** | A value of one scheme given to a target (`Classification`): content role, production, heading level, language, script, status, picture class, code language. | not a role of a block |
| **content role** | What a region, line or range is (`role` scheme): paragraph, heading, marginalia, footnote, header, page number, ... (PAGE-XML's region types, with names of linecaster's own where PAGE has no word). | not a block's role |
| **production** | How content was made (`production` scheme): printed, typewritten, handwritten, stamped, born digital. | |
| **edit** | Another form of a target's text as the source states it (`Edit`): `corrected`, `joined` (a half of a divided word: the whole word), `expanded`, `regularized`. The target's own text stays; a strategy applies an edit when it names it. | not an edit operation of a score |
| **link** | A cross-reference between two annotations (`Link`): caption of, note of, continues, refers to. | not a URL |
| **range** | A logical unit of content (`Range`): a document, chapter, section, article, list or paragraph, stored as its pieces on each page under one id. | not a Python `range` |
| **document range** | A document within or across items (`DocumentRange`): an item holds one unless ranges say otherwise. | not a datatrove `Document`, not a page's or item's document (a rendering) |
| **reference** | A string naming an annotation in the same set (`Ref`): `<id>`, `<line>/<n>` (a word), `<ref>[<start>:<end>]` (characters), `""` (the page), `<page_id>#<ref>` (another page). | |
| **rendering policy** | A catalog entry (`policy`) that decides which annotations go into which layer of a rendering, and whose annotations count where several annotators gave one. It changes no text. | |
| **layer** | Where a rendering puts content: `body`, `furniture` (running heads and feet, page numbers), `background`, `invisible`, `notes`, `metadata`, or `none`. | |
| **region label** | The coarser word layout models and page files use for a region (`text`, `title`, `section_header`, `caption`, `footnote`, `list_item`, `page_header`, `page_footer`, `table`, `picture`, ...): each content role has one; a layout preset maps its model's labels onto them. | not the model's own label (the raw label, `Region.label`) |
| **rendering** | A document (`linecaster.document`) and its HTML, Markdown, text and JSON, ALTO, PAGE-XML, hOCR, an IIIF annotation page or a text made from an annotation set under a policy; written out, never stored in the page record. | |
| **reading order** | The order in which a page's regions and lines are read (`ReadingOrder` annotations, one per annotator that ordered the page; the latest counts unless the policy's `precedence` says otherwise), from the layout model when it learned one (PP-DocLayoutV3), otherwise computed by linecaster. | not the order of `Transcription.lines`, which is the processing order |
| **XY-cut**, **XY-Cut++** | The two ways linecaster computes a reading order for a layout model that has none: XY-cut splits the page recursively at whitespace gaps; XY-Cut++ (Liu et al., 2025) first masks titles, visuals and cross-layout regions, cuts the rest, then matches the masked regions back to their neighbours (`linecaster.data.geometry`, the layout option `reading_order`). | |
| **cross-layout region** | A text region that spans several columns (longer than 1.3 × the median region and overlapping two or more others horizontally), which XY-Cut++ masks before cutting. | not a region label |
| **line** | One printed or written line (`Line`): a zone, and once recognized its reading. | |
| **row** | The lines of one region that sit side by side at the same height (a line's row is in the reading order's `rows`), as in typesetting; detection often splits one printed line into several lines on the same row. | never a stored record |
| **word** | A word of a reading: its text, box, confidence and glyphs. | |
| **paragraph** | The bottom range: running text recomposed from rows of lines, with the decisions that made it (`Paragraph`). Added by the `Recomposer`. | |
| **block** | One unit of a page's or an item's document (`linecaster.document.Block`): a title, heading, paragraph (one across a page break when the pages say it runs on), list item, caption, note, page header or footer, formula, table or picture, with its text, formatting and origins. | not a pipeline block |
| **measurements** | Numbers an annotator records for a page: seconds, tokens, device, `finish_reason`, in a fixed vocabulary. | not trace attributes |
| **text** | A written text of a page or item: a strategy and a format (`--text latin-historic+flow:md`); none is written unless a run names it (by default the document as JSON, literal). | not a "variant" (the 0.9 name) |
| **flow** | The normalization that joins a block's rows into running text at its wraps (`Block.wraps`: the layout's breaks): by a space, or none where Unicode's line breaking joins the words; a row ending in a division mark nothing resolved joins without a space, the mark kept (`de-pends`). Other row breaks (verse) stay. | not dehyphenation |
| **scope** | Full page (with the furniture) or body only: the document's layers, chosen when it is written (`furniture`). | |
| **composition** | Building a document from regions and paragraphs (the `Composer`). | not "assembly" |
| **recomposition** | Finding the paragraphs of the rows: where a paragraph breaks and where it runs on, with the decisions (the `Recomposer`). It changes no text. | not "reflow" (the old name) |
| **binding** | Gathering an item's pages in order into one item (the `Binder`). | |
| **splitting** | Passing an item record's pages on as pages again, with what the item-level steps added (the `Splitter`). | |
| **division mark** | A hyphen the typesetter added where a word was divided at a line end. Removed only by a strategy that names a rule for it (`unicode-marks`, or a source's own marking: `divided-words`). | not a hyphen that belongs to the word |
| **decision** | One choice a recomposition made at a row end, with its reason from a fixed vocabulary: a paragraph break, a continuation. Recorded on the paragraph. | |

## Evaluation

| Term | Meaning | Not |
|---|---|---|
| **ground truth** | A transcription made or checked by people, the reference a run is scored against (`source.kind` `ground_truth`). | not "gold" |
| **anchor** | Where a zone's text comes from in the source text it was read from: characters `[start, end)` of `Source.uri`/`record` at `Source.revision` (`Zone.anchor`). | not a box: an anchor is in the source, a box on the image |
| **benchmark** | A definition of how runs are scored against one ground truth (`linecaster.benchmark/1`): dataset, page set, policy, texts, lanes, metrics, bootstrap; kept by an evaluation. | not a catalog entry |
| **lane** | A comparison strategy both sides of a comparison go through before counting (`diplomatic`, the default, `reading`, `alnum`, `alnum-nonmark`, `ascii-alnum`), named by id and recorded with its hash. | not a text |
| **score record** | One page's counts for one text and lane (`linecaster.score/1`), from which every rate is derived. | not evidence |
| **stratum** | A group of pages a benchmark reports rates for separately (a collection, a century, a script). | |

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
| **derivative** | A project built on linecaster: its own pipelines, blocks or engines, and its project-specific code, defaults and names. | not a fork |
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
