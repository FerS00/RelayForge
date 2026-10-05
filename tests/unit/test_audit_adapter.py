import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import relayforge.adapters.antigravity.adapter as adapter_module
from relayforge.adapters.antigravity.adapter import AntigravityAdapter


def test_audit_parser_rejects_invalid_or_duplicate_findings() -> None:
    row = {
        "id": "F1",
        "severity": "Alto",
        "file": "a.py",
        "line": 1,
        "title": "Issue",
        "evidence": "Proof",
        "recommendation": "Fix",
    }
    verdict, summary, findings = AntigravityAdapter._validate(
        {"verdict": "REJECTED", "summary": "Review", "findings": [row]}
    )
    assert verdict == "REJECTED" and summary == "Review" and findings[0].external_id == "F1"
    with pytest.raises(ValueError, match="audit_finding_invalid"):
        AntigravityAdapter._validate({"verdict": "APPROVED", "findings": [row, row]})
    with pytest.raises(ValueError, match="audit_output_invalid"):
        AntigravityAdapter._validate({"verdict": "BLOCKED", "findings": [], "extra": True})


def test_hashes_reject_symlink_escape(tmp_path: Path) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (worktree / "link.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(ValueError, match="audit_path_outside_worktree"):
        AntigravityAdapter._hashes(worktree, ["link.txt"])


def test_hash_change_during_successful_audit_becomes_blocked(tmp_path: Path, monkeypatch) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()
    source = worktree / "src.py"
    source.write_text("before", encoding="utf-8")
    monkeypatch.setattr(adapter_module.shutil, "which", lambda _: "agy.exe")

    def run(argv, **kwargs):
        source.write_text("changed during audit", encoding="utf-8")
        response = {"verdict": "APPROVED", "summary": "Looks good", "findings": []}
        event = {"event": "result", "result": {"response": json.dumps(response)}}
        return SimpleNamespace(returncode=0, stdout=(json.dumps(event) + "\n").encode())

    monkeypatch.setattr(adapter_module.subprocess, "run", run)
    result = AntigravityAdapter()._audit(worktree, ["src.py"], [], 1, "diff")
    assert result.verdict == "BLOCKED"
    assert result.hashes_before != result.hashes_after
