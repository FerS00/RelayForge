from fastapi.testclient import TestClient


def test_security_headers_and_origin(client: TestClient):
    response = client.get("/")
    assert response.headers["content-security-policy"] == "default-src 'self'"
    forbidden = client.post("/api/conversations", json={}, headers={"Origin": "https://evil.invalid"})
    assert forbidden.status_code == 403
