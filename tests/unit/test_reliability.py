from datetime import UTC, datetime

from relayforge.core.agent_health import classify_failure, retry_time


def test_failure_classification_defaults_closed() -> None:
    assert classify_failure("HTTP 429 rate limit") == "rate_limited"
    assert classify_failure("connection reset") == "network"
    assert classify_failure("authentication required") == "auth_required"
    assert classify_failure("unexpected output") == "unknown"


def test_retry_time_is_bounded_and_utc() -> None:
    now = datetime(2026, 10, 4, tzinfo=UTC)
    assert retry_time(0, now=now) == "2026-10-04T00:00:30Z"
    assert retry_time(10, now=now) == "2026-10-04T00:05:00Z"
