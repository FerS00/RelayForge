from __future__ import annotations

import asyncio
import json
from unittest.mock import Mock

from mcp.types import TextContent
from poc04_mcp_tools import mcp_shim
from poc08_approval import permission_tool


def test_mcp_2_servers_register_tools_without_starting_stdio() -> None:
    relayforge_tools = asyncio.run(mcp_shim.server.list_tools())
    rfperm_tools = asyncio.run(permission_tool.server.list_tools())

    assert {tool.name for tool in relayforge_tools} == {"get_job_status", "propose_job"}
    assert {tool.name for tool in rfperm_tools} == {"approval_prompt"}


def test_approval_prompt_returns_one_text_block_without_structured_content(monkeypatch) -> None:
    post_response = Mock()
    post_response.json.return_value = {"id": "approval-1"}
    get_response = Mock()
    get_response.json.return_value = {"status": "decided", "decision": "allow"}
    monkeypatch.setattr(permission_tool.httpx, "post", Mock(return_value=post_response))
    monkeypatch.setattr(permission_tool.httpx, "get", Mock(return_value=get_response))
    monkeypatch.setattr(permission_tool.time, "sleep", Mock())
    tool_input = {"file_path": "rf-perm-approved.txt", "content": "OK"}

    result = asyncio.run(permission_tool.server.call_tool(
        "approval_prompt", {"tool_name": "Write", "input": tool_input}
    ))

    assert result.structured_content is None
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text) == {
        "behavior": "allow", "updatedInput": tool_input
    }
