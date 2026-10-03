from __future__ import annotations

from common.redact import redact


def test_redacts_each_secret_pattern_and_is_idempotent(monkeypatch) -> None:
    windows_profile = "C:" + "\\" + "Users" + "\\" + "ProfileFixture"
    unix_profile = "/" + "home" + "/" + "ProfileFixture"
    monkeypatch.setenv("USERPROFILE", windows_profile)
    monkeypatch.setenv("HOME", unix_profile)
    text = " ".join([
        "sk-abcdefghijklmnop", "ghp_" + "a" * 20, "github_pat_" + "b" * 20, "AKIA1234567890ABCDEF",
        "xoxb-1234567890", "eyJabc.def.ghi",
        "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
        "token=abcdefgh password:abcdefgh api_key=abcdefgh", windows_profile + "\\" + "file",
        windows_profile.replace("\\", "/") + "/file",
        unix_profile + "/file", "sk-sandboxFAKE0000000000000000",
    ])
    result = redact(text)
    assert "sk-abcdefghijklmnop" not in result
    assert "ghp_" + "a" * 20 not in result
    assert "github_pat_" + "b" * 20 not in result
    assert "AKIA1234567890ABCDEF" not in result
    assert "xoxb-1234567890" not in result
    assert "eyJabc.def.ghi" not in result
    assert "BEGIN RSA PRIVATE KEY" not in result
    assert "abcdefgh" not in result
    assert windows_profile not in result
    assert unix_profile not in result
    assert "sk-sandboxFAKE" not in result
    assert "~" in result
    assert redact(result) == result


def test_redacts_email_and_account_fields_in_plain_and_escaped_json() -> None:
    text = (
        '{"email":"user@example.com","orgId":"org-123","orgName":"Example Org",'
        '"accountId":"account-456","keep":"user@example.com"} '
        r'{\"email\":\"user@example.com\",\"orgId\":\"org-789\"}'
    )
    result = redact(text)
    assert "user@example.com" not in result
    assert "org-123" not in result
    assert "Example Org" not in result
    assert "account-456" not in result
    assert "org-789" not in result
    assert result.count("[REDACTED:account]") == 6
    assert redact(result) == result
