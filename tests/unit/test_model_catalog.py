import json
import subprocess
from pathlib import Path

from relayforge.doctor import model_catalog


def test_codex_cache_exposes_visible_valid_unique_slugs_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "identity": "synthetic-private",
                "models": [
                    {"slug": "fixture-model", "visibility": "list"},
                    {"slug": "fixture-model", "visibility": "list"},
                    {"slug": "hidden", "visibility": "hide"},
                    {"slug": "invalid model", "visibility": "list"},
                    {"slug": 123, "visibility": "list"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert model_catalog.discover_models("codex", "fake-codex") == ["fixture-model"]


def test_codex_cache_missing_malformed_or_oversized_is_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    path = tmp_path / "models_cache.json"
    assert model_catalog.discover_models("codex", "fake") == []
    for data in ("broken json", '{"models":null}', "x" * (model_catalog._MAX_CACHE_BYTES + 1)):
        path.write_text(data, encoding="utf-8")
        assert model_catalog.discover_models("codex", "fake") == []


def test_cli_catalogs_are_parsed_without_running_provider_turns(monkeypatch) -> None:
    monkeypatch.setattr(model_catalog.shutil, "which", lambda name: name)
    calls = []

    def run(argv):
        calls.append(argv)
        text = (
            "Fetching available models...\nfixture-medium\tFixture\ninvalid model\tIgnore\n"
            if argv[1] == "models"
            else "  --model <model> Use an alias (e.g. 'sonnet', 'opus').\n  --other 'not-a-model'\n"
        )
        return subprocess.CompletedProcess(argv, 0, text, "")

    monkeypatch.setattr(model_catalog, "_run_cli", run)
    assert model_catalog.discover_models("antigravity", "fake-agy") == ["fixture-medium"]
    assert model_catalog.discover_models("claude", "fake-claude") == ["sonnet", "opus"]
    assert calls == [["fake-agy", "models"], ["fake-claude", "--help"]]


def test_missing_cli_and_failed_probe_leave_default_available(monkeypatch) -> None:
    monkeypatch.setattr(model_catalog.shutil, "which", lambda _name: None)
    assert model_catalog.discover_models("antigravity", "fake") == []
    monkeypatch.setattr(model_catalog.shutil, "which", lambda name: name)
    monkeypatch.setattr(model_catalog, "_run_cli", lambda argv: subprocess.CompletedProcess(argv, 1, "", ""))
    assert model_catalog.discover_models("antigravity", "fake") == []
