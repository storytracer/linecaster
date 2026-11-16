"""Server environments built by uv: the server a preset's ``serve`` block names (vLLM, SGLang), installed at its
release into a virtual environment of its own, once per machine, and reused by every later task there.

A machine then needs uv and nothing else to serve any preset (a Ray cluster's nodes, a workstation); a job image
that has the server already (HF Jobs) uses its own (``--server-env path``).

* **The release**: the preset's ``serve.version`` (vLLM: linecaster's ``VLLM_VERSION`` unless the preset names
  another), from PyPI. A build's version (``0.5.20.dev10+g8d62f5fb9c``, a wheel the preset's ``server_packages``
  install) installs its release (``0.5.20``) first.
* **The resolution**: as of the day after that release was uploaded to PyPI (``--exclude-newer``), the closest a
  PyPI install comes to the release's own image, and the same on every machine and every day.
* **The preset's ``server_packages``** go in after it (``uv pip install`` with the preset's arguments), as they would
  into an image's Python.
* **A CUDA toolkit**, as a server's image has one (``TOOLKIT``: SGLang compiles kernels as it starts, vLLM in some
  warm-ups): NVIDIA's compiler and headers from PyPI at the version of the ``cuda-toolkit`` torch brought
  (``[nvcc,cccl,cudart]``, so every part is one release), laid out as a toolkit (``lib64``, the libraries' linker
  names); the server gets it as ``CUDA_HOME`` (``cuda_home``), and the environment's CUDA libraries on
  ``LD_LIBRARY_PATH`` (``ld_library_path``).
* **Where**: ``LINECASTER_SERVER_ENVS``, else ``~/.cache/linecaster/servers``; one folder per server, release,
  packages and Python, ready once it holds ``.ready``. Tasks on one machine build it once: the others wait on its
  lock.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from loguru import logger

from ...errors import ServerError

#: the server's package on PyPI
PACKAGES = {"vllm": "vllm", "sglang": "sglang"}
#: the Python the server environments run (the version every linecaster script runs)
PYTHON = "3.12"
#: servers whose environment gets a CUDA toolkit (both compile kernels: SGLang as it starts, vLLM in some warm-ups)
TOOLKIT = {"sglang", "vllm"}
ENVS_VAR = "LINECASTER_SERVER_ENVS"


def envs_root() -> Path:
    """Where the server environments are kept."""
    return Path(os.environ.get(ENVS_VAR) or Path.home() / ".cache" / "linecaster" / "servers")


def release_of(version: str) -> str:
    """The PyPI release a server version installs: the version itself, or a build's release (``0.5.20.dev10+g…``:
    ``0.5.20``)."""
    m = re.match(r"\d+(?:\.\d+)*", version)
    if not m:
        raise ServerError(f"not a release or a build of one: {version!r}")
    return m.group(0)


def resolved_at(package: str, version: str) -> str:
    """``--exclude-newer`` for a release: midnight UTC after the day its first file was uploaded to PyPI."""
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/{version}/json", timeout=60) as r:
        files = json.load(r)["urls"]
    if not files:
        raise ServerError(f"{package} {version} has no files on PyPI")
    first = min(dt.datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00")) for f in files)
    return (first.date() + dt.timedelta(days=1)).isoformat() + "T00:00:00Z"


def env_name(server: str, version: str, packages: list[list[str]] = (), python: str = PYTHON) -> str:
    """The environment's folder name: server, release and a hash of everything that goes in."""
    key = json.dumps([server, release_of(version), [list(p) for p in packages], python]
                     + (["toolkit"] if server in TOOLKIT else []))
    return f"{server}-{release_of(version)}-{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def install_commands(server: str, version: str, packages: list[list[str]], folder: Path, uv: str = "uv",
                     python: str = PYTHON, exclude_newer: str | None = None) -> list[list[str]]:
    """The commands that build the environment in ``folder``."""
    py = str(folder / "bin" / "python")
    release = release_of(version)
    pin = [f"{PACKAGES[server]}=={release}"]
    resolve = ["--exclude-newer", exclude_newer] if exclude_newer else []
    return ([[uv, "venv", "-q", "--python", python, str(folder)],
             [uv, "pip", "install", "-q", "--python", py, *resolve, *pin]]
            + [[uv, "pip", "install", "-q", "--python", py, *args] for args in packages])


def server_env(server: str, version: str, packages: list[list[str]] = (), python: str = PYTHON,
               uv: str = "uv") -> Path:
    """The environment with ``server`` at ``version`` (and ``packages``), built here unless it is already; its
    folder (the server's commands in ``bin``)."""
    if server not in PACKAGES:
        raise ServerError(f"no server environment for {server!r} (vllm or sglang)")
    if not version:
        raise ServerError(f"{server}: the preset names no version to install")
    root = envs_root()
    root.mkdir(parents=True, exist_ok=True)
    folder = root / env_name(server, version, packages, python)
    if (folder / ".ready").exists():
        return folder
    with open(root / f"{folder.name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)             # one task builds it; the others wait and find it ready
        if (folder / ".ready").exists():
            return folder
        shutil.rmtree(folder, ignore_errors=True)    # a build that stopped half way
        release = release_of(version)
        at = resolved_at(PACKAGES[server], release)
        logger.info("server environment {name}: {server} {release} as of {at} (once on this machine)",
                    name=folder.name, server=server, release=release, at=at)
        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")}
        cmds = install_commands(server, version, packages, folder, uv, python, at)
        for cmd in cmds:
            _run(cmd, env, folder)
        home = None
        if server in TOOLKIT:
            home = _toolkit(folder, uv, env)
        (folder / ".ready").write_text(json.dumps({"server": server, "version": version, "release": release,
                                                   "exclude_newer": at, "packages": packages,
                                                   "cuda_home": home}) + "\n")
    return folder


def found_release(server: str, path: str, python: str | None = None) -> str | None:
    """The release of the server already on ``path`` (vLLM's ``vllm``; SGLang in ``python``), ``None`` without one:
    for ``--server-env auto``, which serves a preset with it when it is the preset's release."""
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")}
    env["PATH"] = path
    if server == "vllm":
        exe = shutil.which("vllm", path=path)
        cmd = [exe, "--version"] if exe else None
    else:
        cmd = [python, "-c", "import sglang; print(sglang.__version__)"] if python else None
    if not cmd:
        return None
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.findall(r"\d+\.\d+\.\d+\S*", r.stdout or "")
    return release_of(found[-1]) if r.returncode == 0 and found else None


def library_path(folder: str | Path) -> list[str]:
    """The CUDA library folders of a server environment's NVIDIA packages (``nvidia/cu*/lib``, ``nvidia/*/lib``), for
    the server's ``LD_LIBRARY_PATH``: libraries a CUDA library opens by name at run time (NVRTC its
    ``libnvrtc-builtins``) are found there, as an image finds them in its toolkit's folder."""
    found = []
    for site in sorted(Path(folder).glob("lib/python3*/site-packages/nvidia")):
        found += [str(d) for d in sorted(site.glob("cu*/lib")) + sorted(site.glob("*/lib")) if d.is_dir()]
    return list(dict.fromkeys(found))


def ld_library_path(folder: str | Path, current: str | None) -> str | None:
    """``LD_LIBRARY_PATH`` for a server in ``folder``'s environment: the current one first (the machine's own, e.g.
    CUDA's compatibility libraries), then the environment's CUDA libraries; ``None`` when neither has any."""
    parts = [p for p in (current or "").split(os.pathsep) if p] + library_path(folder)
    return os.pathsep.join(dict.fromkeys(parts)) or None


def cuda_home(folder: str | Path) -> str | None:
    """The CUDA toolkit of a server environment (``TOOLKIT``), ``None`` without one."""
    ready = Path(folder) / ".ready"
    return json.loads(ready.read_text()).get("cuda_home") if ready.exists() else None


def _run(cmd: list[str], env: dict, folder: Path) -> str:
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise ServerError(f"server environment {folder.name}: {' '.join(cmd[:4])} ... failed: "
                          f"{(r.stderr or r.stdout).strip()[-2000:]}")
    return r.stdout


def _toolkit(folder: Path, uv: str, env: dict) -> str:
    """Install NVIDIA's compiler, headers and runtime at the environment's own ``cuda-toolkit`` release (torch's) and
    lay them out as a toolkit; returns its folder (``CUDA_HOME``)."""
    py = str(folder / "bin" / "python")
    out = _run([py, "-c", "import importlib.metadata as m, torch; "
                          "print(m.version('cuda-toolkit'), torch.version.cuda)"], env, folder).split()
    if len(out) != 2 or out[1] == "None":
        raise ServerError(f"server environment {folder.name}: no CUDA torch and cuda-toolkit to match a compiler to")
    release, cuda = out
    _run([uv, "pip", "install", "-q", "--python", py, f"cuda-toolkit[nvcc,cccl,cudart]=={release}"], env, folder)
    site = _run([py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], env, folder).strip()
    home = Path(site) / "nvidia" / f"cu{cuda.split('.')[0]}"
    if not (home / "bin" / "nvcc").exists():
        raise ServerError(f"server environment {folder.name}: no nvcc in {home}")
    lib = home / "lib"
    if not (home / "lib64").exists():
        (home / "lib64").symlink_to("lib")
    for so in lib.glob("lib*.so.*"):                     # linker names, as a toolkit's -dev packages add
        name = so.name.split(".so.")[0] + ".so"
        if not (lib / name).exists():
            (lib / name).symlink_to(so.name)
    return str(home)
