from retail_agent.chat import GREETING, Chat


class EchoAgent:
    def reply(self, message: str) -> str:
        return f"echo: {message}"


class FakeTerminal:
    def __init__(self, messages: list[str]) -> None:
        self._messages = iter(messages)
        self.shown: list[str] = []

    def read(self) -> str | None:
        return next(self._messages, None)

    def show(self, text: str) -> None:
        self.shown.append(text)


def test_greets_then_shows_a_reply_for_each_message():
    terminal = FakeTerminal(["monthly revenue", "top products"])

    Chat(EchoAgent(), terminal).run()

    assert terminal.shown == [GREETING, "echo: monthly revenue", "echo: top products"]


def test_ends_when_the_executive_leaves():
    terminal = FakeTerminal([])

    Chat(EchoAgent(), terminal).run()

    assert terminal.shown == [GREETING]
