from __future__ import annotations

import time
from pathlib import Path

import psutil
import pytest

from relayforge.adapters.base import LaunchPlan
from relayforge.process.supervisor import Supervisor


def start_fake(
    tmp_path: Path, launcher: Path, scenario: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[Supervisor, object]:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", scenario)
    supervisor = Supervisor()
    handle = supervisor.start(
        LaunchPlan((str(launcher), "-p"), tmp_path, "hello"),
        output_path=tmp_path / "out.ndjson",
        stderr_path=tmp_path / "err.log",
    )
    return supervisor, handle


def test_reads_complete_utf8_lines_once(
    tmp_path: Path, fake_launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor, handle = start_fake(tmp_path, fake_launcher, "partial_lines", monkeypatch)
    observed: list[bytes] = []
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and supervisor.exit_code(handle) is None:
        observed.extend(supervisor.read_lines(handle))
        time.sleep(0.02)
    observed.extend(supervisor.read_lines(handle))
    text = b"".join(observed).decode("utf-8")
    assert "Café 🙂 split" in text
    assert len(observed) == len(set(observed))
    supervisor.kill(handle)


def test_kill_all_is_idempotent(tmp_path: Path, fake_launcher: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    supervisor, handle = start_fake(tmp_path, fake_launcher, "spawn_children", monkeypatch)
    time.sleep(0.4)
    descendants = psutil.Process(handle.pid).children(recursive=True)
    supervisor.kill(handle)
    supervisor.kill(handle)
    supervisor.kill_all()
    assert all(not process.is_running() for process in descendants)


def test_discards_and_counts_oversized_lines(
    tmp_path: Path, fake_launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor, handle = start_fake(tmp_path, fake_launcher, "oversized_line", monkeypatch)
    deadline = time.monotonic() + 5
    observed: list[bytes] = []
    while time.monotonic() < deadline:
        observed.extend(supervisor.read_lines(handle))
        if supervisor.exit_code(handle) is not None:
            break
        time.sleep(0.02)
    observed.extend(supervisor.read_lines(handle))
    assert handle.oversized_lines == 1
    assert all(line.startswith(b"{") for line in observed)
    supervisor.kill(handle)


def test_starts_agent_through_cmd_launcher(
    tmp_path: Path, fake_launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor, handle = start_fake(tmp_path, fake_launcher, "ok", monkeypatch)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and supervisor.exit_code(handle) is None:
        time.sleep(0.02)
    lines = supervisor.read_lines(handle)
    assert supervisor.exit_code(handle) == 0
    assert any(b'"type": "result"' in line for line in lines)
    supervisor.kill(handle)


def test_rejects_cmd_metacharacters_before_launch(tmp_path: Path, fake_launcher: Path) -> None:
    supervisor = Supervisor()
    with pytest.raises(ValueError, match="lanzadores por lotes"):
        supervisor.start(
            LaunchPlan((str(fake_launcher), "bad&argument"), tmp_path, "hello"),
            output_path=tmp_path / "out.ndjson",
            stderr_path=tmp_path / "err.log",
        )
    assert not (tmp_path / "out.ndjson").exists()


def test_kill_and_kill_all_tolerate_exited_process(
    tmp_path: Path, fake_launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor, handle = start_fake(tmp_path, fake_launcher, "ok", monkeypatch)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and supervisor.exit_code(handle) is None:
        time.sleep(0.02)
    assert supervisor.exit_code(handle) == 0
    supervisor.kill(handle)
    supervisor.kill_all()
