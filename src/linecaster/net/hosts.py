"""Host policies: how requests to each host go out, from a YAML file (``--hosts FILE``), because one run can need
several hosts with their own limits (an institution's image server, its catalogue, its API)::

    hosts:
      tile.loc.gov: {rate_limits: ["150/60", "3/1"], proxies: proxies.txt}
      lccn.loc.gov: {rate_limits: ["25/60"], direct: true, stop_on: [429, html]}
      www.loc.gov:  {rate_limits: ["18/60"], direct: true}
    default: {rate_limits: ["60/60"]}

A host's policy (else ``default``, else none) is laid over the run's own HTTP settings (``--rate-limit``,
``--proxies``, ``--user-agent``, ...). Its fields: ``rate_limits`` (``REQUESTS/SECONDS`` strings, per worker),
``proxies`` (a proxy file, ``read_proxies``), ``direct`` (no proxy, neither a file nor the environment's),
``user_agent``, ``random_user_agent``, ``attempt_timeout``, ``max_retries``, ``blacklist_ttl`` and
``blacklist_threshold`` (how long a proxy is left out, and after how many failures in a row, e.g. ``72h`` for a host
whose block lasts three days; default ``linecaster.net.http``'s 3600 s after 1), and ``stop_on``: statuses (and
``html``, an HTML page where another format was expected: a CAPTCHA) that stop the run at once, without a retry, for
a host whose block outlasts its retries (lccn.loc.gov blocks for 72 hours and starts the block again with every
request during it). Each policy gets its own fetcher (``HTTPFetcher.shared``), so each host its own rate limits,
breaker and window.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from ..errors import PipelineConfigError

FIELDS = ("rate_limits", "proxies", "direct", "user_agent", "random_user_agent", "attempt_timeout", "max_retries",
          "stop_on", "blacklist_ttl", "blacklist_threshold")


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


class HostPolicies:
    """The policies of a hosts file (``path``, any fsspec path) and how they turn into fetcher settings
    (``http_for``) over the run's ``base`` settings."""

    def __init__(self, path: str, base: dict | None = None):
        from datatrove.io import get_datafolder

        from ..catalog import yamlio

        self.path, self.base = path, dict(base or {})
        folder, _, name = path.rpartition("/")
        try:
            with get_datafolder(folder or ".").open(name, "r") as f:
                doc = yamlio.load(f.read()) or {}
        except FileNotFoundError:
            raise PipelineConfigError(f"--hosts {path}: no such file") from None
        if not isinstance(doc, dict) or set(doc) - {"hosts", "default"}:
            raise PipelineConfigError(f"--hosts {path}: the file holds `hosts:` (host -> policy) and `default:`")
        self.hosts = {str(h).lower(): self._check(p, f"{path}: {h}") for h, p in (doc.get("hosts") or {}).items()}
        self.default = self._check(doc.get("default") or {}, f"{path}: default")

    @staticmethod
    def _check(policy, where: str) -> dict:
        if not isinstance(policy, dict):
            raise PipelineConfigError(f"{where}: a policy is a mapping of {', '.join(FIELDS)}")
        unknown = set(policy) - set(FIELDS)
        if unknown:
            raise PipelineConfigError(f"{where}: unknown {', '.join(sorted(unknown))}; known: {', '.join(FIELDS)}")
        for rate in policy.get("rate_limits") or ():
            _rate(rate, where)
        if "blacklist_ttl" in policy:
            seconds(policy["blacklist_ttl"], where)
        threshold = policy.get("blacklist_threshold")
        if threshold is not None and not (isinstance(threshold, int) and threshold >= 1):
            raise PipelineConfigError(f"{where}: blacklist_threshold is a whole number of failures, at least 1")
        for status in policy.get("stop_on") or ():
            if status != "html" and not (isinstance(status, int) and 100 <= status < 600):
                raise PipelineConfigError(f"{where}: stop_on holds HTTP statuses and `html`, not {status!r}")
        return dict(policy)

    def policy(self, url: str) -> dict:
        """The policy of ``url``'s host: its own, else ``default``."""
        host = (urlsplit(url).hostname or "").lower()
        return self.hosts.get(host, self.default)

    def http_for(self, url: str) -> dict:
        """The fetcher settings (``HTTPFetcher``'s) for ``url``: the run's, with its host's policy over them."""
        policy, out = self.policy(url), dict(self.base)
        if "rate_limits" in policy:
            out["rate_limits"] = [_rate(r, self.path) for r in policy["rate_limits"] or ()] or None
            if out["rate_limits"] is None:
                out.pop("rate_limits")
        if policy.get("direct"):
            out.pop("proxy_file", None)
            out["trust_env"], out["proxy"] = False, None
        elif policy.get("proxies"):
            out["proxy_file"] = policy["proxies"]
        for key in ("user_agent", "attempt_timeout", "max_retries"):
            if key in policy:
                out[key] = policy[key]
        if policy.get("random_user_agent"):
            out["use_fake_user_agent"] = True
        if "blacklist_ttl" in policy:
            out["proxy_blacklist_ttl"] = seconds(policy["blacklist_ttl"], self.path)
        if "blacklist_threshold" in policy:
            out["proxy_blacklist_threshold"] = int(policy["blacklist_threshold"])
        statuses = [s for s in policy.get("stop_on") or () if isinstance(s, int)]
        if statuses:
            out["stop_on"] = statuses
        return out

    def stops_on_html(self, url: str) -> bool:
        return "html" in (self.policy(url).get("stop_on") or ())

    def describe(self) -> str:
        """One line per host for the start of a run."""
        def one(name: str, p: dict) -> str:
            parts = [", ".join(p.get("rate_limits") or []) or "no rate limit"]
            parts.append("direct" if p.get("direct") else "through proxies" if p.get("proxies") else "")
            if p.get("proxies") and p.get("blacklist_ttl"):
                parts.append(f"a blocked proxy left out {p['blacklist_ttl']}")
            if p.get("stop_on"):
                parts.append("stops on " + ", ".join(map(str, p["stop_on"])))
            return f"{name}: " + ", ".join(x for x in parts if x)
        lines = [one(h, p) for h, p in self.hosts.items()]
        if self.default:
            lines.append(one("other hosts", self.default))
        return "; ".join(lines)
