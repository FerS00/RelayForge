"""Herramienta MCP para esperar una decisión humana persistida en RelayForge."""

from __future__ import annotations

import json
import os
import time

import httpx
from mcp.server.mcpserver import MCPServer

server = MCPServer(name="rfperm")


@server.tool(structured_output=False)
def approval_prompt(tool_name: str, input: dict, tool_use_id: str | None = None) -> str:
    base = os.environ.get("RELAYFORGE_API", "http://127.0.0.1:8793").rstrip("/")
    try:
        response = httpx.post(f"{base}/permission", json={"tool_name": tool_name, "input": input}, timeout=10)
        response.raise_for_status()
        request_id = response.json()["id"]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            result = httpx.get(f"{base}/permission/{request_id}", timeout=10)
            result.raise_for_status()
            data = result.json()
            if data.get("status") == "decided":
                if data.get("decision") == "allow":
                    return json.dumps({"behavior": "allow", "updatedInput": input}, ensure_ascii=False)
                return json.dumps({"behavior": "deny", "message": "Rejected by RelayForge"})
            time.sleep(0.5)
    except (httpx.HTTPError, KeyError, ValueError):
        return json.dumps({"behavior": "deny", "message": "Rejected by RelayForge"})
    return json.dumps({"behavior": "deny", "message": "Rejected by RelayForge"})


if __name__ == "__main__":
    server.run("stdio")
