# Running at scale

Where a run runs, how it is divided into tasks and workers, which pages it reads, what it shows while it runs, and
how it gets its credentials and its Jobs. Terms are the [glossary](glossary.md)'s; what a pipeline is made of is in
[pipelines](pipelines.md), fetching over HTTP in [http](http.md).

## Where a run runs

The pipeline is the same everywhere; the command line names the machine.

| Where | Flags |
|---|---|
| this machine | none: the models load inside the pipeline |
| this machine, with a model server | `--backend served`, or `--endpoint URL` for a server that is already up |
| a Ray cluster | `--on ray --tasks 64` |
| Hugging Face Jobs | `--on hf-jobs --namespace NS --commit <sha>` |
| a Slurm cluster | from Python, with datatrove's `SlurmPipelineExecutor` |

On Ray and HF Jobs every task holds one GPU and starts its own model server. A rerun into the same output folder
runs only the tasks that did not finish. The executors behind `--on` are in
[architecture](architecture.md#executors-and-jobs).

### A model server that stays up

A pipeline script serves its own models with `serve`, and a run then names the server's address:

```bash
P="--layout pp-doclayoutv3 --lines pp-ocrv6-medium-det --recognition paddlex-ppocrv6-medium"
uv run pipelines/transcribe_modular.py serve $P
uv run pipelines/transcribe_modular.py scans/ out/ $P --endpoint http://127.0.0.1:8100/v1
```

A recipe's script serves its models too: `uv run launch.py squiddle serve`, then
`uv run launch.py squiddle scans/ out/ --backend served --endpoint http://127.0.0.1:8100/v1`. For a vision-language
model, `--recognition-endpoint` points `transcribe_vlm.py` at a running vLLM or SGLang. Servers listen on loopback
only.

### Ray

`ray` runs Ray's own command line with the pipeline's packages, so every machine has the same versions:

```bash
uv run pipelines/transcribe_modular.py ray start --head --num-gpus 8
uv run pipelines/transcribe_modular.py scans/ out/ $P --on ray --tasks 64
```

Images, output and the logging folder must be on storage every machine can reach, such as an `s3://` bucket.

Each task reserves one GPU, `--cpus-per-task` CPUs (default 12) and memory: `--mem-per-cpu-gb` GiB per CPU
(default 4, so 48 GiB), or `--mem-per-task-gb` GiB whatever its CPUs. Start every worker with at least that much
(`ray start --num-cpus`, `--memory`, `--num-gpus`). Before it submits anything, a launch checks that a live node can
run a task, and stops with what a task needs and what the nodes have. It also logs how many tasks fit at once.
`--no-fit-check` leaves the check out, for a cluster that adds nodes on demand. Each task sizes its thread pools
(OpenMP, BLAS, OpenCV, torch) to its CPUs, not to the machine's.

On Kubernetes, one Deployment can run the head and another the workers:

- Start Ray in each pod through the pipeline script (`uv run pipelines/<script>.py ray start …`), so the pods run
  the script's locked packages.
- Give each worker pod the CPUs, memory and GPU a task reserves, plus room for `/dev/shm` (Ray's object store),
  and pass the same amounts to `ray start --num-cpus/--memory/--num-gpus`. A pod with one GPU holds one task.
- With the data on object storage the pods need only ephemeral storage: the environment, the model weights and
  Ray's temporary files.
- Submit the run to the head with `ray job submit`, so it runs inside the cluster and outlives the session that
  submitted it. A driver outside the cluster must reach every node.

### Hugging Face Jobs

Each Job has one GPU and installs linecaster at a pushed commit with the pipeline's pinned dependencies:

```bash
uv run pipelines/transcribe_modular.py s3://<bucket>/images hf://buckets/<ns>/<bucket>/<run> $P \
  --paths-file hf://buckets/<ns>/<bucket>/pages.txt --env FSSPEC_S3_ANON=true \
  --on hf-jobs --namespace NS --commit <sha> --tasks 4000 --workers 64
```

`--workers` Jobs run at once. `--flavor l4x4 --gpus 4` runs four tasks per Job. `--dry-run` launches nothing.
How a Job gets its dependencies is in [HF Jobs helpers](#hf-jobs-helpers).

### Slurm

A `Pipeline`'s components run on a Slurm cluster through datatrove's Slurm executor: one array job, one GPU per
task, in an environment that has the engines (`venv_path`):

```python
from datatrove.executor import SlurmPipelineExecutor

SlurmPipelineExecutor(
    pipeline.steps(), tasks=64, time="04:00:00", partition="gpu",
    gpus_per_task=1, venv_path="/path/to/venv",
    logging_dir="out/logs").run()
```

## Large collections

For a large collection, fetch the images once, then transcribe them, then bind the pages into items. Each
pipeline reads the page records the one before it wrote:

```bash
uv run pipelines/harvest.py --manifests items.parquet --manifest-key url OUT --rate-limit 5/1
uv run pipelines/transcribe_modular.py --pages OUT/pages OUT2 --layout pp-doclayoutv3 \
  --lines pp-ocrv6-medium-det --recognition paddlex-ppocrv6-medium --item-shards 64
uv run pipelines/bind.py OUT2/pages OUT3 --paragraphs unicode-paragraphs --document linked-document \
  --text literal:txt --text latin-historic+flow:md
```

The harvest writes each item's images into a folder of its own and one page record per page. `--item-shards`
writes each item whole into one shard, which `bind.py` reads ([the item stage](pipelines.md#the-item-stage)).

## Samples

A run reads a **sample** of its input with a sample rule: `--sample N` (at most N pages in all), `--sample-per-item K`
(at most K pages of each item), `--sample-items M` (at most M items), `--sample-seed S` (default 0); any of the first
three alone or together. The sample is chosen by the ids of the input's listing alone, before any image is read or
fetched, and is the same whatever `--tasks`, executor or machine: an evaluation then scores every system on the same
pages, and others can recompute them from the list of ids without linecaster.

The rule (`linecaster.data.sample`, `linecaster.sample/1`), with `H(s)` the first 8 bytes of `sha256(s)` (UTF-8) as
an unsigned big-endian integer:

1. The listing is the input's distinct `(item_id, page_id)` pairs; a page without item has the item id `""`. An id
   with a tab is an error.
2. Items are ordered by `(H(f"{seed}\t{item_id}"), item_id)` (the **item rank**), and only the first M are kept.
   An item without pages takes no rank.
3. Within an item, pages are ordered by `(H(f"{seed}\t{item_id}\t{page_id}"), page_id)` (the **page rank**), and
   only the first K are kept; an item with fewer pages gives them all.
4. The pages, in the order (item rank, page rank), are cut after the first N.

The page hash includes the item, so items whose pages are named alike (`0001.png` in every item folder) do not all
give the same positions. A rank depends only on its ids and the seed: an item added to the input moves no other
item's pages, and a sample of N is the first N pages of a sample of 2N. With K the first N pages come from about N/K
items. In Python:

```python
import hashlib

def h(*ids):
    return int.from_bytes(hashlib.sha256("\t".join(map(str, ids)).encode()).digest()[:8], "big")

def sample(pairs, seed=0, n=None, k=None, m=None):
    items = {}
    for i, p in dict.fromkeys(pairs): items.setdefault(i, []).append(p)
    order = sorted(items, key=lambda i: (h(seed, i), i))[:m]
    return [(i, p) for i in order for p in sorted(items[i], key=lambda p: (h(seed, i, p), p))[:k]][:n]
```

The first 16 hex digits of the SHA-256 sort as `H` does, so SQL can order by them. A stratum is a separate run over
a filtered input.

**Per input** (the readers' `sample`, `linecaster.components.readers.sampling`):

| Input | Ids | Read before the sample | The tasks |
|---|---|---|---|
| IMAGES (`--item-from-parent` for items) | the parent folder, the file name without extension | the file listing | the sample's files in turn |
| `--parquet` (`--item-key` for items) | `--id-key`, or `<item>_<0001>` from `--item-key` and `--sequence-key` | the id columns only | the sample's rows in equal shards (by item with `task_per_item`); a row's image is read with the other sample rows of its row group |
| `--manifests` | the item id of each entry, `<item>_<0001>` for its pages | the item ids; then the manifests of the items in rank order, as far as the rule reaches (every one with `--sample-per-item` alone) | the sample's items as the entries would be; only their sample pages' images are requested |
| `--pages` | `page.item_id`, `id` | every record (no image) | their files as without a sample, passing on the sample's records alone |

`--sample-per-item` and `--sample-items` need items. An id listed twice is read once (its first entry), counted in
the record's `duplicates`. With `--manifests` the manifests the sample reads are saved to `OUT/manifests/` with an
index (`sample.jsonl`: item id, entry, the URL it was read from, the copy's file, its pages); the tasks read those
copies instead of fetching them again, and so does a resume when it computes the sample again. A manifest that
cannot be read, or a IIIF Collection entry, stops the launch: the sample would depend on it. `--max-pages` and a
sample exclude each other; `--limit` and `--skip` still count per task, over the task's share.

The launch computes the sample once, before the tasks (`linecaster.execution.run.sampled`); it travels with the pickled
pipeline, and each task takes its share. It is recorded in the run record's `sample` section:

| Field | Holds |
|---|---|
| `rule`, `hash` | `linecaster.sample/1` and the hashes in words |
| `pages`, `items`, `per_item`, `seed` | N, M, K and S |
| `listing` | `scope` (`pages`, or `items` for manifests, whose pages are known once read), `items`, `pages`, `duplicates`, `manifests_read`, `sha256`: of the distinct sorted lines `item_id<TAB>page_id` (for manifests `item_id`), each with a newline |
| `selected` | `items`, `pages`, `sha256`: of the sample's lines `item_id<TAB>page_id` in sample order, each with a newline |
| `file` | `sample.parquet` |

`OUT/sample.parquet` (`linecaster.execution.sample`) holds one row per sample page in sample order: `rank` (1-based: a
sample of N is `rank <= N`), `item_id`, `page_id`, `item_rank`, `page_rank`, `item_hash`, `page_hash` (unsigned 64
bit) and `item_pages` (the item's pages in the listing), with the record's section in the file's metadata
(`linecaster.sample`). The same sample gives the same rows and metadata, and with the same pyarrow the same bytes;
`selected.sha256` compares samples across versions. `linecaster sample [IMAGES] OUT` with the input and
sample options writes it without a run (with `--manifests`, the manifests too), as a run with the same options would.
A sample's options are operational parameters (the pipeline's hash leaves them out); a resume with another sample is
refused.

## Tasks, workers and rate limits

`--tasks` and `--workers` are chosen when the command line leaves them open (`linecaster.execution.run.allocate`):

| Pipeline | `--tasks` | `--workers` |
|---|---|---|
| with engines | 1 | every task |
| without engines, every rate-limited host through proxies (`--proxies`, an HTTP policy's `proxies: {file}`), local or Ray (`--on hf-jobs`: as below) | the reader's `auto_tasks` (from the input), else 1 | sharing them fairly (`proxies: {per_worker: share}`, the default): one per available proxy, at most one per CPU; with `per_worker` 1 or N: one per available proxy divided by N (`ceil(available / N)`), not capped by the CPUs; either way at most the tasks and, with OUT on object storage, at most 64 (`OBJECT_STORAGE_WORKERS`) |
| without engines, with `--rate-limit` (a host with rate limits and no proxies) | the reader's `auto_tasks`, else 1 | 1 |
| without engines, without `--rate-limit` | the reader's `auto_tasks`, else 1 | one per CPU, at most the tasks |

The available proxies are counted once at launch from one listing of the broker
(`linecaster.execution.run.available_proxies`): those in the file, less those with a live block or broken mark for the
run's hosts (any host when the hosts are not named in an HTTP policy) and those leased by live workers of other runs
(the run's own earlier leases count as available); on a first launch, without a broker yet, all of them. Sharing
the proxies fairly, a few workers use them all, so their count stops at the CPUs; with one proxy per worker (or up to
N) using them all takes a worker per proxy (per N), and the workers mostly wait on the network, so their count is not
capped by the CPUs. With OUT on object storage (any fsspec protocol but a local one: `s3://`, `gs://`, `hf://`,
`az://`, ...) the count stops at `linecaster.execution.run.OBJECT_STORAGE_WORKERS` (64) in both modes: in one setup,
250 workers writing to S3-compatible object storage hung in their listings of `OUT/images` and fetched less than 64
did, which ran cleanly; an observation from that setup, not a guarantee for others. The run states the count and why
(`linecaster.execution.run.workers_note`, e.g. `250 proxies available, OUT on object storage → 64 workers, a fair
share each`, or `250 proxies available → 250 workers, 1 proxy each`). `--workers` overrides it (each worker is a
process with its own memory).

`auto_tasks` is about 1,000 pages per task for `ImageParquetReader` and about 5 items per task for `ManifestReader`
(`linecaster.components.readers.tables.PAGES_PER_TASK`, `ITEMS_PER_TASK`), so a resume repeats little. The harvest
(`pipelines/harvest.py`) asks its reader for one item per task (`task_per_item`): the tasks divide the items, an
item's rows wherever they are in the table (`tables.item_runs`), so every item is whole in its task and a task that
fails costs one item. With `--reuse` (off by default: on some object storage a listing is slow even for an empty
folder, and only the items a stopped launch was in, or with `--retry-failed` the finished items with failed pages,
have anything to reuse) its reader also gets `reuse_folder`
(`OUT/images`): when it reaches an item it lists the item's
folder once (an fsspec listing) and reads a page whose image file is already there from the storage instead of
fetching it from the source (`linecaster.components.readers.existing`); only pages of interrupted items (and of the items
`--retry-failed` runs again, whose failed pages alone are then fetched) are read back, so egress stays small. The reader waits at most `LISTING_TIMEOUT` (60 s) for a listing (on object storage fsspec cancels
it then on its IO loop): one that times out or fails is a warning and a stat (`reuse_listing_timeouts`,
`reuse_listing_errors`), and the item's pages are fetched again, their files overwritten. Such a record is complete and says `image.extra.reused`; the console counts it as done but not in
the rate. On a restart the console's size starts with the finished tasks' `media_size` from datatrove's stats files
(`linecaster.execution.local.size_before`, read in the background). Parquet tables are
divided over the tasks by rows in equal shards, not by files, so a table never needs splitting for a task count.
`--max-pages N` (`--parquet`, IMAGES; the readers' `max_pages`) reads the input as if it ended after its first N
pages, in the same automatic tasks: a smoke test of the real setup. `--limit` counts per task, as in datatrove. The
same pages for every setup and input order: a [sample](#samples).

`--rate-limit` holds per worker: each worker process has one fetcher with its limits (`HTTPFetcher.shared`), so a
server sees the workers running at once times the limits; the run states it before it starts
(`linecaster.execution.run.rate_note`, e.g. `rate limits per worker: 150/60, 3/1 · 1 worker → up to 150/min at a
server`). One worker keeps any rate limit busy: a reader's requests ahead grow while none waits for the limits
(`linecaster.net.http.prefetched`, at most `MAX_AHEAD`), and the fetcher, with its limits and the window it has
grown to, is shared by the tasks a worker runs one after the other (`HTTPFetcher.shared`). With `--proxies` the
limits hold per proxy instead (below), and the run states that (`rate limits per proxy: 150/60 · 100 proxies → up to
15,000/min at a server`; with fewer workers than proxies `· 10 of 100 proxies in use (1 proxy per worker)`).

**Proxies.** `--proxies FILE` sends the http(s) requests through a list of proxies, shared by the workers through the
[broker](broker.md) (`--broker PATH`, any fsspec folder, default `OUT/logs/broker`; runs pointed at one path share
the proxies and their blocks too). Each proxy has one worker at a time, the one that holds its lease, and each worker
holds a fair share of them (`linecaster.net.proxies.ProxyPool`, `per_worker: share`, the default): of the
proxies not blocked for the host, divided by the live workers, claimed at most 2 at a time and grown by rebalancing,
which also gives back what is beyond it when another worker joins. An HTTP policy's `proxies: {per_worker: ...}` (per
host or at the root; hosts that share a list share the setting) gives a worker one proxy instead (`1`: it claims a
free one usable for the host and, when that one is blocked or broken, releases it and claims another at once), or up to N,
claimed one by one; with output on local disk or a short list, one per worker and a worker per proxy is the simplest
way to use them all. The host's rate limits hold per
proxy, so per IP, as servers count them: the owner spaces the requests through a proxy to a host by the strictest
limit, and each request goes through the owned proxy whose turn comes first. A proxy is left out when the failure is
its own ([http](http.md#blocks)). A block (a status in the host's `block_on`, 429 by default, and with `html` there an
HTML page where another format was expected) is a mark in the broker for that host, until its `Retry-After`, else for
60 s, doubling on each repeat up to the host's `block_ttl` (an hour by default): the owner stops using the proxy there
at once, releases it once it is blocked for every host it uses, and whoever claims it later sees the mark, so no
worker sends a request into another's block, and a restarted run none into a block it found before. A broken proxy (a
proxy error, no connection to it, `broken_after` failures in a row, 3 by default) is marked for every host, first for
`broken_ttl` (5 minutes), doubling up to `block_ttl`. A block does not count as an attempt and the request goes on
through another proxy at once, so `max_retries` (retries after the first attempt) counts only the attempts that
reached the server and failed there; a component does not count toward the breaker either. A timeout is mostly a slow
server: it is retried and leaves the proxy in. When none of a worker's proxies is usable for a host and none
is free to claim, its requests to the host pause until a block ends or another worker gives a proxy back (one warning
when the pause starts, one when it ends; the wait is in the fetch record's `pause_seconds`); once the waits since the
host's last successful response would pass its `max_pause` (6 hours; [http](http.md#max_pause)) the run stops
(`StopRequests`) and says when the first proxy returns. An HTTP policy
can set `proxies: {block_ttl: 72h, broken_after: 1}` and further statuses that block at the host (`block_on: [429,
403]`, `block_on: [429, html]`). The console shows the proxies the worker holds, those blocked and those free. On Ray
each task is a process of its own; the next task on a machine takes over the worker slot the last one handed over, and
with it its proxies. The file holds one proxy per line, a URL or `host:port[:user:pass]` as Webshare lists them; the
run record keeps its name, logs show proxies without credentials (`linecaster.net.http.redact`), and the broker names
them by a hash of host and port.

**Failures.** Each fetcher has a breaker (`linecaster.net.http.Breaker`): when most attempts of the last minute got a
server error (5xx, Cloudflare's 520-524 among them), its requests pause, a probe goes out now and then (waits doubling
from one to ten minutes), and the first answer that is not a server error lets them go on; the pages wait instead of
failing. A single server error is retried (with a proxy list without counting against the proxy it came through). A
block on a direct connection (a status in the host's `block_on`, 429 by default) pauses the worker that got it
(`linecaster.net.http.Pause`): its requests to that host wait until the response's `Retry-After` has passed (seconds
or an HTTP-date; without one a minute, doubling while components keep coming), then the request that got it is tried
again, without using up one of its retries; blocks for requests already in flight extend the pause, never shorten
it. The pages wait instead of failing, and the requests to other hosts and other workers go on. The log says when a pause starts (host,
status, how long, until when) and when the requests go on, and a page's fetch record has the time paused
(`pause_seconds`). A worker that would pause more than the host's `max_pause` (6 hours) since its last successful
response stops the run: the worker waits, or stops when the wait would be too long ([http](http.md#max_pause), one
count for both paths). Through proxies a block leaves
that proxy out at the host instead (above). An HTML page where an image, XML or JSON was expected is a failed attempt,
retried like a server error, unless the host's policy makes it a block or a stop ([http](http.md#unexpected-html)). A
local task that fails is logged and the others go on (`LocalExecutor`); it runs again on the next launch. An error
that is not the pages' (`NOT_THE_PAGES`) or `FAILED_IN_A_ROW` failed tasks in a row in one worker stop the run.
`--retry-failed` runs the finished tasks that left rejects again; `kill -USR1 <pid>` dumps every thread's stack.
On Ray (`linecaster.execution.ray.RayExecutor`) the same error stops the run through a marker in the logging folder
(`stopped.json`): every task after it ends before its pipeline starts, so none sends a request into the component that
stopped the first, and the launch fails with that task's error; a launch that left tasks unfinished fails too, so the
Ray job does not end as succeeded. A new launch removes the marker. Before it submits a task, a Ray launch checks
that a live node has what a task reserves (`--cpus-per-task`; `--mem-per-task-gb`, else `--mem-per-cpu-gb` per CPU;
one GPU for a stage with models) and stops with a `PipelineConfigError` if none has, where Ray would keep the tasks
waiting without an error; `--no-fit-check` leaves the check out, for a cluster that adds nodes on demand. A task sizes
the native thread pools to the CPUs it may use (`linecaster.execution.cpus`: its Ray CPUs, else the cgroup's CPU quota),
and so do the worker counts a launch derives "one per CPU".

**Resources.** `pipelines/harvest.py --items TABLE --item-key COL` fetches items' remote files other than page images
(`ResourceReader`): from URL templates per kind (`--resource marcxml=https://catalog.example.org/{item}/marcxml`) or
a table with one row per resource (`--url-key`, `--kind-key`, `--name-key`). Each is checked (XML, JSON or an image must parse, a DjVu file must start with its signature;
an HTML page where another format was expected is retried, and a resource that fails with it counts toward the
breaker) and kept as a raw copy,
`OUT/<kind>/<item>/<name>.<ext>` (`ResourceFilesWriter`), the reference later stages link to, with its fetch record in
`OUT/resources/<rank>.jsonl.gz` (`ResourceRecordWriter`: source and final URL, status, type, size, `sha256`, ETag,
Last-Modified, time). One item per task, `--max-items` for a smoke test, copies already there read back. `--http-policy FILE`
gives the run's requests their settings from one YAML file (`linecaster.net.policy`, [http](http.md#the-http-policy)):
for every host at the root, and under `hosts:` an entry for each host that differs, whose fields replace the root's;
the run's own options go between the two. The settings: rate limits (per proxy through proxies), retries
(`max_retries`), deadline, User-Agent, what blocks (`block_on`, default `[429]`; with `html` an HTML page where
another format was expected) and what stops the run without a retry (`stop_on`: statuses and `html`; something in
both `block_on`, or its default, and `stop_on` is refused, so `block_on: []` with `stop_on: [429]` stops on a 429),
`max_pause`, `direct`, the proxy path's own section (`proxies: {file, per_worker, block_ttl, broken_after,
broken_ttl}`) and the broker (root only). The run states the rules that hold per host before it starts. For every
input fetched over http(s): `--items`, `--parquet` with http(s) image URLs, `--manifests` (the manifests, their
images and OCR files) and `--pages` (the images it fetches again); with rate limits in the file for a host without
proxies a run keeps one worker, with proxies for every rate-limited host its workers follow the available proxies
(above).

The default User-Agent is datatrove's, `HF-Research/1.0` (`linecaster.net.http.USER_AGENT`), deliberately: datatrove
is integral to linecaster, and its media fetcher (`HTTPFetchReader`) sends the same, so a run that fetches through
both presents itself as one client to every host. `--user-agent` or an HTTP policy's `user_agent` sets another.

## The console

A local run (`--on local`, `linecaster.execution.local.LocalExecutor`) shows on the terminal: one line naming the
pipeline (its components, without the builder's boundaries; pages, tasks and workers; what an earlier launch finished), a
live progress line (pages done of the total, rate over the last five minutes, size, failed pages, the task, the time
left) pinned to the terminal's top row, with everything else scrolling below it (a scroll region, `Pinned`), a line per finished task and a summary, in human units
(`linecaster.execution.console`). The `Progress` observer, which the runtime puts on every stage, counts the pages
that leave the pipeline; with several workers each worker process reports its counts to the console about every
second. Off a terminal the progress is a log line every 30 s instead.
datatrove's own console output (its pipeline listing and stats component per task, the merged stats) goes only to the
task logs (`OUT/logs/logs/task_<rank>.log`, in its full line format) and the stats files, which keep it whole. A launch
lists the completion markers once instead of looking them up task by task.

## Secrets

`linecaster.secrets.EnvVar("NAME")` names an environment variable; the value is read in the task
(`resolve()`), never stored: an `EnvVar` pickles by name, `to_dict()` writes `{"env": "NAME"}`.
`Served(endpoint, model, api_key=EnvVar("NAME"), headers={"X-Team": "ocr", "X-Token": EnvVar("TOKEN")})` (and
`Chat(preset, endpoint, api_key=..., headers=...)` alike) sends `Authorization: Bearer <key>` and the headers with
every request through saturate's `AdaptiveClient(headers=...)`;
a key given as text is refused. A missing variable fails the component's warm-up.

## HF Jobs helpers

A launch with `--on hf-jobs` names `--namespace`, the Hugging Face user or organization the Jobs run under and are
billed to, and `--commit`, the linecaster commit the Jobs install (pushed). Neither has a default, and the namespace
is not taken from the logged-in account, so the account a run spends is always the one its command line and run
record name. `--commit` is required for linecaster's own scripts; a downstream project's script outside the linecaster
checkout that takes linecaster from a git tag, branch or rev runs without it (`jobs.needs_commit`), since its Jobs
install what its sources name.

`linecaster.execution.jobs.dependencies(commit, script=None, engines=True)` spells out what a Job installs from a
pipeline script, linecaster's or a downstream project's, as `Dependencies`:

- `requirements`: the script's dependencies with their sources as PEP 508 URLs (`url` as it is; `git` with its
  `tag`, `branch` or `rev` and its `subdirectory`, as `git+URL@REF#subdirectory=DIR`; a `path` into the linecaster
  checkout as GitHub's source archive of linecaster at `commit`, any other path an error), then every package
  reachable from them in the script's lock that comes from no index (the sources the packages declare themselves:
  the kraken fork at its locked commit, the OpenCV stub);
- `constraints`: every package reachable from them that the lock takes from an index, at the lock's version
  (`name==version`; a package the lock holds at several versions with its resolution markers), so a Job resolves the
  versions of the lock; none for a script without a lock;
- `overrides`: the script's `[tool.uv] override-dependencies` (a lock that resolves only with them, such as
  `transcribe_page.py`'s `pillow==12.3.0` over surya-ocr's `pillow<11`).

linecaster's `ray` extra is left out. `engines=False` keeps linecaster with its extras and the sources they need, and
the constraints of what those reach; without a script it raises unless `engines=False` (linecaster alone). A
downstream project's pipeline runs on Jobs from its own script (its sources pinned to a linecaster tag), read as it is on disk.

`uv run --with` (datatrove's way of installing a Job's dependencies) ignores constraints and overrides, whether given
as `UV_CONSTRAINT`, `UV_OVERRIDE` or a `uv.toml`; only a script's own `[tool.uv]` brings them to `uv run`. So
`JobsExecutor` given `Dependencies` uploads, in place of datatrove's `launch_pickled_pipeline.py`, a uv script of the
same name whose inline metadata holds the requirements, `constraint-dependencies` and `override-dependencies`
(`Dependencies.script`) and which then runs datatrove's launcher. Constraints only bound what the requirements bring:
a package the lock holds for another platform is not installed. `--dry-run` prints the three lists; the run record
keeps them (`dependencies`, `constraints`, `overrides`).
