from pathlib import Path

from relayforge.git.delivery import GitDelivery


class UnusedApprovals:
    def is_approved(self, job_id, operation, diff_hash):
        return False


def test_delivery_refuses_missing_exact_approval_before_git_write() -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(_repo: Path, *args: str, timeout: float = 30) -> str:
        calls.append(args)
        if args[:3] == ("symbolic-ref", "--quiet", "--short"):
            return "agent/job-1"
        if args and args[0] == "diff":
            return "approved diff"
        return ""

    delivery = GitDelivery(UnusedApprovals(), fake_git)
    try:
        delivery.deliver(
            job_id="j1",
            job_number=1,
            worktree=Path("."),
            expected_branch="agent/job-1",
            message="Job 1: example",
            diff_hash=delivery.diff_hash("approved diff"),
            operation={
                "operation": "git.push",
                "branch": "agent/job-1",
                "remote": "origin",
            },
        )
    except RuntimeError as exc:
        assert "aprobación vigente" in str(exc)
    else:
        raise AssertionError("Delivery should reject a missing approval")
    assert not any(args and args[0] in {"commit", "push"} for args in calls)
