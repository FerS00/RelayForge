from fastapi.testclient import TestClient


def test_security_headers_and_origin(client: TestClient):
    response = client.get("/")
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "form-action 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    forbidden = client.post("/api/conversations", json={}, headers={"Origin": "https://evil.invalid"})
    assert forbidden.status_code == 403
