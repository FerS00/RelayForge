from pathlib import Path

from relayforge.security.redact import (
    StreamingRedactor,
    redact_json_text,
    redact_log_file,
    redact_text,
    redact_value,
)


def test_redacts_known_token_families_and_private_keys() -> None:
    samples = [
        "sk-" + "123456789012345678901234",
        "ghp_" + "123456789012345678901234",
        "github_pat_" + "12345678901234567890",
        "AKIA" + "1234567890ABCDEF",
        "xoxb-" + "1234567890-abcdef",
        "eyJ" + "abcdefghijk.abcdefghijk.abcdefghijk",
        "sk_live_" + "1234567890123456",
        "-----BEGIN PRIVATE KEY-----\nmaterial\n-----END PRIVATE KEY-----",
    ]
    source = " ".join(samples)
    result = redact_text(source)
    assert "1234567890" not in result
    assert "material" not in result
    assert result.count("[REDACTED]") >= 7


def test_redacts_labeled_values_and_personal_paths_but_keeps_normal_text() -> None:
    windows_path = "C:\\Users\\" + "moral\\repo"
    unix_path = "/home/" + "moral/app"
    source = f'password="synthetic-value" at {windows_path} and {unix_path}; ordinary prose'
    result = redact_text(source)
    assert "synthetic-value" not in result
    assert "moral" not in result
    assert "ordinary prose" in result


def test_recursive_redaction_preserves_shape_and_masks_sensitive_keys() -> None:
    value = {"text": "Bearer abcdefghijklmnop", "nested": [{"api_key": "synthetic"}], "count": 3}
    result = redact_value(value)
    assert result == {
        "text": "[REDACTED]",
        "nested": [{"api_key": "[REDACTED]"}],
        "count": 3,
    }


def test_json_redaction_returns_valid_json() -> None:
    result = redact_json_text('{"message":"password=synthetic","api_key":"synthetic-key"}')
    assert result == '{"message":"password=[REDACTED]","api_key":"[REDACTED]"}'


def test_streaming_redactor_catches_credentials_split_across_chunks() -> None:
    redactor = StreamingRedactor()
    first = redactor.push(("ordinary text " * 50) + "password=synthetic-")
    second = redactor.push("value still hidden ")
    final = redactor.finish()
    combined = first + second + final
    assert "synthetic-value" not in combined
    assert "password=[REDACTED]" in combined


def test_log_redaction_preserves_json_lines_and_scrubs_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "stdout.ndjson"
    token = "ghp_" + "123456789012345678901234"
    path.write_text(
        f'{{"message":"{token}"}}\nfailed at C:\\Users\\moral\\repo\n',
        encoding="utf-8",
    )
    with path.open("a", encoding="utf-8") as output:
        output.write(
            '{"type":"stream_event","event":{"type":"message_start"}}\n'
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"password=synthetic-"}}}\n'
            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"value"}}}\n'
            '{"type":"stream_event","event":{"type":"message_stop"}}\n'
        )
    redact_log_file(path)
    content = path.read_text(encoding="utf-8")
    assert "123456789012345678901234" not in content
    assert "moral" not in content
    assert "synthetic-value" not in content
    assert content.splitlines()[0] == '{"message":"[REDACTED]"}'
