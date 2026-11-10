"""Network access: http(s) fetching (``linecaster.net.http``), its rate limits, the proxies shared through the broker
and the HTTP policy."""
from .http import HTTPFetcher, is_url, prefetched

__all__ = ["HTTPFetcher", "is_url", "prefetched"]
