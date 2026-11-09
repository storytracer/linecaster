"""The package's ``__version__`` is the release in pyproject.toml (the run records and traces name it)."""
import tomllib
from pathlib import Path

import linecaster


def test_the_package_version_is_the_release():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]
    assert linecaster.__version__ == project["version"]
