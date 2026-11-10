"""The HTTP policy: how a run's requests go out, from a YAML file (``--http-policy FILE``), in three levels, each
inheriting from the one above, because one run can need several hosts with their own limits (an institution's image
server, its catalogue, its API)::

    # 1. general: every request, direct or through a proxy
    rate_limits: ["100/60", "2/1"]     # per worker direct, per proxy through proxies
    attempt_timeout: 120
    max_retries: 6
    random_user_agent: true            # or user_agent: TEXT
    block_on: [429]                    # default [429]; 4xx/5xx statuses and `html`
    stop_on: []                        # statuses and `html`; never also in block_on
    max_pause: 6h
    # 2. proxies: only for requests through the proxy list
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

The defaults follow the HTTP standards (``docs/reference/http.md``); what one site or CDN needs is opt-in per host.
A **block** is "this IP was turned away", through a proxy or direct (the server only sees an IP): a status in
``block_on`` (429 by default) and, with ``html`` there, an HTML page where an image, XML or JSON was expected. The
connection decides the reaction: through proxies the proxy is left out for that host (``Retry-After``, else a wait
that starts at 60 s and doubles on each repeat, at most ``block_ttl``) and the request goes on at once through
another, without using up an attempt; direct the worker's requests to that host pause as long (at most
``max_pause``), and the run stops once the pauses would pass ``max_pause``. What is in ``stop_on`` stops the run at
once. An HTML page where another format was expected is otherwise a failed attempt, retried. A **broken proxy** (a
proxy error, no connection to it, ``broken_after`` times in a row) is left out for every host, first for
``broken_ttl``, doubling, at most ``block_ttl``.

A host's settings are, from the lowest precedence up: linecaster's defaults, the file's level 1 (the root), the run's
own options (``--rate-limit``, ``--proxies``, ``--user-agent``, ``--random-user-agent``), the host's level 1. The
``proxies:`` section applies only on the proxy path: the root's, then the host's, field by field (``--proxies`` sits
between them for ``file``). ``direct: true`` at a host means no proxies there (neither a file nor the environment's).
A field at a host replaces the root's, it does not merge into it (``stop_on: [403]`` at a host drops the root's
``stop_on``). ``broker`` (root only) is the folder through which the workers share the proxies and their blocks
(``linecaster.broker``; default ``OUT/logs/broker``). Hosts that use one proxy list must agree on its ``per_worker``.
Each host's settings get their own fetcher (``HTTPFetcher.shared``), so each host its own rate limits, breaker,
pause and window; the proxies of one list are shared by a worker's fetchers. Fields of earlier versions fail with a
``PipelineConfigError`` that names the line to write instead (``MOVED``).
"""
from __future__ import annotations

from urllib.parse import urlsplit

from ..errors import PipelineConfigError

#: the fields of level 1, at the root and per host
GENERAL = ("rate_limits", "attempt_timeout", "max_retries", "user_agent", "random_user_agent", "block_on", "stop_on",
           "max_pause", "direct")
#: the fields of the ``proxies:`` section
PROXY_FIELDS = ("file", "per_worker", "block_ttl", "broken_after", "broken_ttl")
#: what a host's entry may hold
FIELDS = (*GENERAL, "proxies")
#: what the root may hold besides ``hosts``
ROOT_FIELDS = (*FIELDS, "broker")
#: fields of earlier versions and what replaced them (the error names the line to write)
MOVED = {"pause_on": "block_on", "blacklist_on": "block_on", "blacklist_ttl": "proxies: {block_ttl}",
         "blacklist_threshold": "proxies: {broken_after}", "proxies_per_worker": "proxies: {per_worker}"}


def seconds(value, where: str) -> float:
    """``259200``, ``"72h"``, ``"30m"``, ``"45s"``, ``"3d"`` -> seconds."""
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return float(value)
    text = str(value).strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        if text[-1:] in units and float(text[:-1]) > 0:
            return float(text[:-1]) * units[text[-1]]
    except ValueError:
        pass
    raise PipelineConfigError(f"{where}: a duration is seconds or a number with s, m, h or d (72h), not {value!r}")


def duration(value: float) -> str:
    """Seconds in words for the run's description: ``45 s``, ``5 min``, ``1 h``, ``72 h``, ``1 h 30 min``."""
    s = int(round(value))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min" + (f" {s % 60} s" if s % 60 else "")
    return f"{s // 3600} h" + (f" {s % 3600 // 60} min" if s % 3600 // 60 else "")


def _rate(text: str, where: str) -> tuple[int, float]:
    n, sep, s = str(text).partition("/")
    try:
        out = (int(n), float(s))
    except ValueError:
        out = None
    if not sep or out is None or out[0] < 1 or out[1] <= 0:
        raise PipelineConfigError(f"{where}: a rate limit is REQUESTS/SECONDS, e.g. 150/60, not {text!r}")
    return out


def _flow(value) -> str:
    """``value`` as YAML flow style, for the line an error asks for."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_flow(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_flow(v) for v in value) + "]"
    return str(value)


def _moved(entry: dict, where: str) -> None:
    """``PipelineConfigError`` for the fields of earlier versions in ``entry``, naming the line to write instead."""
    old = [k for k in MOVED if k in entry]
    if isinstance(entry.get("proxies"), str):
        old.append("proxies (a path)")
    if not old:
        return
    from .http import BLOCK_ON

    new: dict = {}
    if "pause_on" in entry or "blacklist_on" in entry:
        statuses = set(entry.get("pause_on") or ()) if "pause_on" in entry else set(BLOCK_ON)
        if "blacklist_on" in entry:
            statuses |= {429, *(entry["blacklist_on"] or ())}
        new["block_on"] = sorted(statuses, key=str)
    proxies = dict(entry["proxies"]) if isinstance(entry.get("proxies"), dict) else {}
    if isinstance(entry.get("proxies"), str):
        proxies["file"] = entry["proxies"]
    for key, name in (("proxies_per_worker", "per_worker"), ("blacklist_ttl", "block_ttl"),
                      ("blacklist_threshold", "broken_after")):
        if key in entry:
            proxies[name] = entry[key]
    if proxies:
        new["proxies"] = proxies
    lines = "; ".join(f"{k}: {_flow(v)}" for k, v in new.items())
    raise PipelineConfigError(
        f"{where}: {', '.join(old)} {'is' if len(old) == 1 else 'are'} no longer read; write `{lines}` instead "
        "(block_on: what blocks on both paths, direct and through proxies; proxies: the proxy path's settings)")


def _statuses(values, name: str, where: str, low: int) -> None:
    if not isinstance(values, list | tuple):
        raise PipelineConfigError(f"{where}: {name} is a list of HTTP statuses and `html`")
    for status in values:
        if status != "html" and not (isinstance(status, int) and not isinstance(status, bool) and low <= status < 600):
            kind = "HTTP error statuses (4xx, 5xx)" if low == 400 else "HTTP statuses"
            raise PipelineConfigError(f"{where}: {name} holds {kind} and `html`, not {status!r}")


class HTTPPolicy:
    """The HTTP policy of a file (``path``, any fsspec path) and how it turns into each host's fetcher settings
    (``http_for``, ``settings``) with the run's own options (``base``, ``HTTPFetcher``'s settings) between its root
    and its hosts' entries."""

    def __init__(self, path: str, base: dict | None = None):
        from datatrove.io import get_datafolder

        from ..catalog import yamlio

        self.path, self.base = path, dict(base or {})
        folder, _, name = path.rpartition("/")
        try:
            with get_datafolder(folder or ".").open(name, "r") as f:
                doc = yamlio.load(f.read()) or {}
        except FileNotFoundError:
            raise PipelineConfigError(f"--http-policy {path}: no such file") from None
        if not isinstance(doc, dict):
            raise PipelineConfigError(f"--http-policy {path}: settings for every host, and `hosts:` (host -> settings)")
        if "default" in doc:
            raise PipelineConfigError(f"{path}: `default:` is gone: its settings go at the root of the file")
        hosts = doc.get("hosts") or {}
        if not isinstance(hosts, dict):
            raise PipelineConfigError(f"{path}: `hosts:` maps a host to its settings")
        self.root = self._check({k: v for k, v in doc.items() if k != "hosts"}, path, ROOT_FIELDS)
        self.hosts = {str(h).lower(): self._check(p, f"{path}: hosts: {h}", FIELDS) for h, p in hosts.items()}
        self._block_or_stop(self.root, path)
        for host, entry in self.hosts.items():
            self._block_or_stop({**self.root, **entry}, f"{path}: hosts: {host}")
        self._one_setting_per_list(path)

    def _one_setting_per_list(self, where: str) -> None:
        """Hosts that use one proxy list share its pool, so they must agree on its ``per_worker``."""
        from .proxies import DEFAULT_PER_WORKER

        settings: dict[str, set] = {}
        for host in (None, *self.hosts):
            s = self.settings(host)
            if s.get("proxy_file"):
                settings.setdefault(s["proxy_file"], set()).add(s.get("per_worker", DEFAULT_PER_WORKER))
        for proxies, values in settings.items():
            if len(values) > 1:
                raise PipelineConfigError(f"{where}: the hosts that use {proxies} set its per_worker "
                                          f"{', '.join(map(str, sorted(values, key=str)))}: one list, one setting")

    @staticmethod
    def _block_or_stop(policy: dict, where: str) -> None:
        """Something blocks or stops: refuse one in both ``block_on`` (or its default) and ``stop_on``."""
        from .http import BLOCK_ON

        block = policy["block_on"] if "block_on" in policy else BLOCK_ON
        both = set(block or ()) & set(policy.get("stop_on") or ())
        if both:
            statuses = ", ".join(map(str, sorted(both, key=str)))
            default = "" if "block_on" in policy else " (block_on's default)"
            raise PipelineConfigError(
                f"{where}: {statuses} both in stop_on and block_on{default}: it blocks (a wait) or stops the run; "
                "take it out of stop_on to wait on it, or set block_on without it (block_on: []) to stop on it")

    @staticmethod
    def _check(policy, where: str, fields: tuple[str, ...]) -> dict:
        if not isinstance(policy, dict):
            raise PipelineConfigError(f"{where}: settings are a mapping of {', '.join(fields)}")
        _moved(policy, where)
        unknown = set(policy) - set(fields)
        if unknown:
            raise PipelineConfigError(f"{where}: unknown {', '.join(sorted(unknown))}; known: {', '.join(fields)}")
        for rate in policy.get("rate_limits") or ():
            _rate(rate, where)
        timeout = policy.get("attempt_timeout")
        if timeout is not None and not (isinstance(timeout, int | float) and not isinstance(timeout, bool)
                                        and timeout > 0):
            raise PipelineConfigError(f"{where}: attempt_timeout is seconds, more than 0")
        retries = policy.get("max_retries")
        if retries is not None and not (isinstance(retries, int) and not isinstance(retries, bool) and retries >= 0):
            raise PipelineConfigError(f"{where}: max_retries is a whole number, at least 0")
        if "block_on" in policy:
            _statuses(policy["block_on"] or [], "block_on", where, 400)
        if "stop_on" in policy:
            _statuses(policy["stop_on"] or [], "stop_on", where, 100)
        if "max_pause" in policy:
            seconds(policy["max_pause"], where)
        if "direct" in policy and not isinstance(policy["direct"], bool):
            raise PipelineConfigError(f"{where}: direct is true or false")
        if "proxies" in policy:
            HTTPPolicy._check_proxies(policy["proxies"], f"{where}: proxies")
        if "broker" in policy and not isinstance(policy["broker"], str):
            raise PipelineConfigError(f"{where}: broker is a folder (any fsspec path)")
        return dict(policy)

    @staticmethod
    def _check_proxies(section, where: str) -> None:
        if not isinstance(section, dict):
            raise PipelineConfigError(f"{where}: a mapping of {', '.join(PROXY_FIELDS)}")
        unknown = set(section) - set(PROXY_FIELDS)
        if unknown:
            raise PipelineConfigError(f"{where}: unknown {', '.join(sorted(unknown))}; known: {', '.join(PROXY_FIELDS)}")
        if "file" in section and not isinstance(section["file"], str):
            raise PipelineConfigError(f"{where}: file is the proxy list's path (any fsspec path)")
        if "per_worker" in section:
            from .proxies import per_worker_setting

            per_worker_setting(section["per_worker"], where)
        for key in ("block_ttl", "broken_ttl"):
            if key in section:
                seconds(section[key], f"{where}: {key}")
        after = section.get("broken_after")
        if after is not None and not (isinstance(after, int) and not isinstance(after, bool) and after >= 1):
            raise PipelineConfigError(f"{where}: broken_after is a whole number of errors in a row, at least 1")

    def policy(self, url: str) -> dict:
        """The file's fields for ``url``'s host: the root's, with the host's entry over them."""
        host = (urlsplit(url).hostname or "").lower()
        return {**self.root, **self.hosts.get(host, {})}

    def http_for(self, url: str) -> dict:
        """The fetcher settings (``HTTPFetcher``'s) for ``url``: the file's root, the run's options over it, the
        host's entry over both."""
        return self.settings((urlsplit(url).hostname or "").lower())

    def settings(self, host: str | None) -> dict:
        """The fetcher settings (``HTTPFetcher``'s) for ``host`` (None: a host without an entry): the file's root, the
        run's options over it, the host's entry over both."""
        out: dict = {}
        self._lay(out, self.root)
        out.update(self.base)
        self._lay(out, self.hosts.get(host, {}) if host is not None else {})
        return out

    def _lay(self, out: dict, policy: dict) -> None:
        if "rate_limits" in policy:
            out["rate_limits"] = [_rate(r, self.path) for r in policy["rate_limits"] or ()] or None
            if out["rate_limits"] is None:
                out.pop("rate_limits")
        for key in ("user_agent", "attempt_timeout", "max_retries", "broker"):
            if key in policy:
                out[key] = policy[key]
        if "random_user_agent" in policy:
            out["use_fake_user_agent"] = bool(policy["random_user_agent"])
        if "block_on" in policy:
            out["block_on"] = sorted(policy["block_on"] or (), key=str)
        if "stop_on" in policy:
            out["stop_on"] = list(policy["stop_on"] or ())
        if "max_pause" in policy:
            out["max_pause"] = seconds(policy["max_pause"], self.path)
        proxies = policy.get("proxies") or {}
        if proxies.get("file"):
            out["proxy_file"] = proxies["file"]
        if "per_worker" in proxies:
            out["per_worker"] = proxies["per_worker"]
        for key in ("block_ttl", "broken_ttl"):
            if key in proxies:
                out[key] = seconds(proxies[key], self.path)
        if "broken_after" in proxies:
            out["broken_after"] = int(proxies["broken_after"])
        if policy.get("direct"):                            # last: direct wins over a file at the same level
            out.pop("proxy_file", None)
            out["trust_env"], out["proxy"] = False, None
        elif "direct" in policy:                            # direct: false undoes a direct root
            out.pop("trust_env", None)
            out.pop("proxy", None)

    def rate_limited(self) -> bool:
        """Whether the file sets rate limits anywhere (the run then keeps one worker)."""
        return any(p.get("rate_limits") for p in (self.root, *self.hosts.values()))

    def describe(self) -> str:
        """One line per host for the start of a run, with the rules that hold there on its path (``settings``: the
        root's, the run's options over them, the host's entry over both), defaults and opt-ins alike."""
        lines = [f"{h}: {rules(self.settings(h))}" for h in self.hosts]
        lines.append(f"{'other hosts' if self.hosts else 'every host'}: {rules(self.settings(None))}")
        return "; ".join(lines)


def rules(s: dict) -> str:
    """What holds for a fetcher's settings ``s`` (``HTTPFetcher``'s), in words: its path, rate limits, retries, what
    blocks and how it is answered there, what stops the run."""
    from .http import BLOCK_FIRST_WAIT, BLOCK_ON, BLOCK_TTL, BROKEN_AFTER, BROKEN_TTL, HTTP_DEFAULTS, MAX_PAUSE
    from .proxies import DEFAULT_PER_WORKER, describe_per_worker

    proxied = bool(s.get("proxy_file"))
    stop = list(s.get("stop_on") or ())
    block = [b for b in (s["block_on"] if "block_on" in s else BLOCK_ON) if b not in stop]
    limits = ", ".join(f"{n}/{sec:g}" for n, sec in s.get("rate_limits") or ())
    ttl, pause = s.get("block_ttl", BLOCK_TTL), s.get("max_pause", MAX_PAUSE)
    parts = ["through proxies, " + describe_per_worker(s.get("per_worker", DEFAULT_PER_WORKER)) if proxied else "direct",
             f"{limits} per {'proxy' if proxied else 'worker'}" if limits else "no rate limit",
             f"{s.get('max_retries', HTTP_DEFAULTS['max_retries'])} retries"]
    if s.get("use_fake_user_agent"):
        parts.append("a random User-Agent")
    elif s.get("user_agent"):
        parts.append(f"User-Agent {s['user_agent']}")
    first = duration(BLOCK_FIRST_WAIT)
    blocks = ", ".join(map(str, block))
    if not block:
        parts.append("no block")
    elif proxied:
        parts.append(f"blocks on {blocks}: the proxy left out for the host for Retry-After, else {first} doubling up "
                     f"to {duration(ttl)}")
    else:
        parts.append(f"blocks on {blocks}: the worker waits Retry-After, else {first} doubling, and stops when the "
                     f"wait would pass {duration(pause)}")
    if proxied:
        parts.append(f"a proxy broken after {s.get('broken_after', BROKEN_AFTER)} errors in a row, left out "
                     f"{duration(s.get('broken_ttl', BROKEN_TTL))} doubling up to {duration(ttl)}; no usable proxy: "
                     f"waits, at most {duration(pause)}")
    if "html" not in block and "html" not in stop:
        parts.append("unexpected HTML retried")
    if stop:
        parts.append("stops on " + ", ".join(map(str, stop)))
    return ", ".join(parts)
