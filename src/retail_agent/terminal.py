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
        print_plain(self._console, text)

    def _read_line(self) -> str | None:
        try:
            return self._console.input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            self._console.print()
            return None


def print_plain(console: Console, text: str, *, soft_wrap: bool = False) -> None:
    console.print(text, markup=False, highlight=False, soft_wrap=soft_wrap)
