from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil
import pytest

from common.procs import JobObject, alive_descendants, spawn_in_job, wait_tree_gone

CHILD = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)']); time.sleep(300)"
ROOT = "import subprocess,sys,time; [subprocess.Popen([sys.executable,'-c',sys.argv[1]]) for _ in range(2)]; time.sleep(300)"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects")
def test_job_terminates_process_tree(tmp_path: Path) -> None:
    with JobObject() as job:
        proc = spawn_in_job([sys.executable, "-c", ROOT, CHILD], job, tmp_path,
                            tmp_path / "out.log", tmp_path / "err.log")
        created = psutil.Process(proc.pid).create_time()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(alive_descendants(proc.pid, created)) < 4:
            time.sleep(0.05)
        assert len(alive_descendants(proc.pid, created)) >= 4
        job.terminate()
        assert wait_tree_gone(proc.pid, created, 5)
