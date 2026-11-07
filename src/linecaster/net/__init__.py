"""Network access: http(s) fetching through pybookget (``linecaster[pybookget]``)."""
from .http import HTTPFetcher, is_url, prefetched

__all__ = ["HTTPFetcher", "is_url", "prefetched"]
