import base64
import io
import time

from PIL import Image


def conversation(client):
    return client.post("/api/conversations", json={"agent": "codex"}).json()["id"]


def upload(client, identifier, name, content):
    return client.post(
        f"/api/conversations/{identifier}/attachments",
        json={"name": name, "data_base64": base64.b64encode(content).decode()},
    )


def test_attachment_send_ownership_download_and_idempotency(client, app):
    identifier = conversation(client)
    uploaded = upload(client, identifier, "evidence.log", b"hola FARO evidencia")
    assert uploaded.status_code == 201
    row = uploaded.json()
    url = f"/api/conversations/{identifier}/messages"
    body = {"content": "Revisa", "attachment_ids": [row["id"]]}
    response = client.post(url, json=body, headers={"Idempotency-Key": "evidence"})
    assert response.status_code == 202
    deadline = time.monotonic() + 8
    while app.state.chat.active and time.monotonic() < deadline:
        time.sleep(0.02)
    messages = client.get(url).json()["messages"]
    assert messages[0]["attachments"][0]["id"] == row["id"]
    assert messages[-1]["content"] == "Evidencia recibida"
    assert client.post(url, json=body, headers={"Idempotency-Key": "evidence"}).status_code == 200
    assert client.post(url, json=body, headers={"Idempotency-Key": "another"}).status_code == 422
    download = client.get(f"/api/conversations/{identifier}/attachments/{row['id']}/content")
    assert (
        download.content == b"hola FARO evidencia" and download.headers["x-content-type-options"] == "nosniff"
    )
    assert "attachment" in download.headers["content-disposition"]
    other = conversation(client)
    assert client.get(f"/api/conversations/{other}/attachments/{row['id']}").status_code == 404
    assert (
        client.post(
            f"/api/conversations/{other}/messages", json=body, headers={"Idempotency-Key": "wrong"}
        ).status_code
        == 422
    )


def test_image_upload_and_preview_is_validated(client):
    identifier = conversation(client)
    output = io.BytesIO()
    Image.new("RGB", (2, 2)).save(output, format="PNG")
    row = upload(client, identifier, "capture.png", output.getvalue()).json()
    preview = client.get(f"/api/conversations/{identifier}/attachments/{row['id']}/content")
    assert preview.headers["content-type"] == "image/png"
    assert "inline" in preview.headers["content-disposition"]
    assert upload(client, identifier, "fake.png", b"not an image").status_code == 422


def test_invalid_upload_has_no_file_or_database_row(client, app):
    identifier = conversation(client)
    for name, content in [
        ("../../evil.txt", b"text"),
        ("evil.svg", b"<svg/>"),
        ("evil.exe", b"binary"),
        ("empty.txt", b""),
    ]:
        assert upload(client, identifier, name, content).status_code in {413, 422}
    with app.state.engine.connect() as db:
        assert db.exec_driver_sql("SELECT count(*) FROM attachments").scalar() == 0
    assert not app.state.attachments.storage.exists()


def test_attachment_integrity_tampering_blocks_send(client, app):
    identifier = conversation(client)
    row = upload(client, identifier, "test.txt", b"evidence").json()
    (app.state.attachments.storage / row["id"]).write_bytes(b"changed")
    response = client.post(
        f"/api/conversations/{identifier}/messages",
        json={"attachment_ids": [row["id"]]},
        headers={"Idempotency-Key": "tamper"},
    )
    assert response.status_code == 422 and not app.state.chat.active
