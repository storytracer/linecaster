"""linecaster's markers, and the hooks that skip gpu and network tests where they cannot run."""
from linecaster.testing.markers import pytest_collection_modifyitems, pytest_configure  # noqa: F401 - the hooks
