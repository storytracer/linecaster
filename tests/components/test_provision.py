"""Server environments built by uv: the release a version installs, the resolution date, the commands, one build per
machine."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from linecaster.components.servers import provision
from linecaster.errors import ServerError


def test_a_build_installs_its_release():
    assert provision.release_of("0.30.0") == "0.30.0"
    assert provision.release_of("0.5.20.dev10+g8d62f5fb9c") == "0.5.20"
    with pytest.raises(ServerError):
        provision.release_of("nightly")


def test_the_resolution_is_the_day_after_the_first_upload(monkeypatch):
    body = {"urls": [{"upload_time_iso_8601": "2026-09-22T18:04:11.123456Z"},
                     {"upload_time_iso_8601": "2026-09-22T17:59:00.000000Z"}]}
    monkeypatch.setattr(provision.urllib.request, "urlopen", lambda url, timeout: io.StringIO(json.dumps(body)))
    assert provision.resolved_at("vllm", "0.30.0") == "2026-09-23T00:00:00Z"


def test_the_commands_install_the_release_then_the_preset_s_packages(tmp_path):
    cmds = provision.install_commands("sglang", "0.5.20.dev10+g8d62f5fb9c", [["--no-deps", "https://x/sglang.whl"]],
                                      tmp_path / "e", exclude_newer="2026-10-01T00:00:00Z")
    py = str(tmp_path / "e" / "bin" / "python")
    assert cmds == [["uv", "venv", "-q", "--python", "3.12", str(tmp_path / "e")],
                    ["uv", "pip", "install", "-q", "--python", py, "--exclude-newer", "2026-10-01T00:00:00Z",
                     "sglang==0.5.20"],
                    ["uv", "pip", "install", "-q", "--python", py, "--no-deps", "https://x/sglang.whl"]]


def test_an_environment_is_built_once(monkeypatch, tmp_path):
    monkeypatch.setenv(provision.ENVS_VAR, str(tmp_path))
    monkeypatch.setattr(provision, "resolved_at", lambda package, version: "2026-09-23T00:00:00Z")
    ran = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def run(cmd, **kw):
        ran.append(cmd)
        if cmd[1] == "venv":
            Path(cmd[-1]).mkdir(parents=True)
        return Done()

    monkeypatch.setattr(provision.subprocess, "run", run)
    monkeypatch.setattr(provision, "_toolkit", lambda folder, uv, env: str(folder / "cuda"))   # vLLM gets one too
    a = provision.server_env("vllm", "0.30.0")
    assert a.parent == tmp_path and a.name.startswith("vllm-0.30.0-") and len(ran) == 2
    assert json.loads((a / ".ready").read_text())["exclude_newer"] == "2026-09-23T00:00:00Z"
    assert provision.cuda_home(a) == str(a / "cuda")
    assert provision.server_env("vllm", "0.30.0") == a and len(ran) == 2          # ready: nothing runs again
    assert provision.server_env("vllm", "0.30.0", [["fastokens==0.3.2"]]) != a     # other packages, other folder


def test_a_failed_build_says_why(monkeypatch, tmp_path):
    monkeypatch.setenv(provision.ENVS_VAR, str(tmp_path))
    monkeypatch.setattr(provision, "resolved_at", lambda package, version: "2026-09-23T00:00:00Z")

    class Failed:
        returncode, stdout, stderr = 1, "", "No solution found"

    monkeypatch.setattr(provision.subprocess, "run", lambda cmd, **kw: Failed())
    with pytest.raises(ServerError, match="No solution found"):
        provision.server_env("vllm", "0.30.0")
    with pytest.raises(ServerError, match="vllm or sglang"):
        provision.server_env("tgi", "1.0")


def test_a_server_finds_its_environment_s_cuda_libraries_after_the_machine_s(tmp_path):
    lib = tmp_path / "lib" / "python3.12" / "site-packages" / "nvidia" / "cu13" / "lib"
    lib.mkdir(parents=True)
    assert provision.library_path(tmp_path) == [str(lib)]
    assert provision.ld_library_path(tmp_path, "/usr/local/cuda-13.0/compat") == f"/usr/local/cuda-13.0/compat:{lib}"
    assert provision.ld_library_path(tmp_path / "none", None) is None


def test_auto_serves_with_the_server_here_only_at_the_preset_s_release(monkeypatch):
    """``--server-env auto``: vLLM's image at linecaster's pin serves a pinned preset; a preset that names another
    release, or a machine without vLLM, gets uv's."""
    from linecaster.components.servers.serve import ChatModelServer

    monkeypatch.setattr(provision, "found_release", lambda server, path, python=None: "0.30.0")
    assert ChatModelServer("dots-mocr", server_env="auto").found_here() == "path"          # the pin: 0.30.0
    assert ChatModelServer("lightonocr-2-1b", server_env="auto").found_here() == "uv"     # names 0.26.0
    monkeypatch.setattr(provision, "found_release", lambda server, path, python=None: None)
    assert ChatModelServer("dots-mocr", server_env="auto").found_here() == "uv"           # no vLLM here


def test_found_release_reads_the_server_s_own_version(monkeypatch, tmp_path):
    exe = tmp_path / "vllm"
    exe.write_text("#!/bin/sh\necho 'INFO some log line 1.2.3-not'\necho 0.30.0\n")
    exe.chmod(0o755)
    assert provision.found_release("vllm", str(tmp_path)) == "0.30.0"
    assert provision.found_release("vllm", str(tmp_path / "none")) is None
