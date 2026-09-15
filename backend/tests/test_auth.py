import hashlib

from app.auth import hash_password, is_legacy_hash, verify_password


def test_bcrypt_roundtrip():
    hashed = hash_password("secret123")
    assert hashed.startswith("$2")
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)
    assert not is_legacy_hash(hashed)


def test_legacy_sha256_still_verifies():
    salt = "abc123"
    digest = hashlib.sha256(("secret123" + salt).encode()).hexdigest()
    hashed = f"{salt}:{digest}"
    assert is_legacy_hash(hashed)
    assert verify_password("secret123", hashed)
    assert not verify_password("nope", hashed)
