import typer
from rich.console import Console

from retail_agent.config import ConfigError, load_settings
from retail_agent.di import build_chat

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Chat agent that answers retail analysis questions with safe BigQuery SQL."""


@app.command()
def chat() -> None:
    """Start an interactive chat session."""
    try:
        settings = load_settings()
    except ConfigError as error:
        Console(stderr=True).print(f"{error}. See .env.example.")
        raise typer.Exit(code=2) from None

    build_chat(settings).run()
