from datetime import date
from pathlib import Path
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI
from rich.console import Console

from retail_agent.adapters.bigquery_executor import BigQueryExecutor
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

MODEL_RETRIES = 2
MODEL_TIMEOUT_S = 60


def build_profile_repository(settings: Settings) -> ProfileRepository:
    return ProfileRepository(_database(settings))


def build_console() -> Console:
    return Console()


def build_chat(settings: Settings, profile: Profile, warehouse: Warehouse) -> Chat:
    reports = ReportRepository(_database(settings))
    agent = build_agent(settings, profile, warehouse, reports)
    return Chat(agent, RichTerminal(build_console()), profile)


def build_agent(
    settings: Settings, profile: Profile, warehouse: Warehouse, reports: ReportLibrary
) -> LangChainAgent:
    conversation_id = str(uuid4())
    return LangChainAgent(
        _build_model(settings, settings.gemini_model),
        _build_model(settings, settings.gemini_fallback_model),
        [sql_tool(warehouse), *report_tools(reports, profile.key, conversation_id)],
        system_prompt(profile, date.today()),
        max_model_calls=settings.agent_max_model_calls,
        max_tool_calls={RUN_SQL: settings.agent_max_queries, DELETE_REPORTS: 1},
        timeout_s=settings.agent_timeout_s,
    )


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
        secrets=(settings.google_cloud_project, settings.google_api_key.get_secret_value()),
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
