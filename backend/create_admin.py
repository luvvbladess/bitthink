"""CLI script to create an admin user."""

import asyncio
import sys

from sqlalchemy import select

from app.auth import hash_password
from app.db.engine import AsyncSessionLocal
from app.db.models import User


def _bot_user_id(email: str) -> int:
    import hashlib
    digest = hashlib.sha256(email.encode()).hexdigest()
    return 1_000_000_000 + (int(digest[:12], 16) % 1_000_000_000)


async def main():
    if len(sys.argv) < 3:
        print("Usage: python create_admin.py <email> <password>")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.role = "admin"
            user.password_hash = hash_password(password)
            print(f"Updated existing user {email} to admin")
        else:
            user = User(
                email=email,
                password_hash=hash_password(password),
                first_name=email.split("@")[0],
                role="admin",
                bot_user_id=_bot_user_id(email),
            )
            session.add(user)
            print(f"Created admin user {email}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
