import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_google_genai import ChatGoogleGenerativeAI
from langfuse import Langfuse
from rich.console import Console

from retail_agent.adapters.bigquery_executor import BigQueryExecutor
from retail_agent.adapters.langfuse_tracing import (
    CleanCallbackHandler,
    LangfuseTracer,
    NoTracer,
    cleaner,
    start_local_langfuse,
)
from retail_agent.adapters.profile_repository import ProfileRepository
from retail_agent.adapters.report_repository import ReportRepository
from retail_agent.agent.langchain_agent import LangChainAgent
from retail_agent.agent.prompt import system_prompt
from retail_agent.agent.report_tools import DELETE_REPORTS, report_tools
from retail_agent.agent.sql_tool import RUN_SQL, sql_tool
from retail_agent.app.chat import Chat
from retail_agent.app.terminal import RichTerminal
from retail_agent.config import Settings
from retail_agent.domain.policy import Policy
from retail_agent.domain.profile import Profile
from retail_agent.domain.report import ReportLibrary
from retail_agent.query.warehouse import Warehouse

logger = logging.getLogger(__name__)

LOCAL_LANGFUSE_DATABASE = "langfuse.db"
MODEL_RETRIES = 2
MODEL_TIMEOUT_S = 60


def build_profile_repository(settings: Settings) -> ProfileRepository:
    return ProfileRepository(_database(settings))


def build_console() -> Console:
    return Console()


def build_chat(settings: Settings, profile: Profile, warehouse: Warehouse) -> Chat:
    conversation_id = str(uuid4())
    reports = ReportRepository(_database(settings))
    # The tracer comes last: it may start a local process, and nothing after it may fail.
    tracer = build_tracer(settings, profile.key, conversation_id)
    agent = build_agent(settings, profile, warehouse, reports, conversation_id, tracer.callbacks())
    return Chat(agent, RichTerminal(build_console()), profile, tracer)


def build_agent(
    settings: Settings,
    profile: Profile,
    warehouse: Warehouse,
    reports: ReportLibrary,
    conversation_id: str,
    callbacks: Sequence[BaseCallbackHandler],
) -> LangChainAgent:
    return LangChainAgent(
        _build_model(settings, settings.gemini_model),
        _build_model(settings, settings.gemini_fallback_model),
        [sql_tool(warehouse), *report_tools(reports, profile.key, conversation_id)],
        system_prompt(profile, date.today()),
        max_model_calls=settings.agent_max_model_calls,
        max_tool_calls={RUN_SQL: settings.agent_max_queries, DELETE_REPORTS: 1},
        timeout_s=settings.agent_timeout_s,
        callbacks=callbacks,
    )


def build_tracer(settings: Settings, user: str, conversation_id: str) -> LangfuseTracer | NoTracer:
    """With Langfuse keys traces go to that Langfuse, without them to a local one on SQLite."""
    local = None
    try:
        if settings.langfuse_public_key and settings.langfuse_secret_key:
            public_key = settings.langfuse_public_key
            secret_key = settings.langfuse_secret_key.get_secret_value()
            host = settings.langfuse_host
        else:
            local = start_local_langfuse(local_langfuse_database(settings))
            public_key = local.env["LANGFUSE_PUBLIC_KEY"]
            secret_key = local.env["LANGFUSE_SECRET_KEY"]
            host = local.url
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=host,
            mask_otel_spans=cleaner(settings.secrets),
        )
        handler = CleanCallbackHandler(public_key, settings.secrets)
    except Exception:
        logger.exception("tracing could not be set up")
        if local:
            local.stop()
        return NoTracer()
    return LangfuseTracer(client, handler, user, conversation_id, local)


def local_langfuse_database(settings: Settings) -> Path:
    return settings.data_dir / LOCAL_LANGFUSE_DATABASE


def build_warehouse(settings: Settings, profile: Profile) -> Warehouse:
    executor = BigQueryExecutor(
        settings.google_cloud_project,
        max_bytes_billed=settings.query_max_bytes,
        timeout_s=settings.query_timeout_s,
    )
    return Warehouse(
        executor,
        Policy(scope=profile.scope, row_limit=settings.result_max_rows),
        max_bytes=settings.query_max_bytes,
        max_result_chars=settings.result_max_chars,
        secrets=settings.secrets,
    )


def _database(settings: Settings) -> Path:
    return settings.data_dir / "retail_agent.db"


def _build_model(settings: Settings, name: str) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=name,
        api_key=settings.google_api_key,
        max_retries=MODEL_RETRIES,
        timeout=MODEL_TIMEOUT_S,
    )
