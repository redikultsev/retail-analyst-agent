import pytest

from retail_agent.adapters.report_repository import ReportRepository

VARIABLES = (
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "DATA_DIR",
    "QUERY_MAX_BYTES",
    "QUERY_TIMEOUT_S",
    "RESULT_MAX_CHARS",
    "RESULT_MAX_ROWS",
    "GEMINI_MODEL",
    "GEMINI_FALLBACK_MODEL",
    "AGENT_MAX_MODEL_CALLS",
    "AGENT_MAX_QUERIES",
    "AGENT_TIMEOUT_S",
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


@pytest.fixture
def reports(tmp_path) -> ReportRepository:
    return ReportRepository(tmp_path / "retail_agent.db")
