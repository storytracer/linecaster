"""Provenance: what produced a transcription, for METS, and what a run resolved, for ``OUT/run.yaml``.

* ``mets_agent(m)`` turns one step (``ModelInfo``) into an OCR-D-style METS ``agent`` (an lxml element, for a
  derivative's METS output): ``TYPE="OTHER" OTHERTYPE="SOFTWARE" ROLE="OTHER"``, ``OTHERROLE`` the OCR-D
  functional step (``linecaster.catalog.schema.OCRD_STEPS``), ``name`` linecaster with its release and the
  model, a ``note`` with OCR-D's ``ocrd:option="parameter"`` for the settings (JSON) and one ``note`` per
  identifying field (``lc:option="preset"``, ``preset_sha256``, ``revision``, ...). ``from_mets_agent`` reads
  it back.
* ``step_entries(models)``: the steps as plain dicts, the shape the run record and the page files share.
* ``run_record(...)``: the run record a pipeline writes before it launches (``linecaster.runtime.run.run``): script, recipe,
  command line, options, executor, the pipeline's blocks with their backends and presets, software.

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

RUN_SCHEMA = "linecaster.run/1"
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

def _served_models(pipeline: list) -> dict[str, dict]:
    """Model name -> the model dict of the pipeline's ``ServeModels`` blocks (name, spec, kwargs, preset)."""
    out = {}
    for s in pipeline:
        if type(s).__name__ == "ServeModels":
            for m in getattr(s, "models", []):
                out[m["name"]] = m
    return out


def _engine(spec: str | None, kwargs: dict | None, preset: str | None, preset_sha256: str | None,
            overrides: dict | None = None) -> dict[str, Any]:
    """An engine model: its class, and the preset edition and hash it was built from, with the options given
    over the preset's (``--set``); its options only when there is no preset (a preset's hash covers them)."""
    out: dict[str, Any] = {}
    if spec:
        out["engine"] = spec
    if preset:
        out["preset"] = preset
        if preset_sha256:
            out["preset_sha256"] = preset_sha256
        if overrides:
            out["overrides"] = overrides
    elif kwargs:
        out["options"] = kwargs
    return out


def _chat_spec(spec) -> dict[str, Any]:
    out: dict[str, Any] = {"model": getattr(spec, "model", None)}
    for k in ("revision", "preset", "preset_sha256"):
        if getattr(spec, k, None):
            out[k] = getattr(spec, k)
    return out


def block_entry(block, served: dict[str, dict] | None = None) -> dict[str, Any]:
    """One block of a pipeline: its class, and for a model block its step and backend (with the engine and
    preset, from the backend when in-process and from the server's model list when served)."""
    entry: dict[str, Any] = {"block": type(block).__name__}
    backend = getattr(block, "backend", None)
    if backend is not None and hasattr(backend, "served"):
        entry["step"] = getattr(block, "step", None)
        if getattr(block, "spec", None) is not None:        # a chat VLM (ChatPageStep and friends)
            entry.update(_chat_spec(block.spec))
        if not backend.served:
            entry["backend"] = "in-process"
            entry.update(_engine(getattr(backend, "spec", None), getattr(backend, "kwargs", None),
                                 getattr(backend, "preset", None), getattr(backend, "preset_sha256", None),
                                 getattr(backend, "overrides", None)))
        else:
            entry["backend"] = "served"
            entry["endpoint"] = backend.endpoint
            entry["served_model"] = backend.model
            m = (served or {}).get(backend.model)
            if m is not None and getattr(block, "spec", None) is None:
                entry.update(_engine(m.get("spec"), m.get("kwargs"), m.get("preset"), m.get("preset_sha256"),
                                     m.get("overrides")))
    elif type(block).__name__ == "ServeModels":
        entry["port"] = block.port
        entry["models"] = [{"name": m["name"], **_engine(m.get("spec"), m.get("kwargs"), m.get("preset"),
                                                         m.get("preset_sha256"), m.get("overrides"))}
                           for m in block.models]
    elif type(block).__name__ == "ServeChatModel":
        entry["server"] = getattr(block, "server", None)
        entry["port"] = block.port
        entry.update(_chat_spec(block.spec))
    return entry


def pipeline_entries(pipeline: list) -> list[dict[str, Any]]:
    served = _served_models(pipeline)
    return [block_entry(s, served) for s in pipeline]


def engine_packages(pipeline: list) -> list[str]:
    """The distributions that provide the pipeline's engine classes (``linecaster-kraken``, ...), where
    installed here. Editable installs do not map their modules, so the module name with ``-`` for ``_`` is
    the fallback (``package_versions`` leaves out what is not installed)."""
    from importlib.metadata import packages_distributions

    specs = []
    for e in pipeline_entries(pipeline):
        specs += [e.get("engine")] + [m.get("engine") for m in e.get("models", [])]
    modules = {s.split(":", 1)[0].split(".", 1)[0] for s in specs if s}
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


def run_record(options: dict[str, Any], pipeline: list, *, script: str | None = None, argv: list[str] | None = None,
               executor: str | None = None, extra: dict[str, Any] | None = None,
               created: dt.datetime | None = None, recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    """The run record (schema ``linecaster.run/1``): the time, the pipeline script, the recipe (edition, hash,
    what the command line changed in it), the command line (``--env``
    values redacted) and the parsed options, where it runs (``on``, executor, tasks, workers), the pipeline's
    blocks in order (model blocks with backend, engine and preset), ``extra`` (e.g. the Jobs' image and
    dependencies) and the software (linecaster release and commit, Python, key packages, engine packages)."""
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
    rec["pipeline"] = pipeline_entries(pipeline)
    if extra:
        rec.update(_plain({k: v for k, v in extra.items() if v is not None}))
    rec["software"] = software(engine_packages(pipeline))
    return rec
