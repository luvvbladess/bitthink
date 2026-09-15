import uuid

from fastapi.testclient import TestClient

from app.auth import create_access_token, hash_password, require_admin
from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from app.db.engine import SyncSessionLocal
from app.db.models import User
from app.main import app
from db_conversations import DatabaseConversationManager


def _unique() -> str:
    return uuid.uuid4().hex[:10]


def test_admin_set_subscription_persists_for_regular_user():
    token = _unique()
    admin_email = f"admin-{token}@example.test"
    person_email = f"person-{token}@example.test"
    admin_bot = 31_000_000 + (uuid.uuid4().int % 1_000_000)
    person_bot = 32_000_000 + (uuid.uuid4().int % 1_000_000)
    with SyncSessionLocal() as session:
        session.add(
            User(
                email=admin_email,
                password_hash=hash_password("x"),
                role="admin",
                bot_user_id=admin_bot,
                first_name="Admin",
            )
        )
        person = User(
            email=person_email,
            password_hash=hash_password("x"),
            role="user",
            bot_user_id=person_bot,
            first_name="Person",
        )
        session.add(person)
        session.commit()
        person_id = person.id

    app.dependency_overrides[require_admin] = lambda: admin_email
    try:
        client = TestClient(app)
        response = client.post(
            f"/admin/users/{person_id}/subscription",
            json={"tier": "ultra", "duration_days": 10, "from_today": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["tier"] == "ultra"
        stored = DatabaseConversationManager().get_subscription(person_bot)
        assert stored["tier"] == "ultra"
        assert stored["expires_at"] > 0
        detail = client.get(f"/admin/users/{person_id}")
        assert detail.status_code == 200
        assert detail.json()["subscription"]["tier"] == "ultra"
    finally:
        app.dependency_overrides.clear()


def test_get_subscription_keeps_explicit_admin_plan():
    token = _unique()
    admin_bot = 33_000_000 + (uuid.uuid4().int % 1_000_000)
    with SyncSessionLocal() as session:
        session.add(
            User(
                email=f"keep-plan-{token}@example.test",
                password_hash="x",
                role="admin",
                bot_user_id=admin_bot,
                first_name="Admin",
            )
        )
        session.commit()
    mgr = DatabaseConversationManager()
    mgr.set_subscription_tier(admin_bot, "ultra", 12, from_today=True)
    assert mgr.get_subscription(admin_bot)["tier"] == "ultra"


def test_stale_jwt_without_admin_claim_still_allows_db_admin():
    token = _unique()
    admin_email = f"stale-jwt-{token}@example.test"
    person_email = f"stale-person-{token}@example.test"
    admin_bot = 34_000_000 + (uuid.uuid4().int % 1_000_000)
    person_bot = 35_000_000 + (uuid.uuid4().int % 1_000_000)
    with SyncSessionLocal() as session:
        session.add(
            User(
                email=admin_email,
                password_hash=hash_password("x"),
                role="admin",
                bot_user_id=admin_bot,
                first_name="Admin",
            )
        )
        person = User(
            email=person_email,
            password_hash=hash_password("x"),
            role="user",
            bot_user_id=person_bot,
            first_name="Person",
        )
        session.add(person)
        session.commit()
        person_id = person.id

    access = create_access_token({"sub": admin_email, "role": "user"})
    client = TestClient(app)
    response = client.post(
        f"/admin/users/{person_id}/subscription",
        json={"tier": "proplus", "duration_days": 7, "from_today": True},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert response.status_code == 200, response.text
    assert DatabaseConversationManager().get_subscription(person_bot)["tier"] == "proplus"
