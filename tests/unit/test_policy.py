from pathlib import Path

import pytest

from relayforge.core.policy import PolicyEngine, PolicyError, PolicyOperation


def operation(**changes: object) -> PolicyOperation:
    values: dict[str, object] = {
        "agent": "core",
        "role": "delivery",
        "repo": "repo-1",
        "workflow": "feature",
        "tool": "git",
        "operation": "git.push",
        "target": "origin:refs/heads/agent/job-1",
        "risk": "normal",
        "paths": (),
    }
    values.update(changes)
    return PolicyOperation(**values)  # type: ignore[arg-type]


def test_policy_specific_layer_wins_but_deny_always_wins() -> None:
    engine = PolicyEngine(
        {
            "version": 1,
            "defaults": {"git.push": "ask"},
            "profiles": {"trusted": {"git.push": "allow"}},
            "workflows": {"feature": {"git.push": "allow"}},
            "overrides": [{"repo": "repo-1", "git.push": "deny"}],
        }
    )
    result = engine.evaluate(operation(), profile="trusted")
    assert result.decision == "deny"


def test_security_paths_escalate_workflow_and_protected_targets_are_denied() -> None:
    engine = PolicyEngine.load(Path(__file__).resolve().parents[2] / "config/policies/default.yaml")
    result = engine.evaluate(operation(paths=("src/auth/session.py",)))
    assert result.workflow == "security"
    for target in ("git.force_push", "git.merge", "git.push_protected_branch"):
        protected = engine.evaluate(operation(operation=target))
        assert protected.decision == "deny"


def test_invalid_policy_version_is_rejected() -> None:
    with pytest.raises(PolicyError):
        PolicyEngine({"version": 9, "defaults": {}, "profiles": {}, "workflows": {}})


def test_invalid_unused_rule_is_rejected_at_load_time() -> None:
    with pytest.raises(PolicyError):
        PolicyEngine({"version": 1, "defaults": {"git.push": "sometimes"}, "profiles": {}, "workflows": {}})
