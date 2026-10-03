from __future__ import annotations

import pytest

from poc09_health.run import agy_probe_result, claude_auth_result, codex_auth_result


@pytest.mark.parametrize("code,text,expected", [
    (0, '{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"firstParty",'
        '"subscriptionType":"max","email":"user@example.com","orgId":"private-id",'
        '"orgName":"Private Org"}', "AVAILABLE"),
    (1, '{"loggedIn":false,"authMethod":"claude.ai","apiProvider":"firstParty",'
        '"subscriptionType":"max","email":"user@example.com"}', "AUTH_REQUIRED"),
])
def test_claude_auth_parses_logged_in_json(code: int, text: str, expected: str) -> None:
    status, evidence = claude_auth_result(code, text)
    assert status == expected
    assert set(evidence) <= {"loggedIn", "authMethod", "apiProvider", "subscriptionType"}
    assert "email" not in evidence
    assert "orgId" not in evidence
    assert "orgName" not in evidence


def test_claude_auth_unknown_when_json_cannot_be_parsed() -> None:
    assert claude_auth_result(0, "not json") == ("UNKNOWN", {})


@pytest.mark.parametrize("code,text,expected", [
    (0, "Logged in using ChatGPT", "AVAILABLE"),
    (1, "Not logged in", "AUTH_REQUIRED"),
    (0, "Not logged in", "AUTH_REQUIRED"),
    (0, "unexpected response", "UNKNOWN"),
])
def test_codex_auth_uses_confirmed_status_text(code: int, text: str, expected: str) -> None:
    assert codex_auth_result(code, text)[0] == expected


def test_agy_auth_requires_success_result_with_nonempty_response() -> None:
    good = '{"event":"result","result":{"status":"SUCCESS","response":"OK"}}\n'
    empty = '{"event":"result","result":{"status":"SUCCESS","response":" "}}\n'
    failed = '{"event":"result","result":{"status":"FAILED","response":"OK"}}\n'
    assert agy_probe_result(good)[0] == "AVAILABLE"
    assert agy_probe_result(empty)[0] == "UNKNOWN"
    assert agy_probe_result(failed)[0] == "UNKNOWN"
