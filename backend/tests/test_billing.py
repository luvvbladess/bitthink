from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app


def test_payment_is_coming_soon():
    app.dependency_overrides[get_current_user] = lambda: "tester@example.com"
    try:
        client = TestClient(app)
        for plan in ("pro", "proplus", "ultra"):
            response = client.post(f"/billing/payment/{plan}")
            assert response.status_code == 503
            assert "скоро" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_unknown_plan_is_bad_request():
    app.dependency_overrides[get_current_user] = lambda: "tester@example.com"
    try:
        client = TestClient(app)
        response = client.post("/billing/payment/not-a-plan")
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()
