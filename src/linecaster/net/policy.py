"""The HTTP policy: how a run's requests go out, from a YAML file (``--http-policy FILE``): settings for every host at
the root, and overrides for single hosts under ``hosts:``, because one run can need several hosts with their own limits
(an institution's image server, its catalogue, its API)::

    rate_limits: ["60/60"]
    max_retries: 5
    proxies: proxies.txt
    proxy_blocks: s3://bucket/proxy-blocks
    hosts:
      tile.loc.gov: {rate_limits: ["150/60", "3/1"]}
      lccn.loc.gov: {rate_limits: ["25/60"], direct: true, stop_on: [429, html]}

A host's settings are, from the lowest precedence up: linecaster's defaults, the file's root, the run's own options
(``--rate-limit``, ``--proxies``, ``--user-agent``, ...), the host's entry under ``hosts:``. The fields, at the root and
per host: ``rate_limits`` (``REQUESTS/SECONDS`` strings, per worker), ``proxies`` (a proxy file, ``read_proxies``),
``direct`` (no proxy, neither a file nor the environment's), ``user_agent``, ``random_user_agent``,
``attempt_timeout``, ``max_retries``, ``blacklist_ttl`` and ``blacklist_threshold`` (how long a proxy is left out, and
after how many failures in a row, e.g. ``72h`` for a host whose block lasts three days; default
``linecaster.net.http``'s 3600 s after 1), ``blacklist_on`` (statuses that leave the proxy they came through out,
besides 429, and are retried through the next one: e.g. ``[403]`` for a host that turns away single proxy IPs), and
``stop_on``: statuses (and ``html``, an HTML page where another format was expected: a CAPTCHA) that stop the run at
once, without a retry, for a host whose block outlasts its retries (lccn.loc.gov blocks for 72 hours and starts the
block again with every request during it). At the root only: ``proxy_blocks``, the folder where proxy blocks are
marked (``linecaster.net.proxy_blocks``). A host's entry replaces a field of the root, it does not merge into it
(``stop_on: [403]`` under a host drops the root's ``stop_on``). Each host's settings get their own fetcher
(``HTTPFetcher.shared``), so each host its own rate limits, breaker and window.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from ..errors import PipelineConfigError

FIELDS = ("rate_limits", "proxies", "direct", "user_agent", "random_user_agent", "attempt_timeout", "max_retries",
          "stop_on", "blacklist_ttl", "blacklist_threshold", "blacklist_on")
#: what the root may hold besides ``FIELDS`` and ``hosts``
ROOT_FIELDS = (*FIELDS, "proxy_blocks")


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


def _rate(text: str, where: str) -> tuple[int, float]:
    n, sep, s = str(text).partition("/")
    try:
        out = (int(n), float(s))
    except ValueError:
        out = None
    if not sep or out is None or out[0] < 1 or out[1] <= 0:
        raise PipelineConfigError(f"{where}: a rate limit is REQUESTS/SECONDS, e.g. 150/60, not {text!r}")
    return out


class HTTPPolicy:
    """The HTTP policy of a file (``path``, any fsspec path) and how it turns into each host's fetcher settings
    (``http_for``) with the run's own options (``base``) between its root and its hosts' entries."""

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

    @staticmethod
    def _check(policy, where: str, fields: tuple[str, ...]) -> dict:
        if not isinstance(policy, dict):
            raise PipelineConfigError(f"{where}: settings are a mapping of {', '.join(fields)}")
        unknown = set(policy) - set(fields)
        if unknown:
            raise PipelineConfigError(f"{where}: unknown {', '.join(sorted(unknown))}; known: {', '.join(fields)}")
        for rate in policy.get("rate_limits") or ():
            _rate(rate, where)
        if "blacklist_ttl" in policy:
            seconds(policy["blacklist_ttl"], where)
        threshold = policy.get("blacklist_threshold")
        if threshold is not None and not (isinstance(threshold, int) and threshold >= 1):
            raise PipelineConfigError(f"{where}: blacklist_threshold is a whole number of failures, at least 1")
        retries = policy.get("max_retries")
        if retries is not None and not (isinstance(retries, int) and not isinstance(retries, bool) and retries >= 0):
            raise PipelineConfigError(f"{where}: max_retries is a whole number, at least 0")
        for status in policy.get("stop_on") or ():
            if status != "html" and not (isinstance(status, int) and 100 <= status < 600):
                raise PipelineConfigError(f"{where}: stop_on holds HTTP statuses and `html`, not {status!r}")
        for status in policy.get("blacklist_on") or ():
            if not (isinstance(status, int) and not isinstance(status, bool) and 400 <= status < 600):
                raise PipelineConfigError(f"{where}: blacklist_on holds HTTP error statuses (4xx, 5xx), not {status!r}")
        both = set(policy.get("blacklist_on") or ()) & set(policy.get("stop_on") or ())
        if both:
            raise PipelineConfigError(f"{where}: {', '.join(map(str, sorted(both)))} both in stop_on and blacklist_on")
        if "proxy_blocks" in policy and not isinstance(policy["proxy_blocks"], str):
            raise PipelineConfigError(f"{where}: proxy_blocks is a folder (any fsspec path)")
        return dict(policy)

    def policy(self, url: str) -> dict:
        """The file's settings for ``url``'s host: the root's, with the host's entry over them."""
        host = (urlsplit(url).hostname or "").lower()
        return {**self.root, **self.hosts.get(host, {})}

    def http_for(self, url: str) -> dict:
        """The fetcher settings (``HTTPFetcher``'s) for ``url``: the file's root, the run's options over it, the
        host's entry over both."""
        out: dict = {}
        self._lay(out, self.root)
        out.update(self.base)
        self._lay(out, self.hosts.get((urlsplit(url).hostname or "").lower(), {}))
        return out

    def _lay(self, out: dict, policy: dict) -> None:
        if "rate_limits" in policy:
            out["rate_limits"] = [_rate(r, self.path) for r in policy["rate_limits"] or ()] or None
            if out["rate_limits"] is None:
                out.pop("rate_limits")
        if policy.get("direct"):
            out.pop("proxy_file", None)
            out["trust_env"], out["proxy"] = False, None
        elif "direct" in policy:                            # direct: false undoes a direct root
            out.pop("trust_env", None)
            out.pop("proxy", None)
        if policy.get("proxies"):
            out["proxy_file"] = policy["proxies"]
        for key in ("user_agent", "attempt_timeout", "max_retries", "proxy_blocks"):
            if key in policy:
                out[key] = policy[key]
        if "random_user_agent" in policy:
            out["use_fake_user_agent"] = bool(policy["random_user_agent"])
        if "blacklist_ttl" in policy:
            out["proxy_blacklist_ttl"] = seconds(policy["blacklist_ttl"], self.path)
        if "blacklist_threshold" in policy:
            out["proxy_blacklist_threshold"] = int(policy["blacklist_threshold"])
        if "blacklist_on" in policy:
            out["proxy_blacklist_on"] = sorted(policy["blacklist_on"] or ())
        if "stop_on" in policy:
            out["stop_on"] = [s for s in policy["stop_on"] or () if isinstance(s, int)]

    def stops_on_html(self, url: str) -> bool:
        return "html" in (self.policy(url).get("stop_on") or ())

    def rate_limited(self) -> bool:
        """Whether the file sets rate limits anywhere (the run then keeps one worker)."""
        return any(p.get("rate_limits") for p in (self.root, *self.hosts.values()))

    def describe(self) -> str:
        """One line per host (with the root's settings it keeps) for the start of a run."""
        def one(name: str, p: dict) -> str:
            parts = [", ".join(p.get("rate_limits") or []) or "no rate limit"]
            parts.append("direct" if p.get("direct") else "through proxies" if p.get("proxies") else "")
            if p.get("max_retries") is not None:
                parts.append(f"{p['max_retries']} retries")
            if p.get("proxies") and p.get("blacklist_ttl"):
                parts.append(f"a blocked proxy left out {p['blacklist_ttl']}")
            if p.get("proxies") and p.get("blacklist_on"):
                parts.append(f"a proxy left out on {', '.join(map(str, sorted(p['blacklist_on'])))}")
            if p.get("stop_on"):
                parts.append("stops on " + ", ".join(map(str, p["stop_on"])))
            return f"{name}: " + ", ".join(x for x in parts if x)
        lines = [one(h, {**self.root, **p}) for h, p in self.hosts.items()]
        if self.root:
            lines.append(one("other hosts" if self.hosts else "every host", self.root))
        return "; ".join(lines)
