from __future__ import annotations

from poc10_autostart.probe import agy_result, claude_auth_result, claude_result, codex_auth_result, codex_result


def test_claude_auth_uses_logged_in_and_drops_account_fields() -> None:
    output = '{\n  "loggedIn": true,\n  "email": "private@example.com",' \
        '\n  "orgId": "private-org",\n  "orgName": "Private Org"\n}\n'
    assert claude_auth_result(0, output) == ("AVAILABLE", {"loggedIn": True})
    assert claude_auth_result(1, '{"loggedIn":false}') == ("AUTH_REQUIRED", {"loggedIn": False})


def test_codex_auth_status_text_is_conservative() -> None:
    assert codex_auth_result(0, "Logged in using ChatGPT\n") == ("AVAILABLE", "Logged in using ChatGPT")
    assert codex_auth_result(1, "Not logged in\n") == ("AUTH_REQUIRED", "Not logged in")
    assert codex_auth_result(0, "Unexpected\n")[0] == "UNKNOWN"


def test_deep_probe_extracts_terminal_agent_events() -> None:
    claude = '{"type":"assistant","message":{}}\n{"type":"result","is_error":false,' \
        '"result":"OK"}\n'
    codex = '{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}\n' \
        '{"type":"turn.completed"}\n'
    agy = '{"event":"progress"}\n{"event":"result","result":{"status":"SUCCESS",' \
        '"response":"OK"}}\n'
    assert claude_result(claude) == {"event": "result", "is_error": False, "result_nonempty": True}
    assert codex_result(codex) == {"event": "turn.completed", "result_nonempty": True}
    assert agy_result(agy) == {"event": "result", "status": "SUCCESS", "result_nonempty": True}


def test_result_parsers_do_not_treat_intermediate_events_as_final() -> None:
    assert claude_result('{"type":"assistant","result":"not final"}\n')["event"] is None
    assert codex_result('{"type":"item.completed","item":{"type":"agent_message",' \
                        '"text":"not final"}}\n')["event"] is None
    assert agy_result('{"event":"progress","result":{"status":"SUCCESS","response":"OK"}}')[
        "event"] is None
