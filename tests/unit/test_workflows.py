from pathlib import Path

import pytest

from relayforge.core.workflows import WorkflowConfigError, WorkflowTemplates


@pytest.fixture
def templates() -> WorkflowTemplates:
    root = Path(__file__).resolve().parents[2] / "config" / "workflows"
    return WorkflowTemplates(root)


def test_auto_selects_plan_suggestion_and_security_cannot_be_downgraded(templates: WorkflowTemplates) -> None:
    assert templates.resolve("auto", "trivial").name == "trivial"
    assert templates.resolve("feature", "security").name == "security"


def test_auth_and_security_paths_elevate_from_trivial(templates: WorkflowTemplates) -> None:
    assert templates.elevate_for_paths("trivial", ["src/relayforge/auth/session.py"]).name == "security"
    assert templates.elevate_for_paths("feature", ["README.md"]).name == "feature"


def test_unknown_workflow_suggestion_fails_closed(templates: WorkflowTemplates) -> None:
    with pytest.raises(WorkflowConfigError):
        templates.resolve("auto", "unknown")
