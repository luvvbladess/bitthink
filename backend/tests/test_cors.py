from app.config import Settings


def test_cors_from_csv():
    settings = Settings(CORS_ORIGINS="https://app.example.com, http://localhost:5173")
    assert settings.CORS_ORIGINS == ["https://app.example.com", "http://localhost:5173"]


def test_cors_from_json_list():
    settings = Settings(CORS_ORIGINS='["https://a.test","https://b.test"]')
    assert settings.CORS_ORIGINS == ["https://a.test", "https://b.test"]
