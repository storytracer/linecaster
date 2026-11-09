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

Two workers that claim at once both see both leases in step 3 and agree on the winner. A holder's lease keeps its
claim time across renews, so it stays the earliest. A holder that went without a renew for longer than the lease time
(a stalled process) may find at its next renew that its file was deleted, or that another worker's lease is now the
earliest; it gives the resource up then.

**Marks.** A mark holds for a resource in a scope (a host, or `*` for every scope) for `ttl` seconds from its file's
modification time. It is written once and never changed; whoever sees it expired deletes it. A reader reads a mark's
file once (it never changes) and keeps its end.

**Fair share.** A worker holds `ceil(free / live workers)` resources of a kind (at least one if any is free), where
the live workers are the valid heartbeats. Proxies count as free for a host when no mark blocks them there.

**Worker identity.** A worker is a datatrove worker slot of its machine, `<machine>-<n>`, not a process: on Ray every
task is a new process, and the harvest runs one item per task, so leases tied to processes would change hands every
few seconds. At its first use a process claims the lowest free slot of its machine (`slots/<machine>/<n>`, a lease
held by the process itself) and is that worker from then on. A process that ends hands its slot over
(`Broker.hand_over`: the slot's lease is deleted, the worker's other leases stay), and the next process on that
machine claims the same slot, is the same worker, finds the worker's leases (named after it) and renews them. On Ray
each task hands over at its end (`linecaster.runtime.ray.RayExecutor`); a local run's worker processes outlive their
tasks and keep their slots. A slot whose process crashed expires like any lease, and so do the leases of a slot no
process takes over.

## Proxies

A worker's proxy pool (`linecaster.net.proxies.ProxyPool`, used by `linecaster.net.http.HTTPFetcher` when a proxy
list is set) works on the broker:

- **Share.** It claims its fair share of the proxies not blocked for the host it fetches, and every 10 s
  (`REBALANCE_SECONDS`) and at each renew gives back the ones beyond its share, those blocked for its hosts first,
  so a worker that joins gets its part within seconds and one that leaves frees its part within the lease time.
- **Rate limits per proxy.** With a proxy list the host's rate limits hold per proxy (per IP). The owner spaces the
  requests through a proxy to a host by the strictest limit and sends each request through the owned proxy whose turn
  comes first. One owner per proxy makes the limit hold across all workers and runs that share the broker.
- **Blocks.** A 429 (until its `Retry-After`, else for the host's `blacklist_ttl`), a status in the host's
  `blacklist_on` and an HTML page where another format was expected mark the proxy for that host. The owner stops
  using it there at once, and releases it once it is blocked for every host it uses; a worker that claims it later
  reads the mark with the claim, so no worker sends requests into another's block and starts the server's block
  window again. The request goes on through another proxy without counting as an attempt.
- **Broken proxies.** A proxy error or no connection to the proxy, `blacklist_threshold` times in a row, marks it for
  every host (`*`) for `blacklist_ttl`.
- **No proxy usable.** When every proxy the worker holds is blocked for a host and none is free to claim, the
  worker's requests to that host pause until a block ends or another worker gives a proxy back (one warning at the
  start, one at the end; the time is in the fetch records' `pause_seconds`). A pause that would pass the host's
  `max_pause` stops the run (`StopRequests`).

`--broker PATH` (or an HTTP policy's root key `broker`) names the folder; the default is `OUT/logs/broker`. Runs
pointed at one path share the proxies and their blocks.

## Guarantees and limits

- **One owner per resource**, as long as workers renew within the lease time. A worker stalled for longer than that
  (a frozen process, a storage outage) can briefly share a resource with the worker that claimed it meanwhile, until
  one of them renews and gives it up (at most a renew interval).
- **Per-proxy limits hold across workers**, since only the owner sends requests through a proxy and it enforces the
  limits locally.
- **Liveness comes from storage modification times**, compared with the reader's clock. The storage must list
  modification times (local folders and object stores do); a mark without one falls back to the end written in it.
- **Costs are listings and small writes**: a renew rewrites the worker's leases and heartbeat and lists each kind it
  holds once a minute; a worker that looks for proxies lists the kind at most every 5 s (`FILL_SECONDS`). Claims of
  many workers at once are spread by trying the free resources in an order of each worker's own.
- **What the broker does not do**: no queue, no ordering of work, no exclusive create, no consistency stronger than the
  storage's own listings. Hugging Face buckets are not checked for the listing consistency the claims rely on.

## Future kinds (not implemented)

The same protocol fits other shared resources; these are examples, none of them exists:

- `direct/<machine>`: a machine's own IP as a resource with its own rate limits and blocks, for direct connections.
- `servers/<endpoint>`: a model server's capacity, leased by the workers that send it requests.
- `quotas/<host>`: a host's request budget for a day, divided among workers.
- `items/<item id>`: an item's work claimed by one worker at a time.
