"""Ctrl-C (SIGINT to the process group, as a terminal sends it): a run says what stopped and what runs again, prints no
traceback and ends by the signal itself (``returncode == -2``), so a shell loop around it stops; its unfinished tasks
run on the next launch. Real subprocesses, a small pipeline whose block sleeps per page."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")

SCRIPT = textwrap.dedent('''
    """A pipeline of tiny pages, each held a while."""
    import time

    from linecaster.blocks.base.page import PageBlock
    from linecaster.runtime import run


    class Slow(PageBlock):
        """Holds each page a while."""

        name = "slow"
        parts_read = ("metadata",)

        def process_page(self, doc, page):
            time.sleep(0.3)
            return page


    def options(ap):
        pass


    def models(a):
        return []


    def pipeline(a, script):
        return [run.reader(a), Slow(), run.pages(a)], {"engines": False}


    if __name__ == "__main__":
        run.main(__file__, __doc__, options, models, pipeline)
''')


@pytest.fixture
def run_folder(tmp_path):
    from PIL import Image

    (tmp_path / "in").mkdir()
    for i in range(60):
        Image.new("L", (8, 8), i).save(tmp_path / "in" / f"p{i:03d}.png")
    (tmp_path / "slow.py").write_text(SCRIPT)
    return tmp_path


def launch(cmd, wait_for: str, cwd: Path) -> tuple[int, str]:
    """Starts ``cmd`` in a session of its own, sends the group SIGINT once ``wait_for`` appeared in its output, and
    returns (returncode, output)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, text=True,
                         cwd=cwd, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    seen, deadline = [], time.monotonic() + 60
    for line in p.stdout:
        seen.append(line)
        if wait_for in line or time.monotonic() > deadline:
            break
    time.sleep(1.0)
    os.killpg(p.pid, signal.SIGINT)
    out, _ = p.communicate(timeout=60)
    return p.returncode, "".join(seen) + out


def test_ctrl_c_ends_a_run_by_the_signal_without_a_traceback_and_its_tasks_run_again(run_folder):
    cmd = [sys.executable, "slow.py", "in", "out", "--tasks", "6", "--workers", "2"]
    code, out = launch(cmd, " done: ", run_folder)                 # once a task has finished
    assert code == -signal.SIGINT, out
    assert "stopped:" in out and "not finished: they run again on the next launch" in out
    assert "Traceback" not in out and "KeyboardInterrupt" not in out
    again = subprocess.run(cmd, capture_output=True, text=True, cwd=run_folder, timeout=120)
    assert again.returncode == 0, again.stderr
    assert "done before" in again.stderr and "6/6 tasks" in again.stderr      # only the unfinished ones ran


def test_ctrl_c_stops_a_shell_loop_around_a_run(run_folder):
    loop = (f"for i in 1 2; do echo start $i; {sys.executable} slow.py in out-$i --tasks 6 --workers 2; done; "
            "echo loop-ended")
    code, out = launch(["bash", "-c", loop], "task", run_folder)
    assert "start 1" in out and "start 2" not in out and "loop-ended" not in out, out
    assert code == -signal.SIGINT
