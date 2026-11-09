# Changelog

All notable changes to linecaster. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
each release lists upgrade notes first, then additions, changes, deprecations, removals and fixes. Versions follow
the tags; the first is `v0.1.0`.

## Unreleased

### Upgrade notes

- With a proxy list each worker holds **one proxy at a time** by default, not a fair share of the free ones: it sends
  every request through it and, when it is blocked or broken, releases it and claims another free one at once. A
  run that relied on several proxies per worker (few workers, many proxies) uses only as many proxies as it has
  workers now; give it more workers (below), or set the new HTTP-policy key `proxies_per_worker` (per host or at the
  root; also `HTTPFetcher`'s and `ProxyPool`'s parameter): a whole number `N` (up to N per worker, claimed one by
  one) or `share` (the fair share with rebalancing as before, except that a worker claims at most 2 when it looks
  for proxies and grows to its share only by rebalancing, so the first workers no longer take the proxies of those
  still starting). Hosts that use one proxy list must set the same value.
- The default worker count of a pipeline without engines whose rate-limited hosts all go through proxies follows the
  proxies: one worker per available proxy (those in the file, less those blocked or broken in the broker for the
  run's hosts and those held by another run's live workers), at most one per task, divided by `proxies_per_worker`
  (`ceil(available / N)`; `share` keeps one worker), and no longer capped by the CPUs. A harvest with 250 proxies and
  no `--workers` now runs 250 worker processes; give `--workers` to run fewer. The run states the count and why
  (`250 proxies available → 250 workers, 1 proxy each`). A host with rate limits and no proxy list keeps one worker.
- `linecaster.runtime.local.LocalExecutor`'s `note` may be a list of lines; `linecaster.runtime.run.rate_note`
  counts the proxies in use (`1 of 2 proxies in use (1 proxy per worker)`) when the workers hold fewer than the list.
- A worker process no longer claims the lowest free worker slot of its machine: it starts at its executor's worker
  index (`linecaster.broker.set_worker_index`, set by `LocalExecutor`, `RayExecutor` and `JobsExecutor`), else at a
  random slot, takes a handed-over slot first and probes upward from there, so slot numbers no longer say in which
  order the processes came. Code that starts brokers itself and expects `<machine>-0` first passes
  `Broker(..., worker_index=(0, 1))`.
- A broker's renew logs a lost claim race (two claims at once both believed they won) at INFO, `worker X lost a claim
  race for proxies/<id> to Y; it takes another`; the WARNING `... lease on proxies/<id> expired (no renew within the
  lease time); it gives it up` is only for a lease that really expired (its file gone or older than the lease time),
  which the worker now also gives up when nobody else has claimed the resource.
- Proxies are shared through the broker (`linecaster.broker`, [broker](docs/reference/broker.md)): `--proxy-blocks
  FOLDER` and an HTTP policy's root key `proxy_blocks` are gone; use `--broker PATH` and the root key `broker` (default
  `OUT/logs/broker`; runs pointed at one path share the proxies and their blocks). The old folder of block markers is
  not read; blocks found before are found again at the first request through each proxy. There is no alias.
- With a proxy list the rate limits (`--rate-limit`, an HTTP policy's `rate_limits` for a host through proxies) hold
  per proxy, not per worker: each proxy is used by one worker at a time, which spaces its requests through the proxy
  by the strictest limit. A server sees up to the proxies times the limits, whatever the worker count, so a limit
  meant for all proxies together is now too high by the proxy count: give the limit one IP may send. Direct
  connections keep the limits per worker.
- A host whose proxies are all blocked (or broken) no longer stops the run at once: its requests wait until a block
  ends or another worker gives a proxy back, up to the host's `max_pause` (6 h by default), and stop the run only when
  the first block ends later than that. A 429's `Retry-After` sets how long its proxy is blocked at the host, also
  when it is longer than `blacklist_ttl` (it was capped there).
- The extra `resilient-httpx` is gone: a proxy list needs only `linecaster[pybookget]`. Scripts that list
  `linecaster[...,resilient-httpx]` drop it (`pipelines/harvest.py` does), or their install fails on the unknown
  extra. `HTTPFetcher.proxies_in_rotation()` and `linecaster.net.http.proxy_rotation()` are
  `HTTPFetcher.proxy_counts()` and `proxy_counts()` (held, blocked, free); `HTTPFetcher`'s `proxy_blocks` and
  `default_proxy_blocks` are `broker` and `default_broker`; a request through proxies that used up its attempts raises
  `linecaster.net.http.MaxRetriesExceeded` (was resilient-httpx's, of the same name).
- A 429 pauses the worker that got it instead of stopping the run or failing the page: an HTTP policy has a new
  per-host key `pause_on` (statuses that pause the worker's requests to the host until the response's `Retry-After`
  has passed, then retry the request; default `[429]`) and `max_pause` (default 6 h in all since the host's last
  successful response; beyond it the run stops). A policy with `429` in `stop_on` is refused (`429 both in stop_on and
  pause_on`): move it to `pause_on` (`lccn.loc.gov: {direct: true, stop_on: [429, html]}` becomes
  `{direct: true, pause_on: [429], stop_on: [html]}`), or keep it in `stop_on` with `pause_on: []` to still stop the
  run on it; there is no alias. Without a policy the default applies as well: on a direct connection a 429 used to be
  retried per request by pybookget (each retry after the longer of its backoff and the `Retry-After`, at most 300 s,
  up to `max_retries`), the other requests going on meanwhile, and the page or resource failed with
  `HTTPStatusError` once its retries were used up; now the worker's requests to the host wait out the `Retry-After`
  (a minute doubling to an hour without one), the request is tried again without using up a retry, and the page does
  not fail. `http={"pause_on": []}` keeps the old behavior. Through a proxy list nothing changes: a 429 leaves that
  proxy out.
- `max_retries` (`http={"max_retries": ...}`, an HTTP policy's) counts retries after the first attempt, as its name
  says, where it counted attempts: `max_retries: n` now makes `n + 1` attempts, and `0` is a single attempt. The
  default is 4 (still 5 attempts). A setting written for the old meaning gets one attempt more; lower it by one to keep
  the old count. linecaster pins pybookget 1.2.0 (`45814da`), which counts this way too.
- `pp-doclayout-plus-l` without an edition resolves to edition 2, which orders the regions with XY-Cut++ instead of
  plain XY-cut. A run that must keep the old order names `pp-doclayout-plus-l@1`.
- `pipeline_sha256` leaves an in-process engine's `endpoint` and `timeout` options out (`ENGINE_OPERATIONAL`: where
  its service is). A derivative's run whose engine has an option of either name gets another hash: a resume into its
  folder needs `--new-pipeline`. No released recipe is affected.
- `linecaster.testing.check_engine` calls a page engine (recognition, unit `page`) with an empty transcription
  (no regions, no lines), not the sample layout's regions.
- `--rate-limit` holds per worker (process), not per task: the tasks a worker runs one after the other share one
  fetcher and its limits (`HTTPFetcher.shared`), where each task started its limits afresh. A server sees the workers
  running at once times the limits, as before; the run now states it before it starts (`run.rate_note`).
- `--tasks` and `--workers` default to an automatic choice (`linecaster.runtime.run.allocate`): a pipeline without
  engines (`pipelines/harvest.py`) runs tasks of about 1,000 pages (or 5 items) from its input, one worker with
  `--rate-limit`, one per CPU without; a pipeline with engines keeps one task, every task at once. Resuming a run
  started with the old default (`--tasks 1`) needs `--tasks 1`.
- http(s) requests have a deadline per attempt (`HTTP_DEFAULTS`: pybookget's `attempt_timeout=15` and
  `attempt_min_rate=50_000`, i.e. 15 s plus 1 s per 50 kB of Content-Length, counted after the rate limits): an
  attempt past it is cut and retried. A server that needs longer for a response without Content-Length needs
  `http={"attempt_timeout": None}` (or a longer one). linecaster pins pybookget `bf8eee1`, which has the setting.
- `--prefetch` and the readers' `prefetch=` argument are gone: `ManifestReader` and `ImageParquetReader` request
  `http(s)://` pages ahead in a window that sizes itself; drop the option. `linecaster.net.prefetched` takes
  `(entries, submit, cancel, future=, fetcher=)`.
- `ImageParquetReader` and `ManifestReader` item tables divide rows, not files, over the tasks; `ImageParquetReader`
  no longer splits a task's rows by datatrove's `ParquetReader.read_files_shard`, so `limit` and `skip` apply before
  anything is fetched, and no Parquet file is a `PipelineConfigError` (was datatrove's `RuntimeError`). A table
  no longer needs splitting into one file per task.

### Added

- Worker slots are claimed fast: processes started together (a local run's pool, Ray tasks, a multi-GPU Job's
  tasks) start their search at different slots (`linecaster.broker.set_worker_index`), so they register in about one
  claim each instead of racing for slot 0, then slot 1, ...; a run's first minutes no longer see early workers
  computing their share against the few registered so far. `linecaster.broker.survey_kind` lists who holds the
  resources of a kind (with their runs) and their live marks, from one listing.
- An extra `s3fs` for `s3://` paths in the `linecaster` command and code run in the project's environment (`uv sync --extra s3fs`, or `--all-extras`); the pipeline scripts bring their own. `linecaster broker` names a missing filesystem package in one line instead of a traceback.
- The broker (`linecaster.broker`, [broker](docs/reference/broker.md)): a shared folder, any `DataFolder`, through
  which workers across tasks, runs and machines agree on who holds which shared resource (leases, renewed within
  180 s, claims decided by listing) and what is unavailable until when (marks per scope). A worker is a slot of its
  machine that outlives its processes: on Ray the next task on a machine takes over the slot the last one handed over,
  with its leases. Proxies are its first kind (`linecaster.net.proxies.ProxyPool`): each proxy has one worker at a
  time, each worker its fair share (rebalanced as workers join and leave), a block is a mark seen by whoever claims
  the proxy next, without the 30-s polling of the proxy-blocks folder it replaces, and the rate limits hold per proxy.
  The console shows the proxies held, blocked and free.
- `linecaster broker status PATH [--json]`, `clean PATH [--leases] [--marks]` and `purge PATH`
  ([broker](docs/reference/broker.md#the-command)): what a broker's folder holds (workers, slots, per kind the
  resources held, free, blocked per scope, broken); removing what has expired (safe beside running workers), after a
  hard kill every heartbeat and lease (`--leases`: a relaunch gets slot 0 and the proxies at once instead of waiting
  up to 3 min for them to expire), every mark (`--marks`), or the whole layout (`purge`). Removing live files asks on
  a terminal and is refused without one (`--yes`, `--dry-run`). In code: `linecaster.broker.survey_all`, `clean` and
  `purge`.
- XY-Cut++ reading order (Liu, Li and Wei, arXiv:2504.10258) for layout models without one:
  `linecaster.data.geometry.xy_cut_plus_plus.xy_cut_plus_plus_order(boxes, labels, page_size)`, pure and
  deterministic, the paper's β, θ_v, τ_overlap, centering tolerance and edge weights as keyword arguments, its
  ambiguities resolved by the authors' Apache-2.0 implementation (NOTES.md, 2026-11-07). `paddlex.layout.v1` takes it
  with the new option `reading_order: xy-cut++` (default `xy-cut`, the plain XY-cut as before), and the new edition
  `pp-doclayout-plus-l@2` sets it. `place_unordered` keeps plain XY-cut.
- Nothing to size for a harvest: `pipelines/harvest.py --parquet TABLE ... OUT --rate-limit 150/60` reads any page
  table as it is, in tasks of about 1,000 pages, with one worker that keeps the rate limits busy.
  `linecaster.blocks.readers.tables` divides Parquet tables over tasks by rows in equal shards (by row group);
  `ImageParquetReader.auto_tasks()` and `ManifestReader.auto_tasks()` suggest a task count from the input.
- `ImageParquetReader` requests `http(s)://` images ahead, pages in the rows' order. `linecaster.net.prefetched`, the
  window both readers use, grows while the first request is out and none waits for the rate limits
  (`HTTPFetcher.waiting`), up to `MAX_AHEAD`, so one task keeps any rate limit busy.
- `HTTPFetcher.shared(**config)`: one fetcher per process and configuration, which the readers use, so the rate
  limits (and the window learned) hold across the tasks a worker runs one after the other; `close_shared()`.
- `--parquet` takes one `.parquet` file as well as a folder.
- Resources: `pipelines/harvest.py --items TABLE --item-key COL` fetches items' remote files as served
  (`ResourceReader`, `ResourceFilesWriter`, `ResourceRecordWriter`), from URL templates (`--resource KIND=URL` with
  `{item}`) or a resource table (`--url-key`, `--kind-key`, `--name-key`): raw copies at
  `OUT/<kind>/<item>/<name>.<ext>`, a fetch record each in `OUT/resources/<rank>.jsonl.gz`, one item per task,
  `--max-items`, reuse, rejects, `--retry-failed`. Each response is checked (XML, JSON, images; an HTML page where
  another format was expected fails and counts toward the breaker).
- The HTTP policy: `--http-policy FILE` (`linecaster.net.policy.HTTPPolicy`) gives the run's requests their settings
  from one YAML file, for every host at its root and per host under `hosts:` (an entry replaces the root's fields it
  names; the run's own options go between the two): rate limits, proxies or a direct connection, User-Agent, deadline,
  retries (`max_retries`), the proxy blocks folder (root only) and `stop_on` statuses (and `html`) that stop the run
  without a retry; each host's settings their own fetcher. Readers take it as `http_policy=`. For `--items` and `--parquet`. `RejectWriter` takes any unit.
- A failed fetch says what failed: retries used up through proxies raise `MaxRetriesExceeded` naming the last error
  (`after 5 attempts: HTTP 520`, `... ReadTimeout (no message)`), an empty pool `AllProxiesExhausted` with a message,
  and httpx's silent timeouts get one; and the fetch's record (attempts, `tries`, waits) goes with the exception into
  the failed page's trace (`linecaster.net.http.failed_fetch`), where it was dropped.
- Outages are waited out: each fetcher has a breaker (`linecaster.net.http.Breaker`), which also opens after as many
  server errors in a row as a request has retries; a request whose retries ran out in a pause waits it out and tries
  again (at most `BREAKER_WAITS` times), so a request alone no longer fails before the breaker sees the outage. When at least half of the
  attempts in the last minute (20 at least) got a server error (5xx), requests pause; a probe goes out after a minute,
  then after waits that double up to ten minutes, and the first answer that is not a server error ends the pause. The
  pages wait instead of failing, and the progress line says `paused: server errors`. Cloudflare's 520-524 are retried
  like 502-504 (pybookget `91d39e4`).
- With `--proxies` a server error is retried through another proxy without blacklisting the one it came through
  (resilient-httpx `blacklist_on={429}`, storytracer's fork 1.5.0 at `f706598`): only a 429, a timeout or a connection
  or proxy error counts against a proxy, so an outage no longer empties the pool.
- With `--proxies` (or a host's `proxies`), an HTML page where another format was expected is that proxy's block:
  the proxy is left out and the item goes on through the next one (`linecaster.net.http.ProxyBlocked`;
  `HTTPFetcher.submit(..., expect=)`), with no breaker pause. Without proxies such a page fails as before. The HTTP
  policy sets how long a blocked proxy is left out and after how many failures (`blacklist_ttl: 72h`,
  `blacklist_threshold`; durations in s, m, h or d). A host with no proxy left stops the run (`StopRequests`, a
  `ServerError`) naming when the first returns, where every following item failed with `AllProxiesExhausted`.
- The HTTP policy can name statuses besides 429 that leave the proxy they came through out (`blacklist_on: [403]`,
  resilient-httpx's `blacklist_on`); they are retried through the next proxy instead of failing the item.
- Proxy blocks are shared through a folder of markers (`--proxy-blocks FOLDER` or the HTTP policy's `proxy_blocks`,
  default `OUT/logs/proxy-blocks`;
  `linecaster.net.proxy_blocks`), as datatrove shares finished tasks: each block is a marker written once and never
  changed, and every fetcher reads a host's markers at its first request there and every 30 s after. Every worker in
  every deployment mode, and every later run pointed at the same folder, leaves the blocked proxies out; a restarted
  run no longer sends requests into the blocks it found. linecaster pins resilient-httpx 1.6.0 (storytracer's fork,
  `cdebe7d`, `block_proxy`).
- Through proxies, only a proxy's own failures leave it out: a block (a 429, a status in `blacklist_on`, an HTML block
  page) or a broken proxy (`PROXY_ERRORS`: a proxy error, no connection to it). A timeout, mostly a slow server, is
  retried through another proxy and leaves this one in, where it was left out for an hour (or a host's
  `blacklist_ttl`). A block no longer uses up one of the request's attempts, and the next proxy is tried without a
  backoff wait; the pool bounds the blocks. linecaster pins resilient-httpx 1.7.0 (storytracer's fork, `bc9de0a`:
  `blocks_count_as_attempts`, `block_exceptions`, `blacklist_on_exception`).
- `--on ray`: a pipeline without engines (`pipelines/harvest.py`) runs on datatrove's `RayPipelineExecutor`, so on
  CPU-only Ray workers (`--cpus-per-task`, `--mem-per-cpu-gb`); every single-stage pipeline asked for a GPU per task.
- A Ray run stops as a local one does (`linecaster.runtime.ray.RayExecutor`, also under `RayGPUExecutor`): an error
  that is not the pages' (a host's `stop_on`, a server, the configuration) in one task writes a stop marker to the
  logging folder (`stopped.json`), every later task ends before its pipeline starts, and the launch fails with that
  error. datatrove only ended the task and started the next, whose first request went straight into the block
  (a JSON API run sent about 990 requests into LoC's 429 block that way). A launch with unfinished tasks fails too,
  where the Ray job ended as succeeded with "Only 8/1000 tasks completed".
- `--address` joins the Ray cluster it names (`linecaster.runtime.run.connect_ray`: `auto`, `HOST:6379`,
  `ray://HOST:10001`); it was read but not used, so a run only found a cluster started on its own machine.
- A task that fails no longer stops a local run with several workers (datatrove's pool stopped at the first
  exception, and the launch then hung): it is logged, the others go on, it runs again on the next launch, and the
  summary counts the unfinished tasks. Configuration, catalog and server errors, and 20 failed tasks in a row in one
  worker, still stop the run. `kill -USR1 <pid>` writes every thread's stack to the terminal.
- `--retry-failed` (local): finished tasks that left rejects run again; with `harvest.py` their images that are there
  are read back and only the failed pages fetched, and the task's rejects file is written anew.
- A proxy answered with a 429 or 503 whose `Retry-After` is shorter than the blacklist TTL (3600 s) is left out only
  that long (resilient-httpx's `blacklist_ttl_from_retry_after`, from storytracer's fork, pinned at `238582e` as
  resilient-httpx 1.4.0); everything else keeps 3600 s.
- `pipelines/harvest.py` runs one item per task (`task_per_item` of `ImageParquetReader` and `ManifestReader`): every
  item whole in its task, a task that fails costs one item. Items are grouped by their `--item-key` value, so a table
  whose item rows are apart still gives one task per item (`tables.item_runs`). Other pipelines keep their task
  sizes. A harvest run folder started with the 1,000-page tasks has another task count: run into a new folder.
- A resumed harvest does not fetch images again that an earlier launch wrote: `ImageParquetReader` and
  `ManifestReader` take `reuse_folder` (`harvest.py`: `OUT/images`), list an item's folder once when they reach it
  (`linecaster.blocks.readers.existing.ExistingImages`; names and sizes) and read a page whose file is there from
  the storage instead of fetching it from the source. Only pages of items whose task was interrupted are read back
  (with one item per task, at most one item per worker and restart), so storage egress stays small. Its record is
  complete (`sha256`, width, height) and says `image.extra.reused`; `ImageFilesWriter` leaves the file as it is; the
  reader counts it in `pages`, `media_size` (the bytes it read) and `reused`; the console counts it as done, apart
  from the downloads and their rate. Not with `--existing-ocr`. `ImageFilesWriter` writes local files as
  `<name>.part` and renames them when whole.
- The console's size on a restart starts with the finished tasks' images: their readers' `media_size` from
  datatrove's stats files (`linecaster.runtime.local.size_before`), read in batches in the background while the run
  starts (`size …` until then).
- `--proxies FILE`: http(s) requests through a list of proxies (one per line: a URL, or `host:port[:user:pass]` as
  Webshare lists them), with resilient-httpx (the extra `resilient-httpx`): each attempt through the next proxy, a
  proxy that fails an attempt left out for an hour (`PROXY_BLACKLIST_THRESHOLD` 1, `PROXY_BLACKLIST_TTL` 3600 s), the
  attempt retried through another. Each proxy's client is pybookget's, so the rate limits (shared by all proxies),
  the deadline per attempt and the trace records hold as without; retries follow pybookget's counts and waits, without
  `Retry-After`. The progress line shows the proxies in rotation; credentials are never logged, and the run record
  keeps the file's name, not its lines.
- `--user-agent TEXT` and `--random-user-agent` (a random browser User-Agent from pybookget's fake-useragent, a new
  one for each task, `HTTPFetcher.new_user_agent`) for every http(s) request. The default User-Agent is datatrove's,
  `HF-Research/1.0` (`linecaster.net.http.USER_AGENT`), where it was `linecaster (+https://github.com/storytracer/linecaster)`.
- The console of a local run (`linecaster.runtime.console`, `linecaster.runtime.local.LocalExecutor`): one line
  naming the pipeline, a live progress line for the whole run (pages of the total, rate, size, failed pages, task,
  time left), a line per finished task and a summary, in human units; a progress log line every 30 s off a terminal.
  datatrove's pipeline listing (with the builder's boundary steps) and stats blocks go only to the task logs. The
  completion markers are listed once per launch instead of looked up task by task. With several workers the worker
  processes report their counts to the console (a `multiprocess` manager's dict), and every worker's task lines show.
  On a terminal the progress line is pinned to the top row and everything else scrolls below it (a scroll region,
  `console.Pinned`), so log lines and output from worker processes or libraries never break it.
- `ImageParquetReader` and `ManifestReader` pass pages on as their http(s) requests finish, not in row order, so a
  slow or retried request delays only its own page (`prefetched(..., ordered=False)`); pages read without a request
  keep their order. Requests in flight are capped at the rate limits times the deadline per attempt
  (`HTTPFetcher.max_ahead`). In a 2,000-page LoC smoke run the oldest request, being retried, held the window full
  of finished pages for minutes (94 pages/min against 150).
- Fetch records and traces carry each attempt's outcome (`tries`, the span attribute `http.tries`): a status for a
  response read whole, `<status>-cut` for one the deadline cut, `no-response` for a timeout or a connection error.
- `--max-pages N` (`--parquet`, IMAGES; `max_pages` of `ImageParquetReader` and `ImageFolderReader`): the first N pages
  of the input for the whole run, in the same automatic tasks, so a smoke test is the real setup stopped early
  (`--limit` counts per task).
- A response that trickles no longer holds a task: the deadline per attempt (above) cuts it and fetches it again,
  usually through another proxy exit. In a LoC smoke run one such response took 150 s while the 199 pages behind it
  waited; the trace shows a cut attempt as `http.attempts` 2.

- The four BHL OCR board models the catalog lacked, as the board's drivers run them, each run on the board's
  60-page sample (NOTES.md): model entries `surya-ocr-2.5`, `indra-ocr`, `oxr-1.0`, `falcon-ocr` (Falcon OCR pinned at
  the revision its vendor image ships) and their presets `surya-ocr-2.5@1`, `indra-ocr@1`, `oxr-1.0@1`,
  `falcon-ocr@1` (step `recognition`, unit `page`), with evidence records where they ran.
- Page engines: `PageRecognizer` runs an engine whose unit is the page on the `InProcess` or `Served` backend (or a
  page engine's preset by name), besides a chat VLM on `Chat`. Engine packages `linecaster-indra`
  (`indra.recognition.v1`: the `indra-ocr` package on the CPU), `linecaster-surya` (`surya.recognition.v1`: the
  `surya-ocr` package's full-page path attached to vLLM) and `linecaster-services` (`falcon.recognition.v1`,
  `oxr.recognition.v1`: clients of Falcon-OCR's and OXR's page pipelines behind their own HTTP APIs).
- `ServiceServer` (servers): starts the service a page preset's `serve` block names, last in the pipeline: `vllm
  serve` on the fetched model pin, or a vendor image's entrypoint (`serve.server: vendor` with `command`, `health`,
  `weights_dir`, new optional fields of the preset schema), ready once its health URLs answer.
- `pipelines/transcribe_page.py` (`transcribe_page.v1`): a page engine per page, with the service its preset names
  unless `--recognition-endpoint` names a running one; `launch.py` runs a page engine's preset there.
- `linecaster.testing`: `FakePageEngine` (`fake.recognition.page.v1`) and `fake_service()`, an HTTP service on
  loopback answering given routes. `tests/test_page_engines_catalog.py` checks the page engines in the environment
  of `pipelines/transcribe_page.py`.
- Versioned docs: the docs workflow publishes the site with mike to the `gh-pages` branch, served by GitHub Pages:
  every release tag as version `<major>.<minor>` (`latest` the newest release, the default), every push to `main`
  as `dev`; `mike` joins the dependency group `docs`.

### Fixed

- A page could fail with HTTP 520 during an outage the breaker had seen: when the request's last server error opened
  the breaker and another request's probe was answered (closing it) before that error got back to the fetch, the fetch
  found the breaker closed and gave up. It now tries again whenever the breaker opened during its attempts
  (`Breaker.openings`).
- The rate limits started afresh with every task (each made its own fetcher), so a worker's next task could
  send a whole window's requests at once; and `ImageParquetReader` never closed its fetcher, leaving a thread per
  task. The readers share one fetcher per process and configuration (`HTTPFetcher.shared`).
- `ImageParquetReader`: an image that cannot be read (an `http(s)` error after the retries, a missing file, bytes
  that are not an image) no longer fails the task. The page comes without image and with the error in
  `doc.metadata["errors"]` (`field` `image`, `raw_value` its URI), so the page records and rejects keep it and a
  rerun of the task does not fail on the same dead link again; the reader has an error budget (`max_page_errors`,
  set by `--max-page-errors`), so a server that is down still fails the task. `ImageFilesWriter` passes a page that
  carries errors and no image through without writing a file. A row with neither image bytes nor a path still fails
  the task.

## 0.1.0 (2026-11-06)

### Upgrade notes

The first release, after the refactoring of November 2026 in six phases; each phase's renames are listed
here, and all of them in one table at the end of these notes. There are no compatibility aliases: old imports, flags
and ids fail.

**Phase 1: layout and names**

- Packages: `linecaster.transcription`, `linecaster.page` → `linecaster.data` (data model) and `linecaster.formats`
  (ALTO, PAGE, hOCR; `formats.docling` was `linecaster.document`); `text.py`, `unicode.py`, `reflow.py`,
  `retyper.py` → `linecaster.text.variants`, `.unicode`, `.recomposition`, `.typography`; `images.py`, `plots.py` →
  `linecaster.images`; `run`, `jobs`, `ray_executor`, `provenance` → `linecaster.runtime.*` (`run.rows()` →
  `run.pages()`); `linecaster.models` → `linecaster.adapters`; `blocks/http.py` → `linecaster.net`; blocks by
  family under `linecaster.blocks.<family>` (old modules `filters`, `media`, `models`, `serve`, `texts`,
  `document`, `readers`, `writers` are gone); `specs/` → `docs/reference/`.
- Blocks: `PageStep` → `PageBlock`, `ModelStep` → `ModelBlock`, `WorkingImages` → `ImageConverter`, `AttachImage`
  → `ImageFetcher`, `LayoutStep` → `LayoutDetector`, `LinesStep` → `LineDetector`, `AssignLinesToRegions` →
  `LineAssigner`, `RecognitionStep` → `LineRecognizer`, `ChatRegionStep` → `RegionRecognizer`, `ChatPageStep` →
  `PageRecognizer`, `TablesStep` → `TableRecognizer`, `FormulasStep` → `FormulaRecognizer`, `NormalizeUnicode` →
  `UnicodeNormalizer`, `Typography` → `Typographer`, `ComposePage` → `Composer`, `ValidatePages` → `PageValidator`,
  `RejectSink` → `RejectWriter`, `RecipeStamp` → `RecipeStamper`, `ServeModels` → `ModelServer`, `ServeChatModel`
  → `ChatModelServer`, `PageRowReader` → `PageRecordReader`; writers: `PageFilesWriter` + `PageExportsWriter` →
  `PageFileWriter` (`text_fallback=False` is the old `PageExportsWriter`), `ItemExportsWriter` →
  `ItemDocumentWriter`, `ItemTextJsonlWriter` + `ItemTextFilesWriter` → `ItemTextWriter(format=...)`. Datatrove
  display names changed with them (stats and logs).
- Engines: `…Model` → `…Engine` (`KrakenRecognitionEngine`, `PaddleLayoutEngine`, ...); ids unchanged. Adapters:
  `ChatModel` → `ChatAdapter`, each VLM adapter `X` → `XAdapter`.
- Pipeline scripts: `transcribe_chain.py` → `transcribe_modular.py`; ids `chain.v1` → `transcribe_modular.v1`,
  `vlm.v1` → `transcribe_vlm.v1`, new `harvest.v1`, `bind.v1`.
- Flags: `--recognizer` → `--recognition`; `--vlm`, `--vlm-endpoint` → `--recognition`, `--recognition-endpoint`;
  `--texts` → `--item-texts`; `--exports DIR` → `--files DIR --formats md,txt,json --naming squiddleocr
  --furniture`; `--rows` → `--pages`.
- Stored output: the default transcription `ocr` → `ocr_new`; page records in `OUT/rows/` → `OUT/pages/`; item text
  fidelity `normalised` → `normalized`; typography measurement `levelled` → `leveled`. Page records written before
  phase 1 keep `ocr`; read them with `transcription="ocr"`.
- Catalog: no step `page` (page presets are step `recognition`, unit `page`, under `presets/recognition/`); entries
  are `<id>.yaml` with prose in `<id>.md`; YAML is read as YAML 1.2 with `ruamel.yaml` (replaces PyYAML); lock format
  `linecaster.lock/2`. Edition numbers are unchanged; 20 hashes were recomputed (the page presets and `squiddle@1`),
  so files stamped by a recipe carry the new hash; old hashes still resolve (`previous_sha256`).
- American spelling throughout (e.g. `normalize`, `NORMALIZE_MAP`, `quantize_confidence`, `COLORS`).

**Phase 2: contracts and the builder**

- Pipeline scripts check their pipeline before they launch: a pipeline whose contracts do not fit exits with code 2
  and lists every problem. Own blocks without a `contract()` pass unchecked.
- With `--tasks` over 1, a binder after the page blocks (`--item-texts`) cuts the run into two stages: page records
  in item shards (`OUT/pages/<shard>/`), then the item stage; their logs are `OUT/logs/pages/` and
  `OUT/logs/items/`. One stage logs to `OUT/logs/` as before.
- `--dry-run` prints the plan under `plan` and the Mermaid graph after the JSON.
- A page an in-process block fails on no longer fails the task: it carries the error (`doc.metadata["errors"]`:
  `block`, `step`, `preset`, `type`, `error`; served failures in the same shape, no longer `{step, error}`), later
  model blocks pass it on at once, and it is written to `OUT/rejects/<rank>.jsonl` and kept in the page records.
  More failures than `--max-page-errors` (1 % of a task's pages, counting at least 100) fail the task.
- `ImageConverter(output_folder, rejects_folder, ...)` → `ImageConverter(output_folder, ...)` and
  `PageValidator(rejects_folder, required, prefix)` → `PageValidator(required)`: they record why on the page and
  pass it on (no longer dropped); the `RejectWriter` (now a writer block, `RejectWriter(output_folder, prefix="")`,
  which the builder puts before the first writer of a run) writes the rejects. A derivative that used either adds
  a `RejectWriter` where it wants the file, or lets the builder add one.
- Library code raises `linecaster.errors` (`PipelineConfigError`, `CatalogError`, `PageError`, `ServerError`)
  instead of `SystemExit`, `ValueError`, `KeyError`, `RuntimeError` and `TypeError` for configuration, catalog,
  page and server errors (e.g. an unknown preset is a `CatalogError`, an unknown block option a
  `PipelineConfigError`); pipeline scripts raise `PipelineConfigError` from `pipeline()`.
- `runtime.jobs.dependencies(commit)` without a script raises; give the pipeline's script,
  `runtime.jobs.ENGINE_SCRIPT` (the modular pipeline's engines) or `engines=False` (linecaster alone).
- The run record's schema is `linecaster.run-record/1` (was `linecaster.run/1`): `pipeline` lists the stages with
  every block's `to_dict()` and contract (was a list of block entries; the separate `stages` is gone), and
  `pipeline_sha256` is new. A run into an OUT whose record has another `pipeline_sha256` (or none: a record from
  before) is refused unless `--new-pipeline`; another `--tasks` always is.
- Page records carry `schema: linecaster.page/1` in their row. Records without one (written before phase 1) are read
  with `ocr` as `ocr_new`, and a `pages/` folder without records is read from its sibling `rows/`: no
  `transcription="ocr"` needed any more.
- Engines load in `warm_up()` before the first page, not on it: a page's measured `seconds` no longer include
  loading; the load time is the block's `warm_up_seconds` stat. `ModelServer` and `ChatModelServer` start their
  servers in `warm_up()` (stat `warm_up_seconds`, was the `boot` time stat).
- `engine_spec(ref)` and `preset_models(models)` take `installed=True`; tests that replace `engine_spec` accept it.
- On HF Jobs the tasks log JSON lines (`LINECASTER_LOG_JSON=1`, `runtime.jobs.JobsExecutor`; the run record's
  executor is `JobsExecutor`).
- Every run is traced (OpenTelemetry, a new required dependency: `opentelemetry-api`, `-sdk`,
  `-exporter-otlp-proto-http`): `OUT/traces/` appears in every run folder, and a sampled page's record carries
  `metadata.trace_id`. Every stage with a run folder now has observers, so its pipeline has boundary steps.
- Observers: `on_task_end(error=None)` (was `on_task_end()`; an own observer adds the parameter), and new hooks
  `on_task_event`, `on_leave`, `environment()`. Stream blocks notify `request` (with a `carrier`) after `prepare`,
  and `done` with tokens and `finish_reason`; `PageRecognizer` notifies `prepare` once (was twice).

**Phase 3: rule-based steps, recomposition, binding**

- Text without geometry (lines without boxes, e.g. a delivered plain text): a paragraph now continues across a page
  break only after a division mark; before, the simple line flow joined such pages whenever the text did not end a
  sentence.
- `linecaster.blocks.writers.item_texts(doc, variants, transcription, token_counter)` renders an item record's text
  variants as datatrove documents, for derivatives writing them in a format of their own; `ItemTextWriter` uses it.
- `linecaster.catalog.schema.RULE_STEPS` lists the rule-based steps, to tell a recipe's rule-based slots from its
  model slots.
- Data model: `ModelInfo` → `StepInfo` (new field `engine`, the engine's code id, filled by the model blocks,
  `linecaster serve` and the chat adapters), `Transcription.model` → `Transcription.steps`, `ChatAdapter.model_info()`
  → `step_info()`. New: `Transcription.paragraphs` (`Paragraph`, `ParagraphRow`, `ParagraphRef`, `Decision`),
  `Line.normalized`, and the measurements vocabulary `linecaster.data.MEASUREMENTS` (the keys a step writes; an
  engine package in this repository adds a new key there first, a test checks it).
- Page records are `linecaster.page/2` (`steps` instead of `model`, `paragraphs`, `normalized`). `PageRecordReader`
  reads `linecaster.page/1` records and those from before phase 1 as `/2`; code that reads the JSON itself reads
  `steps`.
- The page files' step records (ALTO `processingStepSettings`, PAGE `Labels`, hOCR `linecaster-step-<n>`, METS agents)
  carry `engine` for steps an engine ran.
- Catalog: the steps `image`, `normalization`, `typography`, `recomposition`, `composition` with built-in engines in
  `linecaster.engines`, in-process only (`linecaster serve` refuses them); presets may name `by_script` strategies;
  `capabilities.unit` may be `item` and `produces` names parts (`PARTS`). `preset-1.json` gains them; no released
  hash changes. `engine_spec(ref, installed=True, served=False)` and `preset_models(models, installed=True,
  served=False)`: tests that replace `engine_spec` accept `served`.
- `regex` is a new core dependency (Unicode scripts).
- The rule-based blocks take a preset or an engine spec, with `options` over it: `Typographer()` →
  `Typographer("ratios@1")`; `Composer(text="reflow", sections=..., rtl=...)` → `Recomposer("unicode-recomposition@1",
  options={"rtl": ...})` + `Composer("docling-composition@1", options={"sections": ...})`, and `text="lines"` is a
  `Composer` without a `Recomposer` before it (the document is composed from paragraphs when there are, else from
  lines); `ImageConverter(output_folder, effort=80)` → `ImageConverter(output_folder, "working-image@1",
  options={"effort": 80})`. New blocks `Recomposer` (composition, `unit="page"|"item"`) and `CharacterNormalizer`
  (text); `Composer` also takes `unit="item"`.
- `DocumentBuilder(name, text=..., sections=..., rtl=..., stats=...)` → `DocumentBuilder(name, sections=...)`: it no
  longer recomposes, it composes a page's paragraphs when it has them (`add_page(..., page_id=...)` names the page for
  paragraphs continued across pages); `build_docling(...)` loses `text`, `rtl` and `stats`; `formats.docling.TEXT_MODES`
  is gone. In `linecaster.text.recomposition`, `join_paragraphs` → `join` (the joined text, the separator and the
  decision on the division mark), new `break_reason`, `kept_reason`, `mark_decision`, `Thresholds` (the geometric
  thresholds and the convention marks, parameters of `reflow_rows`, `Margins.of`, `continues`, ...); `Row.bbox` may
  be `None` (text only). `text.typography.retype` takes `ratios` (`Ratios`) and records no step (the engine does);
  `typography.SETTINGS` is gone.
- Page records and page files: with a recomposition (`--recomposition`, the squiddle recipe) the transcription
  carries its `paragraphs` (with their decisions); the typography step is recorded by its engine (name and engine `typography.ratios.v1`, preset
  `ratios@1` and its hash, every option as settings, `seconds` and `datetime`), and the recomposition and
  composition steps have step records of their own. The documents and their exports are unchanged.
- Binding: `BindItem` and `ItemTexts` are removed. `BindItem(text="reflow", sections=S)` → `Binder()` +
  `Recomposer("unicode-recomposition@1", unit="item")` + `Composer("docling-composition@1", unit="item",
  options={"sections": S})` (`text="lines"`: without the `Recomposer`); the item documents are the same, the item
  document's `metadata` is the item record plus `docling`, `region_of`, `item_id` (no `page_ids`, `pages`,
  `text_mode`, `sections`). `ItemTexts(variants=V, token_counter=F)` → `Binder()` + `Recomposer(...,
  unit="item")` + `CharacterNormalizer("latin-historic@1", unit="item")` + `ItemTextWriter(DIR, variants=V,
  token_counter=F)`: the writer renders the variants from the item record (one row per item and variant, the same
  columns). `ItemDocumentWriter` gains `by_format` (`<format>/<item>.<ext>`).
- The readable variants (`readable_txt`, `readable_md`) are made from the item's recomposition and normalization
  (`Paragraph.normalized`) instead of `text.variants`' own line flow, so they change (paragraph breaks, kept hyphens;
  NOTES.md has the comparison). `linecaster.text.variants`: `join_lines`, `page_blocks`, `item_blocks`, `continues`,
  `HYPHENS` and `SENTENCE_END` are gone; `variants(pages, page_ids=None)` needs recomposed, normalized pages;
  `body_blocks` and `Block.normalized` are new. The normalization engines also set each table cell's `normalized`.
- `pipelines/transcribe_modular.py`: `--text lines|reflow` → the slots `--typography`, `--recomposition`,
  `--normalization` and `--composition` (presets; an empty slot leaves the step out: `--text lines` is no
  `--recomposition`). Without a recipe the rule-based steps run only when picked (before: typography and
  composition always). `--item-texts` needs `--recomposition` and `--normalization` (the recipe `squiddle` has them).
  `--set` takes the rule-based steps too (`--set composition.sections=true`).
- `pipelines/bind.py` (`bind.v1`, now with recipes): Binder → item recomposition → normalization → item composition,
  texts in `OUT/texts/<variant>/` (JSONL; `--files` also one file per item there, was `OUT/files/<variant>/`) and
  item documents in `OUT/documents/<format>/`; slots `--recomposition`, `--normalization`, `--composition` (the new
  recipe `item-texts@1` fills them), `--variants`, `--formats`, `--furniture`, `--dividers`, `--no-texts`,
  `--no-documents`, `--set`.
- `squiddle@1` names the rule-based presets (`ratios@1`, `unicode-recomposition@1`, `latin-historic@1`,
  `docling-composition@1`) instead of the option `text: reflow`: a catalog migration, so its hash changed (files
  stamped by it carry the new one) and the lock's `previous_sha256` lists both earlier hashes (`previous_sha256` may
  now be a list, oldest first; `Resolved.previous_sha256` is a tuple).
- The builder carries the parts across a binder and a splitter (an item record holds its pages), apart from `image`
  and the item's `document`; the role `splitter` is new. `Recomposer`'s contract replaces `paragraphs` too (it makes
  them anew). `RecipeStamper` has unit `any` (it stamps the pages of item records).

**Phase 4: backends and families**

- VLMs are the `Chat` backend (`linecaster.backends.Chat(preset, endpoint=None, served_name=None, max_window=32,
  initial_window=4, read_timeout=600.0, api_key=None, headers=None, prefer="page")`): `PageRecognizer(spec,
  Served(endpoint, model=name, max_window=W, ...))` → `PageRecognizer(Chat(spec, endpoint, served_name=name,
  max_window=W, ...))`, the same for `RegionRecognizer(spec, backend, labels=..., pad=...)` →
  `RegionRecognizer(Chat(...), labels=..., pad=...)`; either also takes a chat preset's ref (`PageRecognizer(
  "dots-ocr")`: on the task's `ChatModelServer`, port 8000). The adapter is `block.adapter` (was `block.spec`), the
  served name `Chat.served_name` (was the `Served` backend's `model`). Without an endpoint `Chat` asks
  `http://127.0.0.1:8000/v1`. The page records are unchanged.
- The run record: a chat block's parameters are `backend` (`{"backend": "chat", "adapter", "preset",
  "preset_sha256", "model", "revision", "served_name", "endpoint", ...}`) instead of `spec` and a served `backend`;
  `pipeline_sha256` covers the adapter, preset edition and hash, model and revision (no longer the served name), so
  a run of `transcribe_vlm.py` into an OUT of before is refused unless `--new-pipeline`.
- `ModelBlock` streams for every served block, and a block names its requests with `_rows`, `_unit`, `_request`,
  `_parse` and `_done` (an own served block that overrode `_run_served` or `RegionRecognizer._run_regions` uses
  them). Model blocks also take a preset ref as their backend (`LayoutDetector("pp-doclayoutv3@1")`: in-process).
- `SingleRegionLayout` is removed: `SingleRegionLayout()` → `LayoutDetector("single-region@1")` (the built-in engine
  `layout.single-region.v1`; `label` and `region_id` are its options). The region is the same; the page now
  records a layout step for it (engine, preset, settings, `seconds`, `datetime`), which page files list too, and the
  block reads the page image instead of the record's size. `ModularTranscriber(lines, recognition)` needs its
  layout: `ModularTranscriber(lines, recognition, "single-region@1")`.
- `pipelines/transcribe_modular.py` needs `--layout` like `--lines` and `--recognition`: a run without one is
  `--layout single-region`. Presets of built-in engines stay in-process with `--backend served`
  (`runtime.run.engines`), and the pipelines' `serve` leaves them out.
- `ManifestReader(existing_ocr=True)` only fetches the library's OCR, as a document media with
  `metadata["format"]` (`alto`, `hocr`); its contract adds `transcription_file` (a new page-level part) instead of
  `ocr_original:*`. The `TranscriptionConverter` reads it into `ocr_original`: the builder puts one right after
  such a reader when no block reads the file, and `pipelines/harvest.py` has its own, so `OUT/ocr/` and the page
  records are as before. Its hash changes (a new block), so a harvest into an OUT of before needs `--new-pipeline`.
  A file that cannot be read is now the page's error (it goes to `rejects/`; before, the page went on without it
  and `ocr_failed` counted it); a failed download is still counted as `ocr_failed`. hOCR files that state another
  image size are scaled to the page image (before: read as they were).
- `PARTS` gains `transcription_file` (no released hash changes).
- A new extra, `[pypdfium2]`, for the `PdfReader`; the locks list it.

**Phase 5: docs**

- `linecaster catalog docs [--out docs/catalog] [--readme README.md]` → `linecaster docs [--out docs] [--readme
  README.md] [--check]`: `--out` is now the docs folder (the catalog's pages go to `<out>/catalog/`). It also writes
  the block pages, the README's block table (between `<!-- blocks:start -->` / `<!-- blocks:end -->`), the site's
  `docs/index.md` and `docs/changelog.md`, and `docs/llms.txt` / `docs/llms-full.txt`; `--check` writes nothing and
  exits with 1, naming each file that differs. `linecaster catalog` no longer has the action `docs`.
- Generated pages start with a comment saying so; their links to files outside `docs/` (sources, pipeline scripts,
  model cards) go to GitHub. The evidence tables have two more columns, Hardware and Backend.
- A new dependency group, `docs` (MkDocs and Material), not an extra: `uv run --group docs mkdocs build --strict`.
- `CLAUDE.md` holds rules only; what it described is in `docs/reference/architecture.md`, the data model and
  serialization pages.

**Phase 6: tests and engine hygiene**

- Contracts name the parts a block removes (`Contract.removes`, `parts_removed`; the run record's contracts and
  `schemas/run-record-1.json` have `removes`). `ImageConverter` without `keep_bytes` removes `image`: a pipeline in
  which a later block reads the image (without an `ImageFetcher` in between) no longer passes the builder's check;
  it failed on its first page before.
- `RegionRecognizer(pad=None)`: an explicit `pad` wins over the adapter's `region_pad`, which is the default (else
  8). Callers that passed `pad` with a preset that has a `region_pad` (`minicpm-ocr-1.0`: 0,
  `lightonocr-2-1b-regions`: 8) now get their `pad`. The run record names `pad: null` when none is given, so
  `pipeline_sha256` of a pipeline with a `RegionRecognizer` changes (no released recipe has one): resuming into an
  older run folder needs `--new-pipeline`.
- Engine packages are version 0.1.0 and depend on `linecaster>=0.0.1,<0.2`; they import from linecaster only
  `linecaster.data` and `linecaster.engines.api`. A derivative's own engine package should do the same.
- Tests: pytest runs with `--strict-markers`; `tests/conftest.py`'s `make_transcription` is
  `linecaster.testing.sample_transcription`.

**Every rename, old → new**

**Blocks**

| Old | New | Family | Phase |
|---|---|---|---|
| `PageStep` | `PageBlock` | base | 1 |
| `ModelStep` | `ModelBlock` | base | 1 |
| `WorkingImages` | `ImageConverter` (preset `working-image@1` in phase 3) | conversion | 1 |
| `AttachImage` | `ImageFetcher` | conversion | 1 |
| `LayoutStep` | `LayoutDetector` | layout | 1 |
| `SingleRegionLayout` | `LayoutDetector` with the engine `layout.single-region.v1` | layout | 4 |
| `LinesStep` | `LineDetector` | lines | 1 |
| `AssignLinesToRegions` | `LineAssigner` | lines | 1 |
| `RecognitionStep` | `LineRecognizer` | recognition | 1 |
| `ChatRegionStep` | `RegionRecognizer` (backend `chat` in phase 4) | recognition | 1 |
| `ChatPageStep` | `PageRecognizer` (backend `chat` in phase 4) | recognition | 1 |
| `TablesStep` | `TableRecognizer` | recognition | 1 |
| `FormulasStep` | `FormulaRecognizer` | recognition | 1 |
| — | `TranscriptionConverter` | conversion | 4 |
| `NormalizeUnicode` | `UnicodeNormalizer` | text | 1 |
| (inside `text.py`) | `CharacterNormalizer` | text | 3 |
| `Typography` | `Typographer` | composition | 1 |
| (inside `document.py`, `text.py`) | `Recomposer` | composition | 3 |
| `ComposePage` | `Composer` | composition | 1 |
| `BindItem`, `ItemTexts` | `Binder` (+ `Recomposer`, `Composer` at the item level, + item writers) | binding | 3 |
| — | `Splitter` | binding | 3 |
| `ValidatePages` | `PageValidator` | validation | 1 |
| `RejectSink` | `RejectWriter` | writers | 1 |
| `RecipeStamp` | `RecipeStamper` | validation | 1 |
| `ServeModels` | `ModelServer` | servers | 1 |
| `ServeChatModel` | `ChatModelServer` | servers | 1 |
| `PageFilesWriter`, `PageExportsWriter` | `PageFileWriter` | writers | 1 |
| `ItemExportsWriter` | `ItemDocumentWriter` | writers | 1 |
| `ItemTextJsonlWriter`, `ItemTextFilesWriter` | `ItemTextWriter` | writers | 1 |
| `PageRowReader` | `PageRecordReader` | readers | 1 |
| other readers, `PageJsonlWriter`, `PageParquetWriter`, `ImageFilesWriter` | unchanged | readers, writers | |
| — | `ModularTranscriber` (composite) | composites | 2 |
| — | `PdfReader` (skeleton) | readers | 4 |

**Engines, adapters**

| Old | New |
|---|---|
| `KrakenRecognitionModel`, `PaddleLayoutModel`, `PaddleLineModel`, `PaddleRecognitionModel`, `PaddleTableModel`, `PaddleFormulaModel`, `TesseractRecognitionModel` | `…Engine` (ids unchanged) |
| `linecaster.models` | `linecaster.adapters` |
| `ChatModel`, `ChatPreset` | `ChatAdapter`, `ChatPreset` |
| `ChandraOCR`, `DeepSeekOCR`, `Dots`, … (`ADAPTERS`) | `…Adapter`; `ADAPTERS` stays the one registry |

**Pipeline scripts, ids, slots, flags**

| Old | New |
|---|---|
| `pipelines/transcribe_chain.py`, id `chain.v1` | `pipelines/transcribe_modular.py`, id `transcribe_modular.v1` |
| `pipelines/transcribe_vlm.py`, id `vlm.v1` | id `transcribe_vlm.v1`; slot `vlm` → `recognition` |
| `pipelines/harvest.py`, no id | id `harvest.v1` |
| `pipelines/bind.py`, no id | id `bind.v1` |
| `--recognizer` | `--recognition` |
| `--vlm`, `--vlm-endpoint` | `--recognition`, `--recognition-endpoint` |
| `--text lines\|reflow` | `--recomposition PRESET` |
| `--texts DIR` | `--item-texts DIR` |
| `--files`, `--exports` | `--files` with every per-page format |
| `--rows DIR`, `OUT/rows/` | `--pages DIR`, `OUT/pages/` |

**Catalog**

| Old | New |
|---|---|
| `STEPS = layout, lines, recognition, tables, formulas, page` | `layout, lines, recognition, tables, formulas, image, normalization, typography, recomposition, composition` |
| `presets/page/` | `presets/recognition/` |
| `<id>.md` with YAML front matter | `<id>.yaml` + `<id>.md` |
| `models/<id>/model.md` | `models/<id>/model.yaml` + `model.md` |
| `catalog.lock` | lock format `linecaster.lock/2` |
| "component" (the umbrella word) | "catalog entry" |
| "catalog" | "catalog" |

**Data model**

| Old | New | Phase |
|---|---|---|
| `ModelInfo` | `StepInfo` | 3 |
| `Transcription.model` | `Transcription.steps` | 3 |
| — | `Transcription.paragraphs` (`Paragraph`) | 3 |
| `measurements` (free keys) | a fixed vocabulary | 3 |
| transcription name `ocr` | `ocr_new` | 1 |

**Modules**

| Old | New |
|---|---|
| `transcription/model.py`, `page.py`, `geometry/` | `data/transcription.py`, `data/page.py`, `data/geometry/` |
| `transcription/alto.py`, `pagexml.py`, `hocr.py`, `_xml.py`, `_provenance.py` | `formats/` |
| `document.py` (DoclingDocument building and exports) | `formats/docling.py` (exports); the building moves to `engines/composition.py` (phase 3) |
| `text.py`, `unicode.py`, `reflow.py`, `retyper.py` | `text/variants.py`, `text/unicode.py`, `text/recomposition.py`, `text/typography.py` |
| `images.py`, `plots.py` | `images/convert.py`, `images/plots.py` |
| `blocks/*.py` (17 flat modules) | `blocks/<family>/` |
| `blocks/http.py` | `net/http.py` |
| `backends/` | `backends/in_process.py`, `served.py`, `chat.py` |
| `models/` | `adapters/` |
| `run.py`, `jobs.py`, `ray_executor.py`, `provenance.py` | `runtime/` |
| — | `engines/` (built-in), `tracing/`, `testing/`, `runtime/builder.py` |
| `specs/` | `docs/reference/` |
| `tests/test_*.py` (flat) | `tests/` mirroring `src/linecaster/` |

**Terms in prose**

| Old | New |
|---|---|
| chain, the chain pipeline | the modular pipeline (`transcribe_modular`) |
| document assembly, reflow | composition, recomposition |
| text version | text variant |
| axes | dimensions |
| book (generic) | item |
| page row, record | page record |
| model (for a page preset, an engine class or an adapter) | page preset, engine, adapter |
| connector | reader |
| British spelling | American spelling |

### Added

- `linecaster.testing`: sample pages (`sample_page`, `sample_boxes`, `sample_png`, `sample_layout`,
  `sample_document`, `sample_documents`, `sample_transcription`); fake CPU engines (`FakeLayoutEngine`,
  `FakeLineEngine`, `FakeRecognitionEngine`, `FakeTableEngine`, `FakeFormulaEngine`), registered as
  `fake.<step>.v1` by `register_fakes()` (`catalog.registry.REGISTERED`); `fake_chat_server()` and `completion()`;
  the conformance checks `check_engine` and `check_block` (with `transcription_changes` and `page_changes`); the
  pytest markers and hooks (`linecaster.testing.markers`). Every built-in engine and every public block has a
  conformance test.
- `linecaster.engines.api`: the `Engine` protocol, `Capabilities`, `weights_of`, `hf_file`, `hf_snapshot`,
  `model_entry`.
- Markers `gpu`, `network`, `slow`, `parity`; `gpu` and `network` tests skip where the device or the network is
  missing.
- Tests of each engine package in `engines/<engine>/tests/` (conformance on the CPU, and on CUDA for kraken, and
  units), run with `uv run tests/test_engines_catalog.py engines/<engine>/tests`; the engine READMEs give the install
  and test commands.
- A missing engine's `CatalogError` names the engine package that provides it and the pipeline scripts that install
  it (`catalog.code.install_hint`).
- The CI workflow `.github/workflows/ci.yml` (CPU, no secrets): `uv sync --locked --all-extras`, the tests without `gpu`,
  `network` and `parity`, `linecaster docs --check`, `linecaster catalog verify`, the strict site build.
- `tests/integration/ray_data_spike.py`: the squiddle blocks through Ray Data (NOTES.md, 2026-11-06).

- The block pages (`docs/blocks/`): an index by family and a page per block with its contract, backends, catalog
  step and presets, where it comes in a pipeline, the pipeline scripts that use it, its options, behavior and
  example, all from code; blocks whose constructor needs arguments declare `docs_args` for them.
- The docstring standard (`docs/reference/conventions.md`, "Docstrings") and `tests/test_docstrings.py`: every
  public block, built-in engine, backend, serializer, `build`, `run_pages`, `runtime.run.main` and public catalog
  function has a summary line and `Args:` for its whole signature; examples for the serializers, `build`, `main` and
  the catalog functions.
- `docs/reference/architecture.md`, `docs/reference/compatibility.md` (what counts as a breaking change), READMEs
  for the engine packages, and the docs site (`mkdocs.yml`).
- Tests: the generated docs are current, and the README's "Your own pipeline" builds and checks.

- The `Chat` backend (`linecaster.backends.Chat`) for `PageRecognizer` and `RegionRecognizer`.
- `TranscriptionConverter(format="auto"|"alto"|"page"|"hocr"|"text", source="media"|"uri",
  transcription="ocr_original", uri_key=None)` (conversion): a library's own transcription delivered with the page,
  or named by a URI in its metadata, read at the page image's size.
- The engine `layout.single-region.v1` and its preset `single-region@1`.
- IIIF Collections (a skeleton): `ManifestReader` reads a collection entry as its manifests, one item each, one level
  deep (a collection in a collection raises `NotImplementedError`), with pybookget's `read_collection` (a pybookget
  that has it).
- `PdfReader(data_folder, paths_file=None, glob_pattern="**/*.pdf", dpi=300, ...)` (a skeleton, extra
  `[pypdfium2]`): one item per PDF, its pages rendered as lossless WebP; the text layer (`text_layer=True`) raises
  `NotImplementedError`.
- Block contracts (`contract()`, `Part`, `Contract`, `PARTS`), the builder (`linecaster.runtime.builder`: `build`,
  `Plan`, checks, branches with `when=`/`group=`, composites, stages, `run_pages`), observers
  (`linecaster.runtime.observers`), the composite `ModularTranscriber`, the error classes (`linecaster.errors`),
  partial runs (`--until`, `--after`, `--tap-after`), `--page IMAGE` and `linecaster page`;
  `docs/reference/pipelines.md`.
- `docs/reference/glossary.md` and `docs/reference/conventions.md`.
- `warm_up()` on every block and backend, with the observers' `on_warm_up(block, seconds)`; per-page failures,
  `RejectWriter` as a block, the error budget (`--max-page-errors`, `build(max_page_errors=...)`).
- `to_dict()` on every block, backend and chat adapter; the run record's pydantic model
  (`linecaster.runtime.record.RunRecord`, `schemas/run-record-1.json`); `provenance.functional_pipeline` and
  `pipeline_sha256`; `--new-pipeline`.
- The describe mode (`runtime.run.describe_script`, `describe_recipe`, `load_script`, `parse`); a recipe edition's
  expanded pipeline in the lock (`pipeline`, `pipeline_sha256`), checked by `catalog verify`; `catalog release
  --migrate-pipeline`. `squiddle@1` has its pipeline recorded.
- Secrets as references: `linecaster.runtime.secrets.EnvVar`; `Served(api_key=..., headers=...)`.
- `linecaster.runtime.logs` (JSON-lines task logs), `runtime.jobs.JobsExecutor`.
- Tracing (`linecaster.tracing`, `docs/reference/tracing.md`): task spans, page traces sampled by page id
  (`--trace-sample`, `build(trace_sample=...)`, default 0.01) plus every failed page, `OUT/traces/<rank>.jsonl.gz`
  (OTLP JSON lines) and OTLP/HTTP when the `OTEL_*` variables say so; served blocks send the page's `traceparent`
  in the request body and `linecaster serve` continues it (`--traces FILE`, `LINECASTER_TRACES`);
  `ChatModelServer` starts vLLM with `--otlp-traces-endpoint` when OTLP is configured; fetch spans from
  `net.http.HTTPFetcher` (`fetch_record`); `trace_id` and `span_id` on log records; `linecaster traces OUT [--by
  block|preset|task] [--slowest N] [--json]`.
- Rule-based engines (`linecaster.engines`): `image.webp-lossless.v1`, `normalization.latin-historic.v1`,
  `typography.ratios.v1`, `recomposition.unicode.v1`, `composition.docling.v1`, the engine protocol for page and
  item units, and dispatch by script (`ScriptDispatch`, `linecaster.engines.scripts`, `normalization.by-script.v1`,
  `recomposition.by-script.v1`, a preset's `by_script`); their pages in `docs/catalog/engines/`. Every threshold of
  the typography and the recomposition is an option (today's values the defaults). The recomposition makes
  `Transcription.paragraphs` with their rows and decisions (division marks removed and hyphens kept with the reason,
  paragraph breaks, continuations with their separator), continues paragraphs across regions and, recomposing an
  item, across pages (a page number between them does not close one), grows the item's lexicon page by page, and
  recomposes text-only transcriptions (a region one paragraph); `CharacterNormalizer` fills `Paragraph.normalized`
  too.
- Presets of the rule-based steps, edition 1: `working-image`, `latin-historic`, `ratios`, `unicode-recomposition`,
  `docling-composition`; `pipelines/transcribe_modular.py` runs `ratios@1`, `unicode-recomposition@1` (with `--text
  reflow`) and `docling-composition@1`.
- Item records in a stream (`linecaster.blocks.base.item`: `doc.metadata["item"]`, the pages in order) for the
  item-unit `Recomposer`, `CharacterNormalizer` and `Composer`; `Binder` (pages → item records) and `Splitter` (item
  records → pages, with what the item-level steps added); the recipe `item-texts@1` (`bind.v1`).

### Fixed

- `PageRecordReader(fetch_images=True)`, `ImageFetcher` and `ImageConverter` dropped the fragment of
  `page.image.uri` and fetched the whole file: for a `PdfReader` page (`file.pdf#page=n`) the PDF, for an
  `ImageParquetReader` row with embedded bytes the Parquet file. A PDF page is now rendered as `PdfReader` renders it
  (at the record's `metadata["pdf"]["dpi"]`), a Parquet row's image read (columns `id` and `image`), and any other
  fragment is the page's error (field `image`), never the wrong bytes (`linecaster.blocks.readers.fragments`).
- `ImageConverter` without `keep_bytes` declared only `metadata` replaced although the page leaves without its image
  bytes: its contract now removes `image`, so the builder no longer treats the image as available after it.
- `ImageFilesWriter` rewrites `page.image.uri` and `extra` (to name the copy) without declaring it: its contract now
  replaces `metadata`.
- `RegionRecognizer` replaces the transcription's earlier lines but declared `lines` only as added: its contract now
  replaces `lines` and `text`, so it may follow a line step.
- `RegionRecognizer` ignored an explicit `pad` when the adapter has a `region_pad`.
- `RegionRecognizer` failed the task on a page without image bytes; the page now carries the error (found by
  `check_block`).
- `PageValidator(required=("image",))` declared that it reads the image bytes, although it checks the page record's
  `image` entry: a page field is now read as `metadata`, so the validator may follow an `ImageConverter` that
  removes the bytes.

- `PageParquetWriter` writes a fixed schema: datatrove took a file's columns from its first row, so a page's
  `errors` were dropped when the first page of a file had none. Page records in Parquet now always have an `errors`
  column (null without errors).
- Tracing holds no page documents: a page a block drops no longer stays in memory, with its image, until the task
  ends; its trace ends when the next page enters that block.
- A sampled page's `metadata.trace_id` is derived from the run and the page id, so a rerun of a run writes the same
  page records.
- `runtime.jobs.dependencies()` reads the pipeline script and its lock as they are at the commit the Jobs install,
  not as the checkout holds them (with a warning when the commit is not in the checkout).
