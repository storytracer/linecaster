# Tracing

Every run is traced with OpenTelemetry (`linecaster.tracing`): spans per task always, spans per page for a sample
chosen by page id plus every page that failed. Traces go to the run folder and, when the standard `OTEL_*`
variables say so, to an OTLP endpoint; nothing is sent anywhere else. Terms are the [glossary](glossary.md)'s.

## What is traced

**Task spans**, for every task:

| Span | What it covers | Attributes (besides `linecaster.block`) |
|---|---|---|
| `linecaster.task` | the task, from its first page to its end (failed: status error, `linecaster.error.type`) | `task`, `tasks`, `sample`, `stage`, `units.failed_exported` |
| `linecaster.warm_up` | a block loading its engine or client (`warm_up()`), per block that loads something | `block.name`, `preset`, `edition`, `engine`, `model`, `backend`, `server` |
| `linecaster.server.start` | a server block's warm-up: starting `linecaster serve` or vLLM/SGLang until it answers | `server`, `model`, `preset`, `port` |
| `linecaster.reader.file` | a file a reader is through: a Parquet file, a file of page records, a manifest (wall time, while its pages also passed the later blocks) | `file`, `pages`, `seconds.own` (the time spent reading) |
| `linecaster.writer.flush` | a page record writer closing its files (a remote file is uploaded then) | `files` |

An image folder's file is one page: its reading is the page's, not a task span.

**Unit traces**, one per page (or item):

| Span | Parent | What it covers |
|---|---|---|
| `linecaster.page` (`linecaster.item` for items a binder makes) | none: the trace's root | from the reader (or the earliest fetch for it) to the end of the stage's last block |
| `linecaster.http.fetch` | the page | each http(s) request a reader made for it: `http.host`, `http.status`, `http.attempts`, `http.retries`, `http.wait_seconds` (the rate limits' wait), `http.tries` (each attempt: a status such as `200` or `429` for a response read whole, `200-cut` for one the deadline per attempt cut, `no-response` for a timeout or a connection or proxy error), `http.what` (`image`, `ocr`) |
| `linecaster.block` | the page | one per block, from the boundary before it to the one after it: for a served block it includes the time the page waited in the window |
| `linecaster.request.prepare` | the served block's span | building the request (image encoding), in saturate's prepare threads |
| `linecaster.request` | the served block's span | from the built request to its result: the wait for a window slot, the HTTP call, retries; `tokens.prompt`, `tokens.completion`, `finish_reason` |
| `linecaster.serve.decode`, `linecaster.serve.queue`, `linecaster.serve.model` | the request | in `linecaster serve`: the image decoded and the transcription read, the wait for the model's worker, the model call (`lines`, `regions`, `words` of its result) |

A page's spans are children of its context explicitly, never of "the current span": pages are interleaved in the
stream. A page that leaves the stage's blocks through a binder ends its trace there; the items get their own. A
page that never reaches the end of the stage (a block dropped it) is ended when the task ends
(`linecaster.unfinished`).

A failed page (an entry added to `doc.metadata["errors"]` in this stage) has status error on its root and on the
block's span, with `linecaster.error.type`.

**Attributes** are identifiers and numbers under `linecaster.*`, never text or images: `block` (class), `block.name`
(datatrove name), `block.family`, `unit`, `page.id`, `item.id`, `step`, `preset` and `edition` (of `id@edition`),
`engine`, `model`, `backend` (`in-process`, `served`), `server` (the endpoint), counts on a block's span as the
page leaves it (`lines`, `regions`, `words` of the block's transcription), `tokens.prompt`, `tokens.completion`,
`finish_reason`, `error.type`, `region` (a region recognizer's request). The resource of every span: `service.name`
(`linecaster`), `service.version`, `host.name`, `linecaster.process` (`pipeline`, `serve`), `linecaster.run` (the
run folder's name, or `LINECASTER_RUN`), `linecaster.task`, `linecaster.tasks`, `linecaster.stage`,
`linecaster.gpu` and `linecaster.gpus` (from the NVIDIA driver, when there is one); `OTEL_RESOURCE_ATTRIBUTES` adds to them.

Log records carry `trace_id` and `span_id` in `extra` (JSON lines on Jobs show them): the page a record names by
`page_id`, else the span of the per-unit block running in the thread, else the task's span.

## Sampling

`--trace-sample SHARE` (`build(..., trace_sample=)`, default 0.01): a page is sampled when a hash of its id
(BLAKE2b, 64 bits) is below `SHARE`, so the same pages on every rerun and machine, and a larger sample contains a
smaller one. `0` traces only failed pages and the task spans; `1` traces every page. A sampled page's record
carries its trace id (`page.metadata.trace_id`), so the page records lead to the trace.

Every page gets a trace context (`doc.metadata["trace"]["traceparent"]`, W3C, flags `01` for a sampled page, `00`
otherwise). The spans of an unsampled page are recorded but not sampled and held per page in a span processor
(`linecaster.tracing.export.PageBuffer`) until the page's root ends: if the page failed in the stage they are
exported, otherwise dropped. The memory this takes is bounded by the pages in flight: about 3 KB per ended span,
one per block and two per request (about 40 KB per page for the twelve blocks of the squiddle recipe). In-process a
page or two are in flight; a served block holds at most its window and its result queue (`max_window` + 4 ×
`max_window` pages), so with the default window of 32 and five served blocks about 800 pages, some 30 MB. A page
dropped by a block is held until the task ends. `linecaster serve` records nothing for an
unsampled page: a failed unsampled page's trace has the pipeline's spans, not the server's.

## Where traces go

- **The run folder**, always: `OUT/traces/<rank>.jsonl.gz` per task (`OUT/traces/<stage>/<rank>.jsonl.gz` with
  several stages), any fsspec folder like the logs; `linecaster serve` started by a task (`ModelServer`) writes
  `<rank>.serve.jsonl.gz` next to it (the task gives it the file in `LINECASTER_TRACES`). The format is
  OpenTelemetry's file exporter format: one `ExportTraceServiceRequest` per line in the OTLP JSON encoding, gzipped.
  Spans are written in batches (every 2 s), each flushed to the file, which is closed (uploaded, for a remote
  folder) when the task ends, also when it fails; a process killed outright loses its last batch, and
  `linecaster traces` reads such a file as far as it goes. A rerun of a task replaces its file. `linecaster serve`
  closes its file when it is stopped (the first SIGTERM or SIGINT ends it gracefully; its handlers are set again
  after the engines load, since an engine's library may replace them).
- **An OTLP endpoint**, when `OTEL_EXPORTER_OTLP_ENDPOINT` or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set (and
  `OTEL_TRACES_EXPORTER` is not `none`): OTLP over HTTP (protobuf), configured by the standard variables (headers,
  timeouts). `linecaster serve` exports there too; `ChatModelServer` starts vLLM with `--otlp-traces-endpoint` and
  `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf`.

Without a run folder (`run_pages`, tests) and without OTLP nothing is traced.

**The trace context and the servers.** saturate sends the same headers with every request, so a served block puts
the page's `traceparent` into the request body (`"traceparent"`), which `linecaster serve` reads (as it reads the
header, if a client sends one). An OpenAI-compatible chat server reads it from the headers only: vLLM continues a
`traceparent` header when started with `--otlp-traces-endpoint`, so with OTLP configured its spans reach the
backend, but as traces of their own, not joined to the pages'.

## The command

```
linecaster traces OUT [--by block|preset|task] [--slowest N] [--json]
```

reads `OUT/traces/**/*.jsonl.gz` (a task still running: what its file has so far) and prints:

- per block (or preset edition, or task) the duration of its `linecaster.block` spans over the traced pages (n,
  p50, p90, p99, errors); for served blocks the split: `prepare`, `request` (as the pipeline saw it), and the
  server's `queue`, `decode` and `model`;
- the **gaps**: per block the time it had no page in it between its first page and its last (it waited for its
  input), when every page was traced (`--trace-sample 1`);
- the `N` slowest traced pages (default 10) with their id, seconds, lines, slowest block and trace id;
- per task its duration, GPU and sample, the warm-up of each block and the server starts, the reader's files
  (pages, seconds reading) and the writers' flush.

`--json` gives the same as data.
