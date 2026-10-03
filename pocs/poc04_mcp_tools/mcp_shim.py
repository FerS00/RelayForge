"""Puente MCP stdio hacia la API autenticada de RelayForge."""

from __future__ import annotations

import json
import os

import httpx
from mcp.server.mcpserver import MCPServer

server = MCPServer(name="relayforge")


def _post(path: str, payload: dict) -> str:
    base = os.environ.get("RELAYFORGE_API", "http://127.0.0.1:8791").rstrip("/")
    token = os.environ.get("RELAYFORGE_JOB_TOKEN", "")
    try:
        response = httpx.post(f"{base}{path}", json=payload,
                              headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except httpx.HTTPError:
        return json.dumps({"error": 503})
    if not response.is_success:
        return json.dumps({"error": response.status_code})
    return json.dumps(response.json(), ensure_ascii=False)


@server.tool(structured_output=False)
def get_job_status(job_id: str) -> str:
    return _post("/internal/mcp/get_job_status", {"job_id": job_id})


@server.tool(structured_output=False)
def propose_job(repo: str, title: str, request: str) -> str:
    return _post("/internal/mcp/propose_job", {"repo": repo, "title": title, "request": request})


if __name__ == "__main__":
    server.run("stdio")
