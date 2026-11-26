from retail_agent.chat import Chat
from retail_agent.policy import Brands
from retail_agent.profile import Profile

BEN = Profile("ben", "Ben Ortiz", "Brand manager", Brands(frozenset({"Diesel"})))


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


def test_greeting_says_who_is_signed_in_and_what_they_see():
    terminal = FakeTerminal([])

    Chat(EchoAgent(), terminal, BEN).run()

    assert "Ben Ortiz" in terminal.shown[0]
    assert "Diesel" in terminal.shown[0]


def test_shows_a_reply_for_each_message():
    terminal = FakeTerminal(["monthly revenue", "top products"])

    Chat(EchoAgent(), terminal, BEN).run()

    assert terminal.shown[1:] == ["echo: monthly revenue", "echo: top products"]


def test_ends_when_the_executive_leaves():
    terminal = FakeTerminal([])

    Chat(EchoAgent(), terminal, BEN).run()

    assert len(terminal.shown) == 1
