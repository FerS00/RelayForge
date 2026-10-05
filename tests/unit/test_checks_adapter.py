from pathlib import Path

import pytest

from relayforge.adapters.checks import CheckCommand, ChecksAdapter, ChecksValidationError


def test_rejects_shell_install_and_invalid_timeout() -> None:
    for command in (
        {"name": "shell", "argv": ["powershell.exe", "-Command", "whoami"]},
        {"name": "install", "argv": ["npm", "ci"]},
        {"name": "empty", "argv": []},
        {"name": "timeout", "argv": ["pytest"], "timeout_seconds": 0},
    ):
        with pytest.raises(ChecksValidationError):
            CheckCommand.parse(command)


def test_environment_is_allowlisted(tmp_path: Path) -> None:
    plan = ChecksAdapter.build_run(
        CheckCommand("env", ("python", "-m", "pytest")),
        tmp_path,
        source_env={
            "PATH": "C:/tools",
            "TEMP": "C:/temp",
            "ANTHROPIC_API_KEY": "synthetic-secret",
            "CODEX_HOME": "C:/private",
            "AWS_ACCESS_KEY_ID": "synthetic-key",
        },
    )
    assert plan.env == {"PATH": "C:/tools", "TEMP": "C:/temp"}


def test_pytest_and_junit_results_are_parsed_safely(tmp_path: Path) -> None:
    assert ChecksAdapter.summarize_output("2 passed, 1 failed, 3 skipped in 0.2s") == {
        "passed": 2,
        "failed": 1,
        "skipped": 3,
    }
    report = tmp_path / "junit.xml"
    report.write_text('<testsuite tests="5" failures="1" errors="0" skipped="1"/>', encoding="utf-8")
    command = CheckCommand("junit", ("pytest", "--junitxml=junit.xml"))
    assert ChecksAdapter.junit_counts(tmp_path, command.argv) == {"passed": 3, "failed": 1, "skipped": 1}
    report.write_text("<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///secret'>]><testsuite/>", encoding="utf-8")
    assert ChecksAdapter.junit_counts(tmp_path, command.argv) is None


def test_junit_path_cannot_escape_worktree(tmp_path: Path) -> None:
    command = CheckCommand("junit", ("pytest", "--junitxml=../outside.xml"))
    assert ChecksAdapter.junit_counts(tmp_path, command.argv) is None
