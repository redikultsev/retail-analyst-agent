from retail_agent.chat import FAILED_REPLY, Chat
from retail_agent.policy import Brands
from retail_agent.profile import Profile

BEN = Profile("ben", "Ben Ortiz", "Brand manager", Brands(frozenset({"Diesel"})))


class EchoAgent:
    async def reply(self, message: str) -> str:
        return f"echo: {message}"


class FailsOnceAgent:
    def __init__(self) -> None:
        self._failed = False

    async def reply(self, message: str) -> str:
        if not self._failed:
            self._failed = True
            raise ConnectionError("the model is down")
        return f"echo: {message}"


class FakeTerminal:
    def __init__(self, messages: list[str]) -> None:
        self._messages = iter(messages)
        self.shown: list[str] = []

    def read(self) -> str | None:
        return next(self._messages, None)

    def show(self, text: str) -> None:
        self.shown.append(text)

    def show_reply(self, markdown: str) -> None:
        self.shown.append(markdown)


async def test_greeting_says_who_is_signed_in_and_what_they_see():
    terminal = FakeTerminal([])

    await Chat(EchoAgent(), terminal, BEN).run()

    assert "Ben Ortiz" in terminal.shown[0]
    assert "Diesel" in terminal.shown[0]


async def test_shows_a_reply_for_each_message():
    terminal = FakeTerminal(["monthly revenue", "top products"])

    await Chat(EchoAgent(), terminal, BEN).run()

    assert terminal.shown[1:] == ["echo: monthly revenue", "echo: top products"]


async def test_ends_when_the_executive_leaves():
    terminal = FakeTerminal([])

    await Chat(EchoAgent(), terminal, BEN).run()

    assert len(terminal.shown) == 1


async def test_a_failed_reply_is_shown_as_one_plain_sentence():
    terminal = FakeTerminal(["monthly revenue"])

    await Chat(FailsOnceAgent(), terminal, BEN).run()

    assert terminal.shown[1:] == [FAILED_REPLY]


async def test_chat_goes_on_after_a_failed_reply():
    terminal = FakeTerminal(["monthly revenue", "top products"])

    await Chat(FailsOnceAgent(), terminal, BEN).run()

    assert terminal.shown[2] == "echo: top products"
