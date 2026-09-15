from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app


def test_connector_secrets_are_not_returned():
    app.dependency_overrides[get_current_user] = lambda: "connector-user@example.com"
    try:
        client = TestClient(app)
        created = client.post(
            "/connectors",
            json={
                "type": "gmail",
                "name": "Рабочая почта",
                "payload": {"email": "me@gmail.com", "app_password": "super-secret-app-pass"},
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["type"] == "gmail"
        assert body["name"] == "Рабочая почта"
        assert "app_password" not in str(body)
        assert "super-secret-app-pass" not in str(body)
        assert "payload" not in body

        listed = client.get("/connectors")
        assert listed.status_code == 200
        items = listed.json()
        assert any(item["id"] == body["id"] for item in items)
        assert "super-secret-app-pass" not in listed.text

        deleted = client.delete(f"/connectors/{body['id']}")
        assert deleted.status_code == 200
        assert client.get("/connectors").json() == []
    finally:
        app.dependency_overrides.clear()


def test_unknown_connector_type_is_rejected():
    app.dependency_overrides[get_current_user] = lambda: "connector-user@example.com"
    try:
        client = TestClient(app)
        response = client.post(
            "/connectors",
            json={"type": "bank", "name": "nope", "payload": {}},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
