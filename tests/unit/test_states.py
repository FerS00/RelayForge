import pytest

from relayforge.core.states import (
    TERMINAL_STATES,
    TRANSITIONS,
    InvalidTransition,
    JobStatus,
    validate_transition,
)


def test_transition_table_accepts_declared_edges_and_rejects_all_others() -> None:
    for source in JobStatus:
        for target in JobStatus:
            if target in TRANSITIONS[source]:
                assert validate_transition(source, target) == (source, target)
            else:
                with pytest.raises(InvalidTransition):
                    validate_transition(source, target)


@pytest.mark.parametrize("terminal", list(TERMINAL_STATES))
def test_terminal_jobs_are_immutable(terminal: JobStatus) -> None:
    assert TRANSITIONS[terminal] == frozenset()


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(InvalidTransition):
        validate_transition("ACTIVE", JobStatus.COMPLETED)
