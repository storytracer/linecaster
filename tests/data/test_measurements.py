"""The measurements vocabulary (``linecaster.data.MEASUREMENTS``): every key linecaster code writes into
``Annotator.measurements`` is in it. The code of the core and of the engine packages is read (``ast``) for every
place that writes measurements: ``measurements={...}`` (with ``**`` of a dict built in the same function; either
branch of a conditional), ``.measurements = {...}``, ``.measurements[key] = ...``, ``.measurements.setdefault(key, ...)`` and
``.update({...})``; a place whose keys the scan cannot see is listed in ``COMPUTED`` and checked by running it."""
import ast
from pathlib import Path

from linecaster.data import FINISH_REASONS, MEASUREMENTS, Annotator
from linecaster.data.measurements import unknown_measurements

REPO = Path(__file__).resolve().parents[2]
SOURCES = [REPO / "src" / "linecaster", *sorted((REPO / "engines").glob("*/src"))]
#: places whose keys are computed (file relative to the repository, the expression), each checked below
COMPUTED = {("src/linecaster/engines/typography.py", "stats.counts()")}


def _dict_keys(node: ast.Dict, local: dict[str, ast.AST]) -> tuple[set[str], list[str]]:
    keys, unresolved = set(), []
    for k, v in zip(node.keys, node.values):
        if k is None:                                   # **name
            if isinstance(v, ast.Name) and isinstance(local.get(v.id), ast.Dict):
                more, bad = _dict_keys(local[v.id], local)
                keys |= more
                unresolved += bad
            else:
                unresolved.append(ast.unparse(v))
        elif isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
        else:
            unresolved.append(ast.unparse(k))
    return keys, unresolved


def _locals(fn) -> dict[str, ast.AST]:
    """Names assigned once to a value in ``fn`` (tuple unpacking too)."""
    out = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
                elif isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple):
                    out.update({n.id: v for n, v in zip(t.elts, node.value.elts) if isinstance(n, ast.Name)})
    return out


def _is_measurements(node) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "measurements"


def written_keys() -> tuple[dict[str, set[str]], set[tuple[str, str]]]:
    """Key -> the files that write it, and the places whose keys are computed."""
    keys: dict[str, set[str]] = {}
    computed = set()
    for root in SOURCES:
        for f in sorted(root.rglob("*.py")):
            rel = f.relative_to(REPO).as_posix()
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                local = _locals(fn)
                params = {a.arg for a in [*fn.args.args, *fn.args.kwonlyargs]}

                def found(names, where=rel):
                    for k in names:
                        keys.setdefault(k, set()).add(where)

                for node in ast.walk(fn):
                    value = None
                    if isinstance(node, ast.Call):
                        for kw in node.keywords:
                            if kw.arg == "measurements":
                                value = kw.value
                        func = node.func
                        if isinstance(func, ast.Attribute) and _is_measurements(func.value) and node.args:
                            if func.attr == "setdefault" and isinstance(node.args[0], ast.Constant):
                                found([node.args[0].value])
                            elif func.attr == "update":
                                value = node.args[0]
                    elif isinstance(node, ast.Assign) and any(_is_measurements(x) for x in node.targets):
                        value = node.value
                    elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) \
                            and _is_measurements(node.value):
                        assert isinstance(node.slice, ast.Constant), f"{rel}: {ast.unparse(node)}"
                        found([node.slice.value])
                    if value is None:
                        continue
                    if isinstance(value, ast.BoolOp):              # measurements or {}
                        value = value.values[0]
                    for v in (value.body, value.orelse) if isinstance(value, ast.IfExp) else (value,):
                        if isinstance(v, ast.Name) and v.id in params:
                            continue                                # passed through from the caller
                        if isinstance(v, ast.Name) and isinstance(local.get(v.id), ast.Dict):
                            v = local[v.id]
                        if isinstance(v, ast.Dict):
                            names, bad = _dict_keys(v, local)
                            found(names)
                            computed |= {(rel, b) for b in bad}
                        else:
                            computed.add((rel, ast.unparse(v)))
    return keys, computed


def test_linecaster_writes_only_known_measurements():
    keys, computed = written_keys()
    unknown = {k: sorted(files) for k, files in keys.items() if k not in MEASUREMENTS}
    assert unknown == {}, f"add them to linecaster.data.MEASUREMENTS first: {unknown}"
    assert computed == COMPUTED
    # the scan sees the steps it should (a scan that finds nothing passes trivially)
    assert {"seconds", "datetime", "prompt_tokens", "completion_tokens", "finish_reason", "regions", "failed",
            "tables", "formulas", "changed"} <= set(keys)


def test_computed_measurements_are_known():
    from linecaster.text.typography import RetypeStats

    assert unknown_measurements(RetypeStats().counts()) == []


def test_unknown_measurements():
    assert unknown_measurements({"seconds": 1, "finish_reason": "stop"}) == []
    assert unknown_measurements({"finish_reason": None}) == []
    assert unknown_measurements({"secs": 1, "finish_reason": "eos"}) == ["secs", "finish_reason='eos'"]
    assert "length" in FINISH_REASONS and all(MEASUREMENTS.values())
    # measurements are not validated on the model: page records of other producers read as they are
    assert Annotator(step="x", name="y", measurements={"other": 1}).measurements == {"other": 1}
