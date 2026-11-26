from rich.console import Console

PROMPT = "[bold cyan]>[/] "
EXIT_WORDS = frozenset({"exit", "quit"})


class RichTerminal:
    def __init__(self, console: Console) -> None:
        self._console = console

    def read(self) -> str | None:
        while (line := self._read_line()) is not None:
            message = line.strip()
            if message.lower() in EXIT_WORDS:
                return None
            if message:
                return message
        return None

    def show(self, text: str) -> None:
        self._console.print(text, markup=False, highlight=False)

    def _read_line(self) -> str | None:
        try:
            return self._console.input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            self._console.print()
            return None
