# HTTP

How linecaster's readers fetch over http(s) (`linecaster.net.http`, `linecaster.net.proxies`,
`linecaster.net.policy`): the defaults, what a block is and how each path answers it, unexpected HTML, retries, and
the HTTP policy file that changes all of it per host. Terms are the [glossary](glossary.md)'s; how workers share the
proxies is in the [broker](broker.md), how runs choose their workers in
[pipelines](pipelines.md#tasks-workers-and-rate-limits).

**The principle:** the defaults follow the HTTP standards (a 429 with its `Retry-After`, the retryable statuses,
`Retry-After` as seconds or an HTTP-date); anything learned from one site or CDN (a block page served with 200, a 403
that means "this IP", a block that lasts three days) is opted into per host in an HTTP policy.

## The defaults

| Setting | Default | What it does |
|---|---|---|
| `user_agent` | `HF-Research/1.0` (datatrove's, `USER_AGENT`) | the User-Agent of every request; `random_user_agent` (`--random-user-agent`) a random browser one per task instead |
| `timeout` | 300 s | each phase of a request (connect, read, write, pool) |
| `max_keepalive_connections` | 16 | idle connections kept open for reuse |
| `max_retries` | 4 | retries after the first attempt (5 attempts; 0: one) |
| `retry_wait_min`, `retry_wait_max` | 2 s, 60 s | the wait after the n-th failed attempt: `retry_wait_min * 2**(n-1)`, at most `retry_wait_max` (2, 4, 8, 16 s) |
| `retry_after_max` | 300 s | the longest `Retry-After` a retry honors on the direct path |
| `attempt_timeout`, `attempt_min_rate` | 15 s, 50,000 bytes/s | the deadline per attempt: 15 s plus 1 s per 50 kB the response declares |
| retryable statuses | 408, 425, 429, 500, 502, 503, 504, 520-524 (`RETRYABLE_STATUS_CODES`) | tried again; every other 4xx and 5xx fails at once |
| `rate_limits` | none | `N/S` windows, at most N requests in any S seconds, all at once: per worker direct, per proxy through proxies |
| `block_on` | `[429]` (`BLOCK_ON`) | what is a block (statuses and `html`) |
| `stop_on` | `[]` | what stops the run at once (statuses and `html`) |
| `max_pause` | 6 h (`MAX_PAUSE`) | the most a worker's requests to a host wait in all since the host's last successful response: in pauses direct, for a usable proxy through proxies ([below](#max_pause)) |
| first wait of a block | 60 s (`BLOCK_FIRST_WAIT`) | a block without `Retry-After`: 60 s, then twice the last wait on each repeat |
| shortest block | 1 s (`PAUSE_MIN_WAIT`) | whatever `Retry-After` says (0, a date gone by) |
| `proxies: block_ttl` | 3600 s (`BLOCK_TTL`) | the longest a blocked proxy is left out without `Retry-After`: the ceiling of the doubling, and of a broken proxy's |
| `proxies: broken_after` | 3 (`BROKEN_AFTER`) | proxy errors in a row before a proxy is broken |
| `proxies: broken_ttl` | 300 s (`BROKEN_TTL`) | a broken proxy's first time out, doubling, at most `block_ttl` |
| `proxies: per_worker` | `share` | how many proxies of the list a worker holds ([broker](broker.md#proxies)) |

## Blocks

A **block** means "this IP was turned away", through a proxy or direct: the server only sees an IP. What counts as a
block is declared once for both paths (`block_on`: statuses, and `html` for an HTML page where another format was
expected). The connection decides the reaction:

| | direct (one IP) | through proxies |
|---|---|---|
| a response in `block_on` | the worker's requests to that host wait (a [pause](glossary.md)) for `Retry-After`, or else 60 s, doubling on each repeat; requests to other hosts go on; the run stops when the wait would be too long (past `max_pause` since the host's last successful response) | the proxy is marked for that host (`Retry-After`, or else 60 s doubling up to `block_ttl`) and the request goes on at once through another proxy, without using up an attempt |
| a response in `stop_on` | the run stops at once | the run stops at once |
| no usable proxy | (none) | the requests to that host wait for a block to end or a proxy to free up; the run stops when the waits would pass `max_pause` since the host's last successful response |
| connection errors | the host's errors: retries and the breaker | the proxy's errors: they count toward `broken_after`, then the proxy is left out for every host |

How long a block lasts is one function for both paths (`linecaster.net.http.block_wait`): with `Retry-After`
(seconds or an HTTP-date) exactly that, at least 1 s; without it 60 s, then twice the last wait for each block that
repeats (for that host, and through proxies for that proxy at that host), at most `block_ttl` through proxies and
`max_pause` direct. Direct, the worker keeps each host's doubling in memory (it owns its IP); through proxies the
doubling travels with the proxy in the broker's marks, so a worker that claims a released proxy continues it
([broker](broker.md#proxies)). **The doubling starts again** at 60 s after a successful response from the host
(through proxies: through that proxy), or after a quiet period: when the next block comes more than the last wait
after the last block there ended (`linecaster.net.http.doubling`). A response to a request sent before a block that
still holds changes nothing. A block is never an attempt: the request that got it is tried again after the pause (direct) or at once through
another proxy, with all its retries left.

A **broken proxy** fails attempts itself (a proxy error, no connection to the proxy, `PROXY_ERRORS`) `broken_after`
times in a row: it is left out for every host, first for `broken_ttl`, twice as long each time it breaks again before
it carries an answer, at most `block_ttl`. A timeout reading the server's answer is a slow server, not a broken proxy:
it is retried and leaves the proxy in. Blocks and broken proxies are marks in the [broker](broker.md), so every
worker that shares it leaves the proxy out, and continues their doubling when it claims the proxy.

### max_pause

`max_pause` is one count on both paths, per worker and host (`linecaster.net.http.PauseTotal`): the
time the worker's requests to the host have spent waiting since the host's last successful response, direct in
pauses (the length each block adds), through proxies waiting for a usable proxy (the time no proxy was usable there).
Once the next wait would take it past `max_pause` (a block whose wait is known, the first proxy block that ends), or
it has passed it (waiting for proxies other workers hold), the run stops with `StopRequests`, whose message says how
long the host's requests waited. A successful response from the host starts it again, through any proxy. Each host
counts for itself: a pause at one host neither holds nor counts against the requests to another. The
[breaker](#retries-and-deadlines)'s waits (a server that fails) do not count: each request waits one out a few
times, then fails.

## Unexpected HTML

A successful response (2xx) with an HTML page where an image, XML, JSON or a manifest was expected is **unexpected
HTML**: an error page served with 200, a soft 404, a login page after a redirect, a CDN's challenge. The readers say
what they expect (`HTTPFetcher.submit`'s `expect`: images, manifests, ALTO files, resources whose kind or URL names a
format); a response told apart by its `Content-Type` (`text/html`) or its first bytes (`<!doctype html`, `<html`).
An error status with an HTML body is that status: a 503 maintenance page is a 503, retried as one.

By default unexpected HTML is a failed attempt, on both paths: it counts, is retried after the backoff, and is traced
`200-html`. After the last attempt the fetch fails with `UnexpectedHTML`, whose message names the expected format and
the content type (`an HTML page (text/html; charset=utf-8, 1234 bytes) where an image was expected: URL`); through
proxies as the cause of `MaxRetriesExceeded` (`after 5 attempts: an HTML page ...`). With `html` in `block_on` it is
a block instead (above), with `html` in `stop_on` it stops the run.

## Retries and deadlines

A request is tried up to `max_retries + 1` times (`HTTPFetcher._attempts`, one loop for both paths). A transport
error (a timeout, a broken connection, a proxy error, an attempt past its deadline), a retryable status and
unexpected HTML are tried again after `retry_wait_min * 2**(n-1)` seconds (at most `retry_wait_max`); on the direct
path at least as long as the response's `Retry-After` asks (at most `retry_after_max`); through proxies the next
attempt goes out through another proxy, without it. Any other status fails at once (`httpx.HTTPStatusError`); a 404
first tries the page's fallback URL, if it has one, with attempts of its own. Retries used up raise the last error
(direct) or `MaxRetriesExceeded` naming it (through proxies). Each attempt must be done within its deadline:
`attempt_timeout` plus 1 s per `attempt_min_rate` bytes the response declares, counted from when it goes out, after
the rate limits; one that takes longer is cut and retried.

Each fetcher also has a **breaker** (`linecaster.net.http.Breaker`): when most recent attempts got a server error,
its requests pause, a probe goes out now and then, and the first answer that is not a server error ends the pause.

## Trace entries

Every fetch records its attempts (the fetch record's `tries`, the `http.tries` of a page's `linecaster.http.fetch`
span, [tracing](tracing.md)): `200` (or another status) for a response read whole, `200-cut` for one cut by the
deadline per attempt, `200-html` for unexpected HTML, `no-response` for none (a timeout, a connection or proxy
error). A block is traced with its status (`429`) but does not count among the attempts a failed fetch names. The
record also has the time spent waiting for the rate limits (`wait_seconds`) and in pauses (`pause_seconds`).

## The HTTP policy

`--http-policy FILE` (`--items`, `--parquet`; `linecaster.net.policy.HTTPPolicy`) gives a run's requests their
settings from one YAML file, in three levels, each inheriting from the one above:

```yaml
# 1. general: every request, direct or through a proxy
rate_limits: ["100/60", "2/1"]     # per worker direct, per proxy through proxies
attempt_timeout: 120
max_retries: 6
random_user_agent: true            # or user_agent: TEXT
block_on: [429]                    # default [429]; 4xx/5xx statuses and `html`
stop_on: []                        # statuses and `html`; never also in block_on
max_pause: 6h
# 2. proxies: only for requests through the proxy list; inherits level 1
proxies:
  file: proxies.txt
  per_worker: share                # share | 1 | N
  block_ttl: 3600                  # a blocked proxy without Retry-After: the ceiling of the doubling
  broken_after: 3                  # proxy errors in a row before it is left out
  broken_ttl: 300                  # a broken proxy's first time out, doubling, at most block_ttl
# 3. hosts: per host, the same two levels; each field overrides the one above
hosts:
  catalog.example.org:
    direct: true
    rate_limits: ["25/60"]
    stop_on: [html]
  images.example.org:
    proxies: {block_ttl: 72h}
broker: s3://bucket/broker         # root only
```

Durations are seconds or a number with `s`, `m`, `h` or `d` (`72h`). A host's settings are, from the lowest
precedence up:

1. linecaster's defaults (above);
2. the file's level 1, at its root;
3. the run's own options: `--rate-limit`, `--proxies` (the proxy list's `file`), `--user-agent`,
   `--random-user-agent`;
4. the host's level 1, under `hosts:`.

The `proxies:` section applies only on the proxy path: the root's, then the host's, field by field (a host's
`proxies: {block_ttl: 72h}` keeps the root's `file`). A field at a host replaces the root's, it does not merge into
it (`stop_on: [403]` at a host drops the root's `stop_on`). `direct: true` at a host means no proxies there, neither
a list nor the environment's (`HTTPS_PROXY`); `direct: false` undoes a direct root. `broker` is the folder through
which the workers share the proxies and their blocks, at the root only (default `OUT/logs/broker`). The checks at
startup: something in both `block_on` (or its default) and `stop_on` is refused (to stop on a 429, write `block_on:
[]` with `stop_on: [429]`); hosts that use one proxy list must agree on its `per_worker`; an unknown field is an
error. Each host's settings get their own fetcher, so each host its own rate limits, breaker, pause and window.

A run states the rules that hold per host and path before it starts (`HTTPPolicy.describe`, in the run's notes),
defaults and opt-ins alike, e.g. `catalog.example.org: direct, 25/60 per worker, 4 retries, blocks on 429: the worker
waits Retry-After, else 1 min doubling, and stops when the wait would pass 6 h, stops on html`.

### Fields of earlier versions

Fields of earlier versions are refused at startup with a `PipelineConfigError` that names the line to write instead:

| Field | Write instead |
|---|---|
| `pause_on: [429, 503]` | `block_on: [429, 503]` |
| `blacklist_on: [403]` | `block_on: [429, 403]` (with the statuses of `pause_on`, if any) |
| `blacklist_ttl: 72h` | `proxies: {block_ttl: 72h}` |
| `blacklist_threshold: 2` | `proxies: {broken_after: 2}` |
| `proxies: proxies.txt` | `proxies: {file: proxies.txt}` |
| `proxies_per_worker: 1` | `proxies: {per_worker: 1}` |

### A CDN-protected host

A host behind a CDN that answers a turned-away IP with a challenge page (HTML with 200) and keeps an IP blocked for
an hour, where one proxy error already means the proxy is unusable, gets the strict reaction back per host:

```yaml
proxies: {file: proxies.txt}
hosts:
  images.example.org:
    block_on: [429, html]          # a challenge page is a block: the proxy is left out, the request goes on
    proxies:
      block_ttl: 3600              # left out up to an hour without Retry-After
      broken_after: 1              # one proxy error in a row: broken
```

Direct, the same `block_on: [429, html]` makes the worker wait on a challenge page as on a 429, or stop when the
wait would be too long.
