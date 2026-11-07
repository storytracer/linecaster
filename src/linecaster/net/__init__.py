"""Network access: http(s) fetching through pybookget (``linecaster[pybookget]``)."""
from .http import HTTPFetcher, divided, is_url, prefetched

__all__ = ["HTTPFetcher", "divided", "is_url", "prefetched"]
