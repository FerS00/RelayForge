from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import uvicorn


def start_server(app, sock: socket.socket) -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(
        app, host="127.0.0.1", port=sock.getsockname()[1], log_level="error", lifespan="off"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    return server, thread


def free_socket() -> tuple[socket.socket, int]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    return sock, sock.getsockname()[1]


@contextmanager
def stream_when_ready(url: str, timeout: httpx.Timeout) -> Iterator[httpx.Response]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        manager = httpx.stream("GET", url, timeout=timeout)
        try:
            response = manager.__enter__()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            time.sleep(0.05)
            continue
        try:
            yield response
        finally:
            manager.__exit__(None, None, None)
        return
    raise AssertionError("Uvicorn no aceptó conexiones a tiempo.")


def assert_message_deltas(events: list[dict[str, object]], expected: list[str]) -> None:
    messages = [(index, event) for index, event in enumerate(events) if event["type"] == "agent.message"]
    assert [event["data"]["text"] for _, event in messages] == expected
    for message_index, message in messages:
        message_id = message["data"]["message_id"]
        deltas = [
            (index, event)
            for index, event in enumerate(events)
            if event["type"] == "agent.message.delta" and event["data"]["message_id"] == message_id
        ]
        assert deltas
        assert max(index for index, _ in deltas) < message_index
        assert "".join(event["data"]["text"] for _, event in deltas) == message["data"]["text"]


def test_uvicorn_stream_delivers_saved_events(app, client, monkeypatch):
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "two_messages")
    conversation = client.post("/api/conversations", json={}).json()
    sock, port = free_socket()
    server, thread = start_server(app, sock)
    timeout = httpx.Timeout(connect=1, read=10, write=5, pool=5)
    url = f"http://127.0.0.1:{port}/api/stream?conversation={conversation['id']}"
    try:
        with stream_when_ready(url, timeout) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            httpx.post(
                f"http://127.0.0.1:{port}/api/conversations/{conversation['id']}/messages",
                json={"content": "sse"},
                headers={"Idempotency-Key": "sse-1"},
                timeout=timeout,
            )
            blocks = []
            for line in lines:
                if line.startswith("data: "):
                    blocks.append(json.loads(line[6:]))
                if any(event["type"] == "step.finished" for event in blocks):
                    break
            assert [event["type"] for event in blocks][0] == "step.started"
            assert blocks[-1]["type"] == "step.finished"
            assert all(event["seq"] > 0 for event in blocks)
            deltas = [event for event in blocks if event["type"] == "agent.message.delta"]
            assert len(deltas) >= 2
            assert_message_deltas(blocks, ["first response", "second response"])
            second = httpx.post(
                f"http://127.0.0.1:{port}/api/conversations/{conversation['id']}/messages",
                json={"content": "second"},
                headers={"Idempotency-Key": "sse-2"},
                timeout=timeout,
            )
            assert second.status_code == 202
            next_turn = []
            for line in lines:
                if line.startswith("data: "):
                    next_turn.append(json.loads(line[6:]))
                if any(event["type"] == "step.finished" for event in next_turn):
                    break
            assert_message_deltas(next_turn, ["first response", "second response"])
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_agent_messages_reach_sse_within_one_second(app, client, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "two_messages")
    log_path = tmp_path / "fake-agent-log.json"
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log_path))
    conversation = client.post("/api/conversations", json={}).json()
    sock, port = free_socket()
    server, thread = start_server(app, sock)
    timeout = httpx.Timeout(connect=1, read=10, write=5, pool=5)
    url = f"http://127.0.0.1:{port}/api/stream?conversation={conversation['id']}"
    received_messages: list[tuple[str, float]] = []
    try:
        with stream_when_ready(url, timeout) as response:
            assert response.status_code == 200
            posted = httpx.post(
                f"http://127.0.0.1:{port}/api/conversations/{conversation['id']}/messages",
                json={"content": "latency"},
                headers={"Idempotency-Key": "latency-1"},
                timeout=timeout,
            )
            assert posted.status_code == 202
            for line in response.iter_lines():
                received_at = time.time()
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    if event["type"] == "agent.message":
                        received_messages.append((event["data"]["text"], received_at))
                    if event["type"] == "step.finished":
                        break
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert not thread.is_alive()
    records = json.loads(log_path.read_text(encoding="utf-8"))["lines"]
    assistant_writes = [
        (
            "".join(
                block["text"] for block in item["record"]["message"]["content"] if block.get("type") == "text"
            ),
            item["written_at"],
        )
        for item in records
        if item["record"].get("type") == "assistant"
    ]
    assert [text for text, _ in received_messages] == ["first response", "second response"]
    assert [text for text, _ in assistant_writes] == ["first response", "second response"]
    for (written_text, written_at), (received_text, received_at) in zip(
        assistant_writes, received_messages, strict=True
    ):
        assert received_text == written_text
        assert received_at - written_at <= 1.0


def test_stream_subscribes_before_returning_headers(app, client):
    conversation = client.post("/api/conversations", json={}).json()
    sock, port = free_socket()
    server, thread = start_server(app, sock)
    deadline = time.monotonic() + 5
    try:
        while time.monotonic() < deadline:
            try:
                with httpx.stream(
                    "GET",
                    f"http://127.0.0.1:{port}/api/stream?conversation={conversation['id']}",
                    timeout=1,
                ) as response:
                    assert response.status_code == 200
                    posted = httpx.post(
                        f"http://127.0.0.1:{port}/api/conversations/{conversation['id']}/messages",
                        json={"content": "after headers"},
                        headers={"Idempotency-Key": "after-headers"},
                    )
                    assert posted.status_code == 202
                    received = []
                    for line in response.iter_lines():
                        if line.startswith("data: "):
                            received.append(json.loads(line[6:]))
                        if any(event["type"] == "step.finished" for event in received):
                            break
                    assert received[0]["type"] == "step.started"
                    assert received[0]["seq"] == 1
                    assert received[-1]["type"] == "step.finished"
                    return
            except (httpx.ConnectError, httpx.ReadTimeout):
                time.sleep(0.05)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    raise AssertionError("SSE no recibió el evento publicado después de las cabeceras.")
