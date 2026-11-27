import asyncio
import logging
from typing import Annotated, NoReturn

import typer

from retail_agent.config import ConfigError, Settings, load_settings
from retail_agent.di import build_chat, build_console, build_profile_repository, build_warehouse
from retail_agent.policy import Brands, describe
from retail_agent.profile import Profile
from retail_agent.profile_repository import ProfileError
from retail_agent.sql_report import print_outcome
from retail_agent.startup_check import WarehouseNotReady, verify
from retail_agent.warehouse import Refused, Warehouse

app = typer.Typer(no_args_is_help=True, add_completion=False)
User = Annotated[str, typer.Option("--user", help="Who is asking. See 'retail-agent users'.")]
LOG_FILE = "retail_agent.log"
SETUP_HINT = "Check GOOGLE_CLOUD_PROJECT and your Google credentials."
Query = Annotated[str, typer.Argument(help="SQL to run under the rules of that user.")]


@app.callback()
def main() -> None:
    """Chat agent that answers retail analysis questions with safe BigQuery SQL."""


@app.command()
def chat(user: User) -> None:
    """Start an interactive chat session."""
    settings = _settings()
    profile = _profile(settings, user)
    _log_to_file(settings)
    warehouse = build_warehouse(settings, profile)
    missing = _missing_brands(warehouse)
    if missing:
        typer.echo(f"Warning: brands not found in the data: {describe(Brands(missing))}.")
    asyncio.run(build_chat(settings, profile, warehouse).run())


@app.command()
def sql(query: Query, user: User) -> None:
    """Run one query through the same checks the agent uses and show what happened."""
    settings = _settings()
    profile = _profile(settings, user)
    _log_to_file(settings)
    outcome = asyncio.run(build_warehouse(settings, profile).run(query))
    print_outcome(build_console(), outcome, profile.scope)
    if isinstance(outcome, Refused):
        raise typer.Exit(code=1)


@app.command()
def users() -> None:
    """List the people who can use the agent and the brands each of them sees."""
    try:
        profiles = build_profile_repository(_settings()).all()
    except ProfileError as error:
        _fail(str(error))
    for profile in profiles:
        typer.echo(f"{profile.key:<8}{profile.name}, {profile.role}: {describe(profile.scope)}")


def _settings() -> Settings:
    try:
        return load_settings()
    except ConfigError as error:
        _fail(f"{error}. See .env.example.")


def _profile(settings: Settings, user: str) -> Profile:
    try:
        return build_profile_repository(settings).get(user)
    except ProfileError as error:
        _fail(str(error))


def _log_to_file(settings: Settings) -> None:
    logging.basicConfig(
        filename=settings.data_dir / LOG_FILE,
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _missing_brands(warehouse: Warehouse) -> frozenset[str]:
    typer.echo("Checking access to the data...")
    try:
        return asyncio.run(verify(warehouse))
    except WarehouseNotReady as error:
        _fail(f"{error} {SETUP_HINT}" if error.unreachable else str(error))


def _fail(text: str) -> NoReturn:
    typer.echo(text, err=True)
    raise typer.Exit(code=2)
