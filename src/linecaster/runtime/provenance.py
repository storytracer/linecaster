"""Provenance: what produced a transcription, for METS, and what a run resolved, for ``OUT/run.yaml``.

* ``mets_agent(m)`` turns one step (``ModelInfo``) into an OCR-D-style METS ``agent`` (an lxml element, for a
  derivative's METS output): ``TYPE="OTHER" OTHERTYPE="SOFTWARE" ROLE="OTHER"``, ``OTHERROLE`` the OCR-D
  functional step (``linecaster.catalog.schema.OCRD_STEPS``), ``name`` linecaster with its release and the
  model, a ``note`` with OCR-D's ``ocrd:option="parameter"`` for the settings (JSON) and one ``note`` per
  identifying field (``lc:option="preset"``, ``preset_sha256``, ``revision``, ...). ``from_mets_agent`` reads
  it back.
* ``step_entries(models)``: the steps as plain dicts, the shape the run record and the page files share.
* ``run_record(...)``: the run record a pipeline writes before it launches (``linecaster.runtime.run.run``): script, recipe,
  command line, options, executor, the pipeline (every stage's blocks as ``to_dict()`` with their contracts), its
  ``pipeline_sha256`` (``functional_pipeline``: the functional parameters only), software.

Import-light: lxml and the standard library (datatrove only for the blocks it inspects, lazily).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree

from ..data.transcription import ModelInfo
from ..formats import _provenance as P

RUN_SCHEMA = "linecaster.run-record/1"
METS = "http://www.loc.gov/METS/"
OCRD = "https://ocr-d.de"
LC = "https://github.com/storytracer/linecaster"
#: OCR-D step for linecaster steps OCRD_STEPS does not name (unicode, typography, ...: post-processing)
OCRD_FALLBACK_STEP = "recognition/post-correction"
#: packages the run record names besides linecaster (the engines' packages are added from the pipeline)
KEY_PACKAGES = ("datatrove", "saturate", "docling-core")


# ------------------------------------------------------------------------------------------------ software

def version() -> str:
    """linecaster's release."""
    return P.version()


@lru_cache(maxsize=1)
def commit() -> dict[str, Any] | None:
    """The linecaster commit this process runs: from the installation's PEP 610 ``direct_url.json`` (installed
    from git), else from the source checkout it is imported from (``dirty: true`` with uncommitted changes to
    tracked files). None when neither says."""
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        raw = distribution("linecaster").read_text("direct_url.json")
    except PackageNotFoundError:
        raw = None
    if raw:
        try:
            vcs = json.loads(raw).get("vcs_info") or {}
        except ValueError:
            vcs = {}
        if vcs.get("commit_id"):
            return {"commit": vcs["commit_id"]}
    return git_state(Path(__file__).resolve().parent)


def git_state(folder: str | Path) -> dict[str, Any] | None:
    """``{"commit": sha}`` (plus ``"dirty": True``) of the git checkout ``folder`` is in, or None."""
    def git(*args: str) -> str | None:
        try:
            r = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, timeout=10,
                               check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    sha = git("rev-parse", "HEAD")
    if not sha:
        return None
    out: dict[str, Any] = {"commit": sha}
    if git("status", "--porcelain", "--untracked-files=no"):
        out["dirty"] = True
    return out


def package_versions(names) -> dict[str, str]:
    """Installed versions of the distributions ``names`` (those not installed are left out)."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    out = {}
    for n in names:
        try:
            out[n] = dist_version(n)
        except PackageNotFoundError:
            pass
    return out


def software(extra_packages=()) -> dict[str, Any]:
    """linecaster's release and commit, Python, and the key packages' versions."""
    out: dict[str, Any] = {"linecaster": version()}
    state = commit()
    if state:
        out.update(state)
    out["python"] = platform.python_version()
    names = list(dict.fromkeys([*KEY_PACKAGES, *extra_packages]))
    out["packages"] = package_versions(names)
    return out


# ------------------------------------------------------------------------------------------------ steps

def step_entry(m: ModelInfo) -> dict[str, Any]:
    """One step as the page files record it: step, name, revision, preset, preset hash, backend, settings."""
    return P.record(m)


def step_entries(models: list[ModelInfo]) -> list[dict[str, Any]]:
    return [step_entry(m) for m in models]


def ocrd_step(step: str) -> str:
    """The OCR-D functional step of a linecaster step."""
    from ..catalog.schema import OCRD_STEPS

    return OCRD_STEPS.get(step, OCRD_FALLBACK_STEP)


def mets_agent(m: ModelInfo) -> etree._Element:
    """An OCR-D-style METS ``agent`` for one step (namespaces ``mets``, ``ocrd`` and ``lc`` declared on it)::

        <mets:agent TYPE="OTHER" OTHERTYPE="SOFTWARE" ROLE="OTHER" OTHERROLE="recognition/text-recognition">
          <mets:name>linecaster 0.4.0 kraken-ppocrv6-medium@0123abcd</mets:name>
          <mets:note ocrd:option="parameter">{"batch_size":8}</mets:note>
          <mets:note lc:option="step">recognition</mets:note>
          <mets:note lc:option="preset">kraken-ppocrv6-medium@1</mets:note>
          ...
        </mets:agent>
    """
    agent = etree.Element(f"{{{METS}}}agent", nsmap={"mets": METS, "ocrd": OCRD, "lc": LC})
    for k, v in (("TYPE", "OTHER"), ("OTHERTYPE", "SOFTWARE"), ("ROLE", "OTHER"), ("OTHERROLE", ocrd_step(m.step))):
        agent.set(k, v)
    etree.SubElement(agent, f"{{{METS}}}name").text = (
        f"{P.software()} {m.name}" + (f"@{m.revision}" if m.revision else ""))
    if m.settings:
        note = etree.SubElement(agent, f"{{{METS}}}note")
        note.set(f"{{{OCRD}}}option", "parameter")
        note.text = P.dumps(m.settings)
    for k, v in step_entry(m).items():
        if k == "settings":
            continue
        note = etree.SubElement(agent, f"{{{METS}}}note")
        note.set(f"{{{LC}}}option", k)
        note.text = v
    return agent


def mets_agents(models: list[ModelInfo]) -> list[etree._Element]:
    return [mets_agent(m) for m in models]


def from_mets_agent(agent: etree._Element) -> ModelInfo:
    """The step a ``mets_agent`` describes."""
    rec: dict[str, Any] = {}
    for note in agent.iter(f"{{{METS}}}note"):
        if note.get(f"{{{OCRD}}}option") == "parameter":
            rec["settings"] = json.loads(note.text or "{}")
        elif note.get(f"{{{LC}}}option") in P.RECORD_KEYS:
            rec[note.get(f"{{{LC}}}option")] = note.text or ""
    return P.from_record(rec)


# ------------------------------------------------------------------------------------------------ run record

def pipeline_section(plan) -> list[dict[str, Any]]:
    """The run record's ``pipeline``: per stage its name, tasks and blocks in order, each block as its
    ``to_dict()`` with its contract (``Plan.describe()``'s stages)."""
    return plan.describe()["stages"] if plan is not None else []


def _served_models(blocks: list) -> dict[str, dict]:
    """Model name -> the model dict of the ``ModelServer`` blocks (name, spec, kwargs, preset, preset_sha256)."""
    out = {}
    for b in blocks:
        if type(b).__name__ == "ModelServer":
            for m in getattr(b, "models", []):
                out[m["name"]] = m
    return out


def _functional_backend(backend: dict, served: dict[str, dict]) -> dict[str, Any]:
    """What a model block's backend contributes to the pipeline's hash: the engine, its options and the preset
    edition with its hash, wherever the engine runs (in-process, or the server model a served backend names);
    for a server this run does not start, what the backend knows (engine, preset, else the served model's name)."""
    from ..blocks.base.block import plain

    if backend.get("backend") == "in-process":
        out = {"engine": backend.get("engine"), "options": backend.get("options") or {},
               "preset": backend.get("preset"), "preset_sha256": backend.get("preset_sha256")}
    elif (m := served.get(backend.get("model"))) is not None:
        out = {"engine": m.get("spec"), "options": plain(m.get("kwargs") or {}), "preset": m.get("preset"),
               "preset_sha256": m.get("preset_sha256")}
    else:
        out = {"engine": backend.get("engine"), "preset": backend.get("preset")}
        if not any(out.values()):
            out["model"] = backend.get("model")
    return {k: v for k, v in out.items() if v is not None}


def _functional_value(value, served: dict[str, dict]):
    if isinstance(value, dict) and "backend" in value and isinstance(value.get("backend"), str):
        return _functional_backend(value, served)
    if isinstance(value, dict) and "adapter" in value and "preset" in value:       # a chat adapter
        return {k: v for k, v in value.items() if k != "served_name"}
    return value


def functional_block(block, served: dict[str, dict] | None = None) -> dict[str, Any] | None:
    """What a block contributes to the pipeline's hash: its class and its functional parameters (every parameter
    but its ``operational_params()``; backends by their engine, options and preset, ``_functional_backend``), its
    condition and group. Server blocks contribute nothing (their models count through the blocks they serve)."""
    from ..blocks.base.contract import contract_of
    from .builder import block_dict

    if contract_of(block).role == "server":
        return None
    d = block_dict(block)
    out: dict[str, Any] = {"block": d["block"], "class": d["class"]}
    operational = block.operational_params() if hasattr(block, "operational_params") else frozenset()
    params = {k: _functional_value(v, served or {}) for k, v in (d.get("params") or {}).items() if k not in operational}
    if params:
        out["params"] = params
    when = getattr(block, "when", None)
    if when is not None:
        out["when"] = when.describe()
        if getattr(block, "group", None) is not None:
            out["group"] = block.group
    return out


def functional_pipeline(plan) -> list[dict[str, Any]]:
    """The pipeline as its hash covers it: every stage's blocks in order (``functional_block``)."""
    blocks = plan.blocks if plan is not None else []
    served = _served_models(blocks)
    return [f for b in blocks if (f := functional_block(b, served)) is not None]


def pipeline_sha256(plan) -> str:
    """The hash of the pipeline's functional parameters (``functional_pipeline``), canonical JSON: the same for a
    resumed run, a run on another executor or backend, or into another folder; different when a block, a preset, an
    engine option or any other functional parameter changes."""
    from ..catalog.registry import canonical_sha256

    return canonical_sha256(functional_pipeline(plan))


def engine_packages(plan) -> list[str]:
    """The distributions that provide the pipeline's engine classes (``linecaster-kraken``, ...), where
    installed here. Editable installs do not map their modules, so the module name with ``-`` for ``_`` is
    the fallback (``package_versions`` leaves out what is not installed)."""
    from importlib.metadata import packages_distributions

    blocks = plan.blocks if plan is not None else []
    specs = [m.get("spec") for m in _served_models(blocks).values()]
    for b in blocks:
        backend = getattr(b, "backend", None)
        specs.append(getattr(backend, "spec", None) if not getattr(backend, "served", True) else
                     getattr(backend, "engine", None))
    modules = {s.split(":", 1)[0].split(".", 1)[0] for s in specs if isinstance(s, str)}
    dists = packages_distributions()
    return sorted({d for mod in modules for d in dists.get(mod) or [mod.replace("_", "-")]})


def redact_argv(argv: list[str]) -> list[str]:
    """The command line without the values of ``--env KEY=VALUE`` (they may hold credentials)."""
    out, after_env = [], False
    for x in argv:
        if after_env and "=" in x:
            x = x.split("=", 1)[0] + "=<redacted>"
        elif x.startswith("--env="):
            x = "--env=" + x[len("--env="):].split("=", 1)[0] + "=<redacted>"
        after_env = x == "--env"
        out.append(x)
    return out


def _plain(v: Any) -> Any:
    """Options as YAML-friendly values (paths and other objects as text)."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def script_entry(script: str | None) -> dict[str, Any] | None:
    """The pipeline script: its path in its git checkout (else its file name) and the sha256 of the file."""
    if not script:
        return None
    path = Path(script)
    out: dict[str, Any] = {"path": path.name}
    try:
        top = subprocess.run(["git", "-C", str(path.resolve().parent), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10, check=False)
        if top.returncode == 0 and top.stdout.strip():
            out["path"] = path.resolve().relative_to(Path(top.stdout.strip()).resolve()).as_posix()
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        out["sha256"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        pass
    return out


def run_record(options: dict[str, Any], plan=None, *, script: str | None = None, argv: list[str] | None = None,
               executor: str | None = None, extra: dict[str, Any] | None = None,
               created: dt.datetime | None = None, recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    """The run record (schema ``linecaster.run-record/1``, ``linecaster.runtime.record.RunRecord``): the time, the
    pipeline script, the recipe (edition, hash, what the command line changed in it), the command line (``--env``
    values redacted) and the parsed options, where it runs (``on``, executor, tasks, workers), the pipeline of the
    builder's ``plan`` (per stage its blocks as dicts, in order, with their contracts) and its ``pipeline_sha256``,
    ``extra`` (the Jobs' image and dependencies) and the software (linecaster release and commit, Python, key
    packages, engine packages). Validated against ``RunRecord``."""
    from .record import RunRecord

    opts = _plain(dict(options))
    if opts.get("env"):
        opts["env"] = [kv.split("=", 1)[0] + "=<redacted>" for kv in opts["env"]]
    when = (created or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    rec: dict[str, Any] = {"schema": RUN_SCHEMA, "created": when.strftime("%Y-%m-%dT%H:%M:%SZ")}
    entry = script_entry(script)
    if entry:
        rec["script"] = entry
    if recipe:
        rec["recipe"] = recipe
    if argv is not None:
        rec["argv"] = redact_argv(list(argv))
    if "on" in opts:
        rec["on"] = opts.pop("on")
    if executor:
        rec["executor"] = executor
    for k in ("tasks", "workers"):
        if k in opts:
            rec[k] = opts.pop(k)
    rec["options"] = opts           # the rest of the parsed options
    rec["pipeline"] = pipeline_section(plan)
    rec["pipeline_sha256"] = pipeline_sha256(plan)
    if extra:
        rec.update(_plain({k: v for k, v in extra.items() if v is not None}))
    rec["software"] = software(engine_packages(plan))
    return RunRecord.model_validate(rec).model_dump(mode="json", by_alias=True, exclude_none=True)
