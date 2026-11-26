import pytest

VARIABLES = (
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "DATA_DIR",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def required_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "acme-analytics")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
