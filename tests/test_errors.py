"""The error classes: library code raises them, never ``SystemExit``; only the command line turns them into exit
codes."""
import ast
from pathlib import Path

import pytest

from linecaster import errors
from linecaster.errors import CatalogError, LinecasterError, PageError, PipelineConfigError, ServerError

SRC = Path(__file__).resolve().parents[1] / "src" / "linecaster"
#: where an error becomes an exit code: the ``linecaster`` command and a pipeline script's ``main``
COMMAND_LINE = {("cli.py", None), ("runtime/run.py", "main")}


def test_the_hierarchy():
    for cls in (PipelineConfigError, CatalogError, PageError, ServerError):
        assert issubclass(cls, LinecasterError) and not issubclass(cls, (KeyError, ValueError, SystemExit))
    e = PipelineConfigError(["a", "b"])
    assert e.problems == ["a", "b"] and str(e) == "the pipeline cannot run:\n- a\n- b"
    assert PipelineConfigError("one").problems == ["one"]
    p = PageError("b_0001", "LineDetector", "boom")
    assert (p.page_id, p.block, str(p)) == ("b_0001", "LineDetector", "page b_0001 failed in LineDetector: boom")
    assert str(PageError("b_0002")) == "page b_0002 failed"
    assert [errors.exit_code(x) for x in (e, CatalogError("x"), p, ServerError("x"), RuntimeError())] == [2, 1, 1, 1, 1]


def _exits(tree: ast.AST):
    """``(function, line)`` of every ``raise SystemExit``, ``sys.exit(...)`` and ``exit(...)``."""
    found = []

    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            here = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(child, ast.Raise) and child.exc is not None:
                exc = child.exc.func if isinstance(child.exc, ast.Call) else child.exc
                if isinstance(exc, ast.Name) and exc.id == "SystemExit":
                    found.append((fn, child.lineno))
            if isinstance(child, ast.Call):
                f = child.func
                if (isinstance(f, ast.Attribute) and f.attr == "exit" and getattr(f.value, "id", None) == "sys") or (
                        isinstance(f, ast.Name) and f.id == "exit"):
                    found.append((fn, child.lineno))
            walk(child, here)

    walk(tree, None)
    return found


def test_no_system_exit_in_library_code():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        for fn, line in _exits(ast.parse(path.read_text(encoding="utf-8"))):
            if (rel, None) in COMMAND_LINE or (rel, fn) in COMMAND_LINE:
                continue
            offenders.append(f"{rel}:{line} ({fn})")
    assert offenders == []


def test_the_rule_finds_an_exit():
    tree = ast.parse("import sys\ndef f():\n    raise SystemExit('x')\ndef g():\n    sys.exit(1)\n")
    assert _exits(tree) == [("f", 3), ("g", 5)]


def test_library_errors_are_linecaster_errors(tmp_path):
    from linecaster.blocks.readers.images import ImageFolderReader
    from linecaster.catalog.registry import catalog
    from linecaster.runtime import jobs, run

    with pytest.raises(CatalogError):
        catalog().preset("no-such-preset")
    with pytest.raises(PipelineConfigError):
        run.overrides(["recognition.x"], ["recognition"])
    with pytest.raises(PipelineConfigError):
        list(ImageFolderReader(str(tmp_path)).run())
    with pytest.raises(PipelineConfigError):
        jobs.dependencies("abc123")
