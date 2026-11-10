# Broker

The broker is a shared folder through which workers across tasks, runs and machines agree on who uses which shared
resource and what is unavailable until when. It is any datatrove `DataFolder` (a local folder, S3, any fsspec path)
that every worker can reach: no server, no lock service, no queue. Workers write small JSON files, list the folder
and read the modification times the storage reports. The code is `linecaster.broker`; proxies are the first kind of
resource it coordinates (`linecaster.net.proxies`).

Terms are the [glossary](glossary.md)'s: **broker**, **lease**, **mark**, **worker identity** (worker slot).

## Why

A worker that keeps something to itself (a rate limiter, a list of blocked proxies) is right only if no other worker
uses the same thing. Servers count requests per IP, so per proxy, and block per IP; a run has many workers (local
processes, Ray tasks, HF Jobs) on several machines, and several runs may use the same proxies. The broker gives each
proxy one owner at a time, so what the owner enforces for it holds for everyone, and makes a block that one worker
found visible to whoever uses that proxy next.

## Layout

```
<broker>/
  broker.json                          {"format": "linecaster.broker/1", "created": ...}
  workers/<worker>.json                heartbeat: machine, slot, run, started, renewed
  slots/<machine>/<n>/leases/...       the worker slots of a machine
  <kind>/<resource id>/
    leases/<claimed>-<worker>.json     who holds it, since when
    marks/<scope>/<until>-<n>.json     what holds for it until when
```

The layout is versioned (`broker.json`'s `format`) and neutral: a kind of resource is a folder name and its resources
are ids, so a new kind needs no change of the protocol. File names are deterministic (times, worker ids, counters;
no random parts).

| Kind | Resource id | Leases | Marks |
|---|---|---|---|
| `slots` | `<machine>/<n>` | the process that is worker `<machine>-<n>` now | none |
| `proxies` | a hash of the proxy's host and port (`linecaster.net.proxies.proxy_id`); no credential reaches the folder | the worker that sends requests through the proxy | a block at a host (scope: the host, until the block ends); a broken proxy (scope `*`, every host) |

## Protocol

**Liveness.** A lease or a heartbeat is valid while its file was written within the lease time (`LEASE_TTL`,
180 s), by the modification time the storage lists. A worker renews every 60 s (`RENEW_SECONDS`): it rewrites its
lease files and its heartbeat. A worker that crashes stops renewing, and its leases expire on their own. The age of a
file is the reader's clock against the storage's, so the writers' clocks do not matter, and machines whose clocks are
kept by NTP agree.

**Claims.** There is no exclusive create on object storage, so a claim is decided by listing:

1. list the resource's `leases/`; if another worker's lease is valid, the claim fails (expired leases found on the
   way are deleted);
2. write the own lease, `<claimed>-<worker>.json`, the claim's time in its name;
3. list again: the earliest valid lease wins, by the time in its name, then by the worker id; a loser deletes its own
   lease.

Two workers that claim at once mostly both see both leases in step 3 and agree on the winner. When one listed before
the other's write had landed (object storage takes a moment), both may believe they won; the next renew settles it:
the holder whose lease is not the earliest valid one gives the resource up and logs at INFO `worker X lost a claim
race for proxies/<id> to Y; it takes another` (a proxy pool then claims a replacement at once). A holder's lease
keeps its claim time across renews, so it stays the earliest. A holder that went without a renew for longer than the
lease time (a stalled process) finds at its next renew that its lease file is gone (deleted as expired by another
worker) or older than the lease time; it gives the resource up and logs a WARNING, `lease on proxies/<id> expired (no
renew within the lease time)`.

**Marks.** A mark holds for a resource in a scope (a host, or `*` for every scope) for `ttl` seconds from its file's
modification time. It is written once and never changed; whoever sees it expired deletes it, past its `keep`
seconds if it has them: a mark with `keep` stays readable that long after its end, no longer holding, so its data
(a proxy's doubling, `last_wait`) reaches whoever claims the resource next (`linecaster.broker.Resource.last`). A
reader reads a mark's file once (it never changes) and keeps its end. The record is JSON: `ttl`, `until` (the end on
the writer's clock, informational), `worker`, and the kind's data (`status`, `last_wait`, `keep` for proxies).
A reader ignores the fields it does not know: a broker that does not know `keep` deletes a kept mark at its end
(the doubling then starts again), and a mark without `keep` and `last_wait` is deleted at its end and starts the
doubling at 60 s.

**Fair share.** Sharing them fairly (proxies with `per_worker: share`, the default), a worker holds `ceil(free / live
workers)` resources of a kind (at least one if any is free), where the live workers are the valid heartbeats. Proxies
count as free for a host when no mark blocks them there.

**Worker identity.** A worker is a datatrove worker slot of its machine, `<machine>-<n>`, not a process: on Ray every
task is a new process, and the harvest runs one item per task, so leases tied to processes would change hands every
few seconds. At its first use a process claims a free slot of its machine (`slots/<machine>/<n>`, a lease held by the
process itself) and is that worker from then on. Its search starts at a slot of its own, so processes started together
do not race for the same slots: the executor's worker index (`linecaster.broker.set_worker_index`: datatrove's local
rank in a local run's pool, the rank modulo the tasks at once on Ray, the task's GPU in a multi-GPU Job), else a random
place. From one listing of the machine's slots and one of the heartbeats it takes a handed-over slot first (a live
heartbeat whose slot no process holds: its leases wait for a successor), then, with worker index k, the k-th free
slot, then the free slots upward from there, past every valid lease. Free counts the slots not held since before this
launch: those without a valid slot lease claimed more than a minute ago (`SLOT_PEERS_SECONDS`; a lease keeps its claim
time across renews). The slots of a run stopped moments ago, whose leases are still valid, are left out of the count,
so a relaunch takes the slots past them at one claim per process instead of racing upward through them; the slots its
peers claimed meanwhile are not, so a pool whose processes look one after the other still takes slots 0 to n−1. Processes started together with distinct worker indexes need one claim each (`tests/test_broker.py`). A process that ends hands its slot over
(`Broker.hand_over`: the slot's lease is deleted, the worker's other leases stay), and the next process on that
machine claims that slot (handed-over slots come first), is the same worker, finds the worker's leases (named after
it) and renews them. On Ray each task hands over at its end (`linecaster.runtime.ray.RayExecutor`); a local run's worker processes outlive their
tasks and keep their slots, and a process that ends normally hands over at its exit. A slot whose process crashed expires like any lease, and so do the leases of a slot no
process takes over.

## Proxies

A worker's proxy pool (`linecaster.net.proxies.ProxyPool`, used by `linecaster.net.http.HTTPFetcher` when a proxy
list is set) works on the broker:

- **A fair share per worker** (the default; an HTTP policy's `proxies: {per_worker: share}`). The worker claims at most
  2 when it looks for proxies (`FIRST_FILL`) and grows toward its fair share of the proxies not blocked for its hosts at
  each check of its pool (every 10 s in use, `REBALANCE_SECONDS`, and after each renew; at most doubling each time),
  where it also gives back the ones beyond its share, those blocked for its hosts first. A worker that joins gets its
  part within seconds, one that leaves frees its part within the lease time, and the first workers of a launch do not
  take the proxies of those still starting. A few workers then use every proxy, which suits a run whose limit is not the
  proxies, such as one writing to object storage.
- **One proxy per worker** (`proxies: {per_worker: 1}`). The worker claims one free proxy usable for the host it
  fetches, in an order of its own (so workers claiming at once try different proxies first), and sends every request
  through it. When the proxy is blocked or broken (below), the worker marks it, releases it and claims another free
  usable one at once. No fair share and no rebalancing: the host's rate limits per proxy are the worker's own. With
  several hosts, a worker whose proxy is blocked at one of them keeps it for the others and swaps it for a free proxy
  usable at every host it uses, if there is one. Using every proxy takes as many workers as proxies, which suits
  output on local disk or a short proxy list.
- **Up to N per worker** (`proxies: {per_worker: N}`). As with one, the proxies claimed one by one: one when the worker
  holds none usable, then one more at each check of its pool, up to N and never more (more inherited from its slot's
  earlier process are given back).
- **Rate limits per proxy.** With a proxy list the host's rate limits hold per proxy (per IP). The owner spaces the
  requests through a proxy to a host by the strictest limit and sends each request through the owned proxy whose turn
  comes first. One owner per proxy makes the limit hold across all workers and runs that share the broker.
- **Blocks.** A status in the host's `block_on` (429 by default) and, with `html` there, an HTML page where another
  format was expected mark the proxy for that host ([http](http.md#blocks)): until the response's `Retry-After`, else
  for 60 s, twice the last wait on each repeat of that proxy at that host, at most the host's `block_ttl` (an hour by
  default). The mark records the status (`429`, `html`) and the doubling below. The owner
  stops using it there at once, and releases it once it is blocked for every host it uses; a worker that claims it later
  reads the mark with the claim, so no worker sends requests into another's block and starts the server's block window
  again. The request goes on through another proxy without counting as an attempt.
- **Broken proxies.** A proxy error or no connection to the proxy, `broken_after` times in a row (3 by default),
  marks it for every host (`*`, status `broken`): first for `broken_ttl` (300 s), twice as long each time it breaks
  again before it carries an answer, at most `block_ttl`. Its doubling travels with the proxy as a block's does.
- **The doubling travels with the proxy.** Each block or broken mark without `Retry-After` records its wait
  (`last_wait`; a mark with `Retry-After` the doubling's last wait unchanged) and is kept that long past its end
  (`keep`), so a worker that claims a released proxy continues the doubling where its last owner left it (60, 120,
  240 s across workers) instead of starting at 60 s. While a worker holds a proxy it is the only one using it, so it
  keeps the doubling in memory from its claim on (and writes it into each mark). **The doubling starts again** at
  60 s: after a successful response through the proxy from that host (any answer through it, for a broken proxy's), in
  that worker at once and for everyone else by deleting the proxy's ended marks there (in a thread; until then, or if
  that fails, the next owner doubles once more than it should, never less); or after a quiet period, when the next
  block comes more than its last wait after the last block there ended (`linecaster.net.http.doubling`; the kept mark
  is gone by then). An answer to a request sent before a block that still holds changes nothing. The rule is the
  direct path's too, where a worker keeps each host's doubling in memory. Why these two: a successful response is the
  only sure sign the host lets the IP in again, and the quiet period bounds how long a mark is kept, as long as the
  block before it, so a proxy that nobody tried for that long is not punished for an old episode.
- **No proxy usable.** When every proxy the worker holds is blocked for a host and none is free to claim, the
  worker's requests to that host pause until a block it knows of ends or another worker gives a proxy back (it looks
  again at once when a block ends, else every 5 s, `FILL_SECONDS`) (one warning at the
  start, one at the end; the time is in the fetch records' `pause_seconds`). Once these waits since the host's last
  successful response would pass its `max_pause` ([http](http.md#max_pause)), the run stops (`StopRequests`).

`--broker PATH` (or an HTTP policy's root key `broker`) names the folder; the default is `OUT/logs/broker`. Runs
pointed at one path share the proxies and their blocks. A run's default worker count comes from the broker too
(`linecaster.runtime.run.allocate`): from the proxies available at launch (the proxies in the file, less those with
a live block or broken mark for the run's hosts and those leased by live workers of other runs, read with
`linecaster.broker.survey_kind`), one per available proxy and at most one per CPU sharing them fairly, divided by N
with `per_worker` 1 or N, and at most 64 with OUT on object storage ([pipelines](pipelines.md#tasks-workers-and-rate-limits));
on local and Ray runs only (on HF Jobs each worker is a Job, so a proxy list never sets their number).

## The command

`linecaster broker` reads and tidies a broker's folder (`PATH`: any fsspec path, e.g. `OUT/logs/broker` or
`s3://bucket/broker`). The code is `linecaster.broker.survey_all`, `clean` and `purge`, usable from code with a
`now` to judge liveness by.

| Command | Does |
|---|---|
| `linecaster broker status PATH [--json]` | from one listing: the format; the workers (machine, run, time since the last renew), live and stale; the worker slots per machine; per kind of resource how many there are, held by a live lease, held only by expired ones (stale), free, blocked per scope with the latest end, broken (`*`), and the expired marks. Ids only, no credential (proxies are hashes). `--json`: one JSON object with the same content |
| `linecaster broker clean PATH` | removes what has expired: heartbeats and leases (slots and resources) not renewed within the lease time, marks past their end and their `keep` (a kept mark holds a proxy's doubling). Safe while a run uses the broker |
| `linecaster broker clean PATH --leases` | also every heartbeat, slot lease and resource lease, live or not; the marks (blocks) stay |
| `linecaster broker clean PATH --marks` | also every mark, live, kept or not: blocked and broken proxies are tried again at once, and their doubling starts again at 60 s |
| `linecaster broker purge PATH` | resets the broker: removes every file of its layout, `broker.json` among them, so the next run starts as on an empty folder |

`clean` and `purge` take `--dry-run` (list what would be removed, remove nothing) and `-v` (list each removed file);
`clean` prints the counts per category otherwise. **Confirmation**: `clean --leases` or `--marks` that would remove
something live (renewed within the lease time, a mark not expired), and `purge` always, list what they would remove
and ask on a terminal; without one they refuse. `--yes` skips the question. Both refuse a folder that is not a
broker's (`clean`: no `broker.json` of this format; `purge`: neither `broker.json` nor `workers/` or `slots/`), and
neither removes a file outside the broker's layout. Exit codes: 0 done (or nothing to do), 1 refused or aborted, 2 a
usage error.

**After a hard kill** (`kill -9`, a crash, a local run whose worker processes are terminated) nothing hands over:
the dead workers' heartbeats, slots and proxy leases look valid for up to the lease time (3 min). A run started again
within that time gets new slot numbers, finds every proxy held and pauses until the leases expire. Once no process of
the killed run is left, `linecaster broker clean PATH --leases` removes them, and the next run gets the slots of its
worker indexes and claims the proxies at once; the blocks found before stay, so no worker sends requests into a block again. Add `--marks` only
when the blocks themselves are wrong (a fixed proxy list, a host that lifted its block).

**Which to use**: plain `clean` any time, also as a cron job beside running workers (it only deletes what a worker
would delete when it sees it); `clean --leases` after a hard kill; `clean --leases --marks` to start the proxies
afresh while keeping the folder; `purge` to reset a broker completely (a test folder, a broker of an older format, a
folder to hand over empty). `clean --leases --marks` and `purge` remove the same live files; `purge` also removes
`broker.json` and the folders left empty.

## Guarantees and limits

- **One owner per resource**, as long as workers renew within the lease time. A worker stalled for longer than that
  (a frozen process, a storage outage) can briefly share a resource with the worker that claimed it meanwhile, until
  one of them renews and gives it up (at most a renew interval).
- **Per-proxy limits hold across workers**, since only the owner sends requests through a proxy and it enforces the
  limits locally.
- **Liveness comes from storage modification times**, compared with the reader's clock. The storage must list
  modification times (local folders and object stores do); a mark without one falls back to the end written in it.
- **Costs are listings and small writes**: a renew rewrites the worker's leases and heartbeat and lists each kind it
  holds once a minute; a worker that looks for proxies lists the kind at most every 5 s (`FILL_SECONDS`), at once after
  it gave one up. Claims of many workers at once are spread by trying the free resources in an order of each
  worker's own, and slot claims by starting at each process's worker index.
- **What the broker does not do**: no queue, no ordering of work, no exclusive create, no consistency stronger than the
  storage's own listings. Hugging Face buckets are not checked for the listing consistency the claims rely on.

## Future kinds (not implemented)

The same protocol fits other shared resources; these are examples, none of them exists:

- `direct/<machine>`: a machine's own IP as a resource with its own rate limits and blocks, for direct connections.
- `servers/<endpoint>`: a model server's capacity, leased by the workers that send it requests.
- `quotas/<host>`: a host's request budget for a day, divided among workers.
- `items/<item id>`: an item's work claimed by one worker at a time.
