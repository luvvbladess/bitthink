from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app


def test_image_quality_defaults_to_high_and_can_be_changed():
    app.dependency_overrides[get_current_user] = lambda: "image-quality-user@example.com"
    try:
        client = TestClient(app)
        listed = client.get("/models")
        assert listed.status_code == 200, listed.text
        # Nobody chose yet: pictures are drawn at the highest quality, as they always were.
        assert listed.json()["imageQuality"] == "high"
        assert listed.json()["imageQualities"] == ["low", "medium", "high"]

        changed = client.post("/models/image-quality", json={"quality": "low"})
        assert changed.status_code == 200, changed.text
        assert client.get("/models").json()["imageQuality"] == "low"

        client.post("/models/image-quality", json={"quality": "medium"})
        assert client.get("/models").json()["imageQuality"] == "medium"
    finally:
        app.dependency_overrides.clear()


def test_unknown_image_quality_is_rejected_and_changes_nothing():
    app.dependency_overrides[get_current_user] = lambda: "image-quality-user2@example.com"
    try:
        client = TestClient(app)
        for bad in ("ultra", "", None, 3, "auto"):
            response = client.post("/models/image-quality", json={"quality": bad})
            assert response.status_code == 400, (bad, response.text)
        assert client.get("/models").json()["imageQuality"] == "high"
    finally:
        app.dependency_overrides.clear()


def test_chat_pictures_are_drawn_at_the_chosen_quality(monkeypatch):
    import asyncio

    import openai_client
    import studio_router
    from conversations import conversation_manager

    user_id = 94041
    conversation_manager.set_user_image_quality(user_id, "medium")
    seen = []

    async def fake_generate(prompt, size="auto", quality="auto"):
        seen.append(quality)
        return None, "stop here"

    monkeypatch.setattr(openai_client, "generate_image", fake_generate)
    monkeypatch.setattr(studio_router, "_chat_image_bytes", lambda *_a, **_k: [])
    result = asyncio.run(studio_router.get_image_response([], "Нарисуй рыжего кота на крыше", user_id, None))
    assert result is not None and seen == ["medium"]
