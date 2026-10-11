from pathlib import Path

import pytest

from relayforge.adapters.base import RunSpec
from relayforge.adapters.claude.adapter import ClaudeAdapter
from relayforge.adapters.codex.adapter import CodexAdapter, CodexRunSpec
from relayforge.core.conversation_settings import (
    DEFAULT_TOOLS_JSON,
    EFFORTS,
    ConversationSettingsError,
    ToolPolicy,
    load_tools,
    merge_tools,
    supported_efforts,
    tool_disabled,
)
from relayforge.db import models


def test_default_policy_matches_previous_behavior_and_orm_literal() -> None:
    policy = ToolPolicy()
    assert policy.write_files and policy.commands and policy.git_local and policy.preview
    assert not policy.web_search and not policy.remote_delivery
    assert models.DEFAULT_TOOLS_JSON == DEFAULT_TOOLS_JSON
    assert load_tools("{}") == policy and load_tools(None) == policy and load_tools("not json") == policy


def test_merge_rejects_unknown_keys_non_booleans_and_dependency() -> None:
    for change in ({"shell": True}, {"commands": "yes"}):
        with pytest.raises(ConversationSettingsError, match="tools_invalid"):
            merge_tools(ToolPolicy(), change)
    with pytest.raises(ConversationSettingsError, match="tool_dependency"):
        merge_tools(ToolPolicy(), {"git_local": False, "remote_delivery": True})
    assert merge_tools(ToolPolicy(), {"commands": False}).commands is False


def test_tool_disabled_maps_actions_and_keeps_reads_always_available() -> None:
    policy = ToolPolicy(write_files=False, preview=False)
    assert tool_disabled(policy, "write_file") == "write_files"
    assert tool_disabled(policy, "start_preview") == "preview"
    assert tool_disabled(policy, "read_file") is None and tool_disabled(policy, "list_directory") is None
    assert tool_disabled(policy, "native_task") is None


def test_supported_efforts_use_codex_catalog_and_never_ultra() -> None:
    catalog = {"gpt-small": ("low", "medium", "ultra"), "gpt-empty": ()}
    assert supported_efforts("codex", "gpt-small", catalog) == ("low", "medium")
    assert supported_efforts("codex", "unknown", catalog) == EFFORTS
    assert supported_efforts("codex", "gpt-empty", catalog) == EFFORTS
    assert supported_efforts("claude", "", catalog) == EFFORTS
    assert supported_efforts("antigravity", "", catalog) == ()
    assert "ultra" not in EFFORTS


def test_codex_argv_has_separate_effort_and_global_search_flag() -> None:
    adapter = CodexAdapter("codex")
    plan = adapter.build_run(CodexRunSpec(Path("."), "hola", None, reasoning_effort="high", web_search=True))
    argv = list(plan.argv)
    assert argv[:3] == ["codex", "--search", "exec"]
    index = argv.index("model_reasoning_effort='high'")
    assert argv[index - 1] == "-c"
    resumed = list(
        adapter.build_run(
            CodexRunSpec(Path("."), "hola", None, resume_thread_id="thread-1", web_search=True)
        ).argv
    )
    assert resumed[:2] == ["codex", "--search"] and resumed.index("--search") < resumed.index("exec")
    plain = list(adapter.build_run(CodexRunSpec(Path("."), "hola", None)).argv)
    assert "--search" not in plain
    with pytest.raises(ValueError):
        adapter.build_run(CodexRunSpec(Path("."), "hola", None, reasoning_effort="ultra"))


def test_claude_argv_effort_and_web_tools_follow_chat_policy() -> None:
    adapter = ClaudeAdapter("claude")
    argv = list(
        adapter.build_run(RunSpec("s", False, Path("."), "hola", effort="max", web_search=False)).argv
    )
    assert argv[argv.index("--effort") + 1] == "max"
    assert "WebSearch" in argv and "WebFetch" in argv
    allowed = list(adapter.build_run(RunSpec("s", False, Path("."), "hola", web_search=True)).argv)
    assert "WebSearch" not in allowed and "--effort" not in allowed
    legacy = list(adapter.build_run(RunSpec("s", False, Path("."), "hola")).argv)
    assert "WebSearch" not in legacy
    with pytest.raises(ValueError):
        adapter.build_run(RunSpec("s", False, Path("."), "hola", effort="ultra"))
