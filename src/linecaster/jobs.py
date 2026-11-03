"""Hugging Face Jobs helpers for linecaster pipelines (on datatrove's ``JobsPipelineExecutor``).

* ``dependencies(commit)``: what a Job installs with ``uv run --with`` to run the kraken + PaddleX
  engines in-process or behind ``ServeModels``: linecaster and its two engine packages pinned by
  commit (public GitHub), the kraken fork, the OpenCV stub (PaddleX pins OpenCV's GUI build, which
  needs libGL; the Jobs image has none, so ``stubs/opencv-contrib-python`` satisfies the pin with the
  headless build of the same version) and the versions the goldens were recorded with.
* ``WheelJobsExecutor``: ``JobsPipelineExecutor`` that also mounts volumes into every Job. A private
  derivative ships its code as a wheel: ``upload_wheel`` puts it in a bucket folder, the executor
  mounts that folder read-only (authorised by the Job's own HF token; no credential is persisted)
  and ``uv run --with <mount>/<wheel>`` installs it. ``wheel_volume`` builds the mount.

``uv run --with`` ignores ``[tool.uv.sources]``, so everything here is spelled out as URLs.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from datatrove.executor import JobsPipelineExecutor

REPO = "https://github.com/storytracer/linecaster"
# kraken takes its version from git history (versioningit), so the fork needs git+ (the default Jobs image has git)
KRAKEN_FORK = "kraken @ git+https://github.com/storytracer/kraken@3d235ee8"
#: the versions the goldens were recorded with (envs/kraken-paddlex constraint-dependencies)
PINS = ("lightning==2.6.6", "onnxruntime-gpu==1.29.0", "pillow==12.3.0")
WHEEL_MOUNT = "/wheels"


def dependencies(commit: str, engines: bool = True) -> list[str]:
    """``uv run --with`` requirements for a Job at linecaster ``commit`` (must be pushed). With
    ``engines=False`` only linecaster itself (a CPU pipeline, or a VLM pipeline whose image brings vLLM).

    linecaster is installed from GitHub's source archive (``.../archive/<rev>.tar.gz``), not with ``git+``:
    some images (``vllm/vllm-openai``) have uv but no git executable. The kraken fork still needs git (its
    version comes from git history); the default Jobs image, which engine Jobs use, has it."""
    repo = f"{REPO}/archive/{commit}.tar.gz"
    deps = [f"linecaster @ {repo}"]
    if engines:
        deps += [f"linecaster-kraken @ {repo}#subdirectory=backends/kraken",
                 f"linecaster-paddlex @ {repo}#subdirectory=backends/paddlex", KRAKEN_FORK,
                 f"opencv-contrib-python @ {repo}#subdirectory=stubs/opencv-contrib-python", *PINS]
    return deps


def bucket_parts(url: str) -> tuple[str, str]:
    """``hf://buckets/ns/name[/prefix]`` -> (``ns/name``, ``prefix``)."""
    parts = url.removeprefix("hf://buckets/").strip("/").split("/")
    return "/".join(parts[:2]), "/".join(parts[2:])


def wheel_volume(folder_url: str, mount_path: str = WHEEL_MOUNT) -> dict:
    """A read-only bucket volume for ``WheelJobsExecutor(volumes=[...])`` from ``hf://buckets/ns/name/path``."""
    bucket, path = bucket_parts(folder_url)
    vol = {"type": "bucket", "source": bucket, "mount_path": mount_path, "read_only": True}
    if path:
        vol["path"] = path
    return vol


def build_wheel(project: str | Path, out_dir: str | Path | None = None) -> Path:
    """``uv build --wheel`` for the project at ``project``; returns the newest wheel."""
    project = Path(project)
    out = Path(out_dir) if out_dir else project / "dist"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out)], cwd=project, check=True,
                   capture_output=True, text=True)
    return max(out.glob("*.whl"), key=lambda p: p.stat().st_mtime)


def upload_wheel(wheel: str | Path, folder_url: str) -> str:
    """Upload ``wheel`` to ``folder_url`` (``hf://buckets/...``); returns its URL."""
    from huggingface_hub import HfFileSystem

    wheel = Path(wheel)
    url = f"{folder_url.rstrip('/')}/{wheel.name}"
    HfFileSystem().put_file(str(wheel), url)
    return url


class WheelJobsExecutor(JobsPipelineExecutor):
    """``JobsPipelineExecutor`` that mounts ``volumes`` (dicts of ``huggingface_hub.Volume`` fields)
    into every Job it launches."""

    def __init__(self, *args, volumes: list[dict] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.volumes = list(volumes or [])

    def _submit_array_index(self, array_index: int, pik_path: str, token: str) -> str:
        import huggingface_hub
        from huggingface_hub import Volume

        original = huggingface_hub.run_uv_job
        volumes = [Volume(**v) for v in self.volumes]

        def run_uv_job(*args, **kwargs):
            kwargs["volumes"] = [*(kwargs.get("volumes") or []), *volumes]
            return original(*args, **kwargs)

        huggingface_hub.run_uv_job = run_uv_job     # the parent imports it at call time
        try:
            return super()._submit_array_index(array_index, pik_path, token)
        finally:
            huggingface_hub.run_uv_job = original
