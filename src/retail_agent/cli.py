from typing import Annotated, NoReturn

import typer

from retail_agent.config import ConfigError, Settings, load_settings
from retail_agent.di import build_chat, build_profile_repository
from retail_agent.policy import describe
from retail_agent.profile_repository import ProfileError

app = typer.Typer(no_args_is_help=True, add_completion=False)
User = Annotated[str, typer.Option("--user", help="Who is asking. See 'retail-agent users'.")]


@app.callback()
def main() -> None:
    """Chat agent that answers retail analysis questions with safe BigQuery SQL."""


@app.command()
def chat(user: User) -> None:
    """Start an interactive chat session."""
    settings = _settings()
    try:
        profile = build_profile_repository(settings).get(user)
    except ProfileError as error:
        _fail(str(error))
    build_chat(settings, profile).run()


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


def _fail(text: str) -> NoReturn:
    typer.echo(text, err=True)
    raise typer.Exit(code=2)
