# Glossary

The words linecaster uses. Each word has one meaning. A word that needs a second meaning gets a qualifier
("content role", "datatrove `Document`") and is never used bare for it. Code, docs and commit messages use
these terms; a new term is added here before it is used.

The first four sections are the core: what you need to read any other page. The sections after them belong to
one subject each and link to the page that explains it.

## Pipelines

| Term | Meaning |
|---|---|
| **component** | One processing unit of a pipeline. Technically a datatrove `PipelineStep` with a contract. Components are named after what they do: `LineRecognizer`, `ParagraphBuilder`, `PageJsonlWriter`. |
| **step** | One kind of work in a pipeline: `layout`, `lines`, `recognition`, `tables`, `formulas`, `image`, `hierarchy`, `paragraphs`, `document`, `import`, `tagging`. An engine does the work of one step and a preset belongs to one step, so the presets of a step are interchangeable. datatrove's class is always written `PipelineStep`. |
| **contract** | What a component reads, adds, replaces and removes in the page record, with its unit and its kind (reader, writer, model, transform, server). Contracts are checked before a run starts. |
| **part** | One named piece of a page record that a contract refers to: `image`, `lines`, `text`, `paragraphs`. The [parts](#parts) table lists them. |
| **unit** | What one call of a component or an engine processes: a `line`, a `region`, a `page` or an `item`. |
| **condition** | A test on the page record. A component with a condition (`when=`) processes only the pages that pass; the others go through unchanged. |
| **composite** | A named group of components that is used like one component, with one contract (`ModularTranscriber`). |
| **pipeline** | An ordered list of components that a stream of pages passes through. A datatrove executor runs it. |
| **pipeline template** | The code that builds one kind of pipeline from options (`linecaster.templates.transcribe_modular`), with an id (`transcribe_modular.v1`). |
| **slot** | A place in a pipeline template that a preset fills. It is named after its step, and so is its flag (`--layout`, `--recognition`). No slot has a default preset. |
| **pipeline script** | A self-contained uv script in `pipelines/` that gives one pipeline template its environment and its command line. |
| **recipe** | A tested way to fill a pipeline template, as a catalog entry: a preset for each slot and the options. |
| **stage** | One datatrove pipeline run as part of a longer computation. Stages run one after another and hand over through files. A pipeline is cut into stages where the unit changes from page to item. |
| **executor**, **job**, **task**, **worker**, **shard** | datatrove's terms. The executor runs a pipeline as tasks. A job is one launch (one HF Job, one Slurm job). A task is one unit of work. Workers are tasks running at the same time. A shard is the part of the input one task reads. |
| **backend** | Where a component's engine runs: in the pipeline's process (`InProcess`), behind `linecaster serve` (`Served`), or behind an OpenAI-compatible server (`Chat`). |
| **server** | A process that hosts models: `linecaster serve`, vLLM or SGLang, or a vendor's own image. The server components `EngineServer`, `VLMServer` and `VendorServer` start one inside a task; they go last in a pipeline. |
| **run** | One execution of a pipeline over one input, into one run folder. |
| **run folder** | The output folder of a run: `pages/` (the page records), `rejects/`, `logs/`, `traces/` and `run.yaml`. |
| **run record** | `run.yaml` in the run folder: the pipeline as it ran, with every component's parameters, the recipe, the command line and the software versions. |
| **sample** | The pages a run reads when it is given a sample rule (`--sample N`). The same input and rule always give the same pages. |
| **reject** | A page that failed a check or a component. It is written to `rejects/` with the reason and stays in the page records with its errors. |
| **error budget** | The share of a task's pages that may fail in a component before the task fails. |
| **warm-up** | What a component loads before its first unit: an engine, a client. |
| **functional parameter**, **operational parameter** | A functional parameter can change what a run writes. An operational parameter only says where things are or how the work runs (folders, ports, worker counts). The run record's hash covers the functional ones. |
| **downstream project** | A project built on linecaster, with its own pipelines, components or engines. Project-specific code lives there, never in linecaster. |

### Parts

| Part | Meaning |
|---|---|
| `image` | The page image's bytes, as the reader brought them. |
| `metadata` | The page record's own fields: ids, sequence, the image's record, the metadata. |
| `transcription_file` | A transcription delivered with the page as a file (ALTO, PAGE-XML, hOCR or text). The `TranscriptionConverter` reads it into a transcription. |
| `regions`, `reading_order`, `lines`, `baselines`, `text`, `words`, ... | What presets produce (`PRODUCES` in the catalog's schema). |
| `line_regions` | Lines assigned to the layout regions and ordered within them (`LineAssigner`). |
| `hierarchy` | Heading levels, headline splits and drop capitals (`HierarchyDetector`). |
| `paragraphs` | The paragraphs of the rows, with the decisions that made them (`ParagraphBuilder`). Structure only, no text. |
| `tags` | Tags with their basis (`Tagger`). |
| `document` | The document of a page or an item (`DocumentBuilder`). It travels with the page through the pipeline and is not stored in the page record. |

## Models and the catalog

| Term | Meaning |
|---|---|
| **model** | Weights from upstream (or learned data such as hyphenation patterns), pinned to a revision. |
| **engine** | Code that does the work of one step: it loads a model and processes one unit per call. Engines have a versioned id (`kraken.recognition.v1`). Rule-based engines need no model. Built-in engines are in the core; engine packages (`linecaster-kraken`, ...) add more. |
| **preset** | A named configuration of one engine: its options and the model it loads. A preset is what you pick for a step (`--recognition kraken-ppocrv6-medium`). |
| **catalog** | linecaster's register of models, presets, recipes, normalizations, strategies, rendering policies, conventions and vocabularies. It holds no measurements. |
| **catalog entry** | One thing in the catalog: a YAML file, with an optional Markdown file for prose. |
| **revision** | The exact upstream commit a model is pinned to. |
| **code id** | The versioned id of an engine or a pipeline template: `<name>.v<n>`. |
| **index** | `catalog.index`: the hash of every catalog entry. A change in it is a change of behavior. |

## Pages, items and text

| Term | Meaning |
|---|---|
| **item** | A named, ordered container of pages: a book, an issue, a PDF, a folder of images. linecaster assumes nothing more about it. |
| **page** | One page of an item, with its image and its annotation sets. |
| **page record** | A page as stored and as passed through a pipeline (`Page`): the image reference, the annotation sets and the metadata. Components read it and add to it. |
| **item record** | An item with its pages in order, as the `ItemAssembler` passes it on. |
| **page image** | The image a page's coordinates refer to (`PageImage`). |
| **annotation** | One thing an annotator said about a page: a zone, a reading, a table, a formula, a classification, an edit, a link, a reading order. Never changed after it is added. |
| **annotation set** | Everything one source said about one page (`AnnotationSet`). |
| **transcription** | An annotation set that also holds text (`Transcription`). A page has named transcriptions: `ocr_new` (linecaster's), `ocr_original` (delivered with the page), `ground_truth`. |
| **annotator** | Who or what added annotations (`Annotator`): a model, a rule-based engine, a delivered file, or people. It records the engine, the preset, the recipe and the linecaster version. |
| **raw output** | What one request returned, verbatim (`RawOutput`): a model's completion or an engine's native result. |
| **zone** | A place on the page image (`Zone`): a region or a line, with a box and a polygon. |
| **region** | A zone found by layout analysis. |
| **line** | One printed or written line (`Line`): a zone and, once recognized, its reading. |
| **reading** | The text a recognizer read on one line (`Reading`), with its words and alternatives. Stored exactly as given. |
| **reading order** | The order in which a page's regions and lines are read. |
| **row** | The lines of one region that sit side by side at the same height. Detection often splits one printed line into several lines of one row. |
| **classification** | A value of one scheme given to a target (`Classification`): content role, production, heading level, language, script. |
| **content role** | What a region or line is: paragraph, heading, marginalia, footnote, header, page number. Always written with "content". |
| **region label** | The coarser word layout models use for a region (`text`, `title`, `table`, `picture`). Each content role maps to one. |
| **edit** | Another form of a target's text that the source itself states (`Edit`): corrected, expanded, regularized, or the whole of a divided word. The original text stays. |
| **paragraph** | Running text built from the rows of lines (`Paragraph`), with the decisions that made it. |
| **document** | The reader-facing result for a page or an item (`linecaster.document.Document`): titles, headings, paragraphs, tables and notes in order. Built from transcriptions, written as HTML, Markdown, text or JSON. datatrove's class of the same name is always written "datatrove `Document`". |
| **block** | One unit of a document (`Block`): a heading, a paragraph, a list item, a caption, a table, a picture. |
| **rendering** | Anything written from an annotation set: a document, ALTO, PAGE-XML, hOCR, a IIIF annotation page, a text. Renderings are written out and never stored in the page record. |
| **rendering policy** | A catalog entry that decides which annotations go into which layer of a rendering. It changes no text. |
| **layer** | Where a rendering puts content: `body`, `furniture` (running heads, page numbers), `notes`, `background`, `invisible`, `metadata` or `none`. |
| **normalization** | One named change of a text, as a catalog entry: `nfc`, `long-s`, `flow`. Nothing is normalized unless a strategy says so. |
| **strategy** | A named, ordered list of normalizations, as a catalog entry (`latin-historic`). It is applied when a text is written (`--text latin-historic:md`), never to what is stored. Several joined by `+` make an unnamed one (`nfc+long-s+flow`). |
| **per-script engine** | The engine that a by-script engine sends a script's decisions to: a preset of the same step (`by_script`). Its option is named `strategies`; a bare "strategy" is the catalog's. |
| **literal** | The strategy that changes nothing: the readings exactly as given. |
| **text** | A written text of a page or an item: a strategy and a format (`literal:txt`). |
| **flow** | The normalization that joins the rows of a block into running text. A division mark that nothing resolved is kept. |
| **division mark** | A hyphen the typesetter added where a word was divided at a line end. |
| **script** | A writing system, by its ISO 15924 code (`Latn`, `Hebr`). A uv script is always a "pipeline script" or "recipe script". |

## Evaluation

| Term | Meaning |
|---|---|
| **ground truth** | A transcription made or checked by people, which runs are scored against. |
| **benchmark** | A definition of how runs are scored against one ground truth: the dataset, the pages, the rendering policy, the lanes and the metrics. |
| **evaluation** | Runs scored under a benchmark, with their score records and evidence records. An evaluation lives in its own repository. |
| **score record** | One page's counts for one text and one lane. Every rate is derived from the counts. |
| **evidence record** | A measurement of a preset or recipe with its source: the run, the benchmark and the scoring it was measured with. Kept by an evaluation, never in the catalog. |
| **element** | A part of a page that is scored on its own: a region's text, a table or a formula. |
| **match group** | Elements of the ground truth and of the output that were matched to each other and are compared as wholes. |
| **lane** | A strategy both sides of a comparison go through before they are counted (`diplomatic`, `reading`, `alnum`). |
| **stratum** | The pages or elements that share one value of a dimension (content role, language, script, a tag). Rates are reported per stratum. |
| **slice** | The pages of a benchmark whose ground truth has tables, formulas, or neither, with rates of their own. |
| **split** | A named share of a ground truth's items (`test`, `train`). Every page of an item is in the same split. |
| **export** | A ground truth and a run written as another project's benchmark files (`linecaster export omnidocbench`). |

## Running at scale

Explained in [pipelines](pipelines.md).

| Term | Meaning |
|---|---|
| **item shard** | A folder of page records that holds every page of a set of items, so that a later stage reads whole items. |
| **observer** | A callback before and after each unit of a component: progress, taps, tracing. |
| **tap** | An observer that writes the page records as they leave a given component (`--tap-after`). |
| **partial run** | A run of part of a pipeline: up to a component (`--until`) or from the page records after one (`--after`). |
| **item rank**, **page rank** | An item's place in the sample order, and a page's place within its item. Both come from a hash of the seed and the ids. |
| **stratified sample** | A sample whose pages are chosen separately for each stratum. |
| **secret reference** | `EnvVar("NAME")`: a credential named by its environment variable. It is read in the task and never stored. |
| **image warning** | A fault in an image file that is read around and recorded, without failing the page: for example an optional PNG chunk with a wrong checksum, or EXIF that cannot be read. |
| **working image** | The image preset `working-image`: lossless WebP at full resolution, 8-bit sRGB. |
| **manifest** | An item's list of its pages and their files: a IIIF Presentation manifest or a METS document. |
| **resource** | A remote file of an item or a page (a catalogue record, a manifest, OCR, an image), fetched and kept as a raw copy with a fetch record. |

## Vision-language models

Explained in the [catalog](catalog.md#engines).

| Term | Meaning |
|---|---|
| **pass** | One request for a page. A page has more than one pass only when it is repaired. |
| **repair pass** | A further request for a page whose completion stopped at its token limit, with a higher limit. The page keeps the first completion that finished. |
| **repetition detection** | vLLM's guard against a completion that loops: the server ends it early. Such a page is not repaired. |
| **grounding** | A model's mode that labels and locates every text block of the page while it transcribes it. linecaster makes one region per block. |
| **adapter** | The code that talks to one VLM family over the OpenAI-compatible API: its request and its parsing (`linecaster.engines.chat`). |
| **page engine** | An engine whose unit is the page: it reads the whole page and returns its transcription (`PageRecognizer` runs it). |
| **service** | The server a page engine talks to that is neither `linecaster serve` nor a chat server: a vendor's own image. `VendorServer` starts it. |

## Ground-truth sources

Explained in the [catalog](catalog.md) and in [evaluation](evaluation.md).

| Term | Meaning |
|---|---|
| **importer** | An engine of the `import` step: it reads a source file into a transcription. |
| **source file** | The file, record or wiki page an importer reads (`SourceFile`). |
| **conventions** | A catalog entry that says what one public source's markup means, as rules an importer applies. |
| **match** | Where a conventions rule points: a CSS selector, a JSONPath or a regular expression. |
| **decision** | What a conventions rule says the matched thing is: `remove`, `text_block`, `note`, `edit`, `cell`. Also: one choice the `ParagraphBuilder` made at a row end, always written "paragraph decision". |
| **coverage** | What an importer's conventions handled on a page: the matches per rule and what no rule matched. |
| **anchor** | Where a zone's text comes from in the source text: a character range. |
| **line image** | An image of one line with its text, as line-level ground-truth datasets give them. |
| **tokenizer** | How the word metrics cut a text into words (`uax29`, `whitespace`, `characters`). A model's tokenizer is always written "the model's tokenizer". |

## Classification schemes

Explained in the [data model](data-model.md).

| Term | Meaning |
|---|---|
| **vocabulary** | A catalog entry that defines the values of one classification scheme. |
| **property scheme** | A classification scheme whose values are `yes` and `no`: `degraded`, `tiny`, `rotated`, `multi_column`, `form`. |
| **tag** | A classification in a property scheme, with its basis. No tag does not mean `no`. |
| **tagger** | An engine of the `tagging` step: rules on geometry, or a panel of models. |
| **production** | How content was made: printed, typewritten, handwritten, stamped, born digital. |
| **writing direction** | The direction a page or block is written in: `horizontal-lr`, `horizontal-rl`, `vertical-rl`, `vertical-lr`. |
| **motivation** | Why an annotation was made (`segmenting`, `transcribing`, `classifying`, ...). The W3C Web Annotation term. |
| **shape** | Geometry without an annotator of its own (`Shape`): a word, a glyph, a cell. |
| **word**, **glyph** | A word of a reading, and one character of a word, each with its box and confidence. |
| **link** | A cross-reference between two annotations (`Link`): caption of, note of, continues. |
| **range** | A logical unit of content across pages (`Range`): a chapter, a section, an article. |
| **reference** | A string naming an annotation in the same set (`Ref`). |
| **measurements** | Numbers an annotator records for a page: seconds, tokens, device. |
| **XY-cut**, **XY-Cut++** | The two ways linecaster computes a reading order when the layout model gives none. |
| **cross-layout region** | A text region that spans several columns: longer than 1.3 times the median region and overlapping two or more others horizontally. XY-Cut++ sets it aside before cutting. |

## Fetching

Explained in [HTTP](http.md) and [broker](broker.md).

| Term | Meaning |
|---|---|
| **HTTP policy** | How a run's requests go out, from one YAML file (`--http-policy`): rate limits, retries, the User-Agent, the proxies, and a host entry for each host that differs. |
| **host entry** | The settings of one host in an HTTP policy. They replace the general ones. |
| **HTTP block** | A host turning a request away because of where it comes from: a 429 by default (`block_on`). The proxy is left out for that host, or the worker's requests to it pause. An HTTP block does not count as a failed attempt. Always written with "HTTP" or of a proxy or host; a bare "block" is a document's. |
| **unexpected HTML** | A successful response with an HTML page where an image, XML or JSON was expected. A failed attempt by default. |
| **pause** | A time in which a worker sends no request to a host and its requests wait. |
| **breaker** | A guard against an outage: when most recent attempts got a server error, requests pause until the host answers again. |
| **broken proxy** | A proxy that failed several attempts in a row itself. It is left out for every host for a while. |
| **proxies per worker** | How many proxies of a list one worker holds at a time. |
| **broker** | A shared folder through which workers on any machine agree on who uses which shared thing, such as a proxy. It has no server. |
| **lease** | A worker's claim on one thing in the broker. It expires unless renewed. |
| **mark** | A note in the broker that something is unavailable until a time. |
| **worker identity** | Who holds leases in the broker: a numbered place on a machine, which outlives the processes that fill it. |

## Tracing

Explained in [tracing](tracing.md).

| Term | Meaning |
|---|---|
| **trace**, **span** | OpenTelemetry's terms. A trace is one page's or one task's path through a run, made of spans. |
| **traced pages** | The pages that get a trace: a fixed share chosen by page id (`--trace-share`), plus every page that failed. |
| **trace context** | A page's `traceparent`, given by the reader. The page's spans are its children. |
| **task span** | A span of the task's own work: a warm-up, a server start, a writer's flush. |
| **gap** | The time a component had no page in it between its first page and its last. |

## Contributing

Explained in [conventions](conventions.md) and [compatibility](compatibility.md).

| Term | Meaning |
|---|---|
| **engine API** | What an engine package may import from linecaster besides the data model: `linecaster.engines.api`. |
| **fake engine** | A deterministic CPU engine for tests, one per step (`linecaster.testing`). |
| **conformance check** | `check_engine` and `check_component`: the tests every engine and every component must pass. |
| **generated docs** | The pages `linecaster docs` writes from code, docstrings and the catalog. Never edited by hand and not in git. |
| **breaking change** | A change after which code, a command line, a stored file or a catalog reference stops working or means something else. |
| **upgrade note** | The CHANGELOG entry for a breaking change: what changed, who is affected, what to do. |

## The name

A linecaster is a hot-metal typesetting machine that casts whole lines of type. linecaster makes a new, digital
edition of a printed item, line by line.
