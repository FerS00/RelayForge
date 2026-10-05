from relayforge.security.personal_paths import personal_path_lines


def test_detects_windows_and_unix_home_paths_without_returning_values() -> None:
    windows = "C:\\" + "Users\\alice\\project"
    unix = "/home/" + "alice/project"
    root = "/root/" + "build-agent"
    result = personal_path_lines(f"safe\n{windows}\n{unix}\n{root}")
    assert result == [2, 3, 4]


def test_allows_relative_and_placeholder_paths() -> None:
    assert personal_path_lines("src/file.py\nC:\\Users\\<user>\\repo\n") == []
