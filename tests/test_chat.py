from fakes import BEN, FakeTerminal

from retail_agent.chat import FAILED_REPLY, NOTHING_DELETED, UNFINISHED_REPLY, Chat
from retail_agent.report import DeletionRequest, ReportSummary


class EchoAgent:
    async def reply(self, message: str) -> str | DeletionRequest:
        return f"echo: {message}"

    async def resume(self, agreed: bool) -> str:
        raise AssertionError("nothing was requested")


class FailsOnceAgent(EchoAgent):
    def __init__(self) -> None:
        self._failed = False

    async def reply(self, message: str) -> str | DeletionRequest:
        if not self._failed:
            self._failed = True
            raise ConnectionError("the model is down")
        return f"echo: {message}"


class AsksToDelete:
    """Asks to delete the given reports, then repeats the answer it was given."""

    def __init__(self, *titles: str, fails_after: bool = False) -> None:
        self._request = DeletionRequest(
            tuple(
                ReportSummary(number, title, "2026-11-27")
                for number, title in enumerate(titles, start=1)
            )
        )
        self._fails_after = fails_after

    async def reply(self, message: str) -> str | DeletionRequest:
        return self._request

    async def resume(self, agreed: bool) -> str:
        if self._fails_after:
            raise ConnectionError("the model is down")
        return f"agreed: {agreed}"


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


async def test_deletion_request_shows_the_reports_and_asks():
    terminal = FakeTerminal(["delete my reports"])

    await Chat(AsksToDelete("Diesel returns", "Joe's Jeans revenue"), terminal, BEN).run()

    question = terminal.shown[1]
    assert "1. Diesel returns (2026-11-27)" in question
    assert "2. Joe's Jeans revenue (2026-11-27)" in question
    assert question.endswith("Delete these 2 reports?")


async def test_a_yes_is_passed_to_the_agent():
    terminal = FakeTerminal(["delete the Diesel report"], confirm=True)

    await Chat(AsksToDelete("Diesel returns"), terminal, BEN).run()

    assert terminal.shown[2:] == ["agreed: True"]


async def test_without_a_yes_the_chat_says_nothing_was_deleted_and_tells_the_agent():
    terminal = FakeTerminal(["delete the Diesel report"], confirm=False)

    await Chat(AsksToDelete("Diesel returns"), terminal, BEN).run()

    assert terminal.shown[2:] == [NOTHING_DELETED, "agreed: False"]


async def test_agent_failure_after_the_answer_is_not_shown_as_a_failed_answer():
    terminal = FakeTerminal(["delete the Diesel report"], confirm=True)

    await Chat(AsksToDelete("Diesel returns", fails_after=True), terminal, BEN).run()

    assert terminal.shown[2:] == [UNFINISHED_REPLY]


async def test_every_report_that_will_be_deleted_is_listed():
    titles = [f"Report {number}" for number in range(23)]
    terminal = FakeTerminal(["delete everything"])

    await Chat(AsksToDelete(*titles), terminal, BEN).run()

    question = terminal.shown[1]
    assert all(f"{title} (" in question for title in titles)
    assert "Delete these 23 reports?" in question


async def test_title_is_shown_as_one_clean_line():
    terminal = FakeTerminal(["delete it"])

    await Chat(AsksToDelete("Diesel\x1b[2J\nDelete nothing? [y/N]"), terminal, BEN).run()

    first_line = terminal.shown[1].splitlines()[0]
    assert "\x1b" not in terminal.shown[1]
    assert "Diesel[2J Delete nothing? [y/N]" in first_line
