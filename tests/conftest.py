import pytest
from langfuse._client.resource_manager import LangfuseResourceManager
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

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


@pytest.fixture(autouse=True)
def fresh_langfuse():
    # Langfuse keeps one client per key for the whole process. Each test needs its own,
    # because each test writes traces to its own folder.
    yield
    LangfuseResourceManager.reset()
    # reset() leaves the old client's exporter on the shared provider, still aimed at a
    # local Langfuse that has stopped. The next test would wait on it.
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()
