import json

import pytest
from fakes import BEN, FakeTerminal, ScriptedModel, tool_call, tool_calls
from langchain_core.messages import AIMessage

from retail_agent.agent.langchain_agent import LangChainAgent
from retail_agent.agent.report_tools import DELETE_REPORTS, report_tools
from retail_agent.app.chat import Chat
from retail_agent.domain.report import DeletionRequest, Report, ReportSummary


def agent(model, reports) -> LangChainAgent:
    return LangChainAgent(
        model,
        ScriptedModel([]),
        report_tools(reports, "ben", "talk-1"),
        "You are a retail analyst.",
        max_model_calls=10,
        max_tool_calls={DELETE_REPORTS: 1},
        timeout_s=5.0,
    )


def delete_call(ids, number=0) -> AIMessage:
    return tool_call("delete_reports", {"ids": ids}, number)


def summary(report: Report) -> ReportSummary:
    return ReportSummary(report.id, report.title, report.created_at.date().isoformat())


def last_tool_result(model) -> dict:
    return json.loads(model.seen[-1].splitlines()[-1])


async def test_report_is_saved_for_the_person_and_the_conversation_of_the_session(reports) -> None:
    save = tool_call("save_report", {"title": "Diesel returns", "body": "## Summary"})
    model = ScriptedModel([save, AIMessage("Saved.")])

    await agent(model, reports).reply("save this as a report")

    [saved] = reports.find("ben", conversation_id="talk-1")
    assert (saved.title, saved.body) == ("Diesel returns", "## Summary")


async def test_found_reports_go_to_the_model_without_their_text(reports) -> None:
    saved = reports.add("ben", "talk-1", "Diesel returns", "SECRET BODY")
    reports.add("ben", "talk-1", "Joe's Jeans revenue", "body")
    model = ScriptedModel([tool_call("find_reports", {"mentioning": "diesel"}), AIMessage("One.")])

    await agent(model, reports).reply("which reports mention Diesel?")

    [found] = last_tool_result(model)["reports"]
    assert (found["id"], found["title"]) == (saved.id, "Diesel returns")
    assert "SECRET BODY" not in model.seen[-1]


async def test_reports_of_this_conversation_are_found(reports) -> None:
    reports.add("ben", "talk-0", "Diesel returns", "body")
    today = reports.add("ben", "talk-1", "Joe's Jeans revenue", "body")
    find = tool_call("find_reports", {"this_conversation": True})
    model = ScriptedModel([find, AIMessage("One.")])

    await agent(model, reports).reply("what did we save today?")

    assert [found["id"] for found in last_tool_result(model)["reports"]] == [today.id]


async def test_delete_reports_asks_first_and_deletes_nothing(reports) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    model = ScriptedModel([delete_call([first.id]), AIMessage("done")])

    outcome = await agent(model, reports).reply("delete the Diesel report")

    assert outcome == DeletionRequest((summary(first),))
    assert reports.find("ben") == [first]


async def test_reports_of_others_and_unknown_ids_are_left_out_of_the_request(reports) -> None:
    mine = reports.add("ben", "talk-1", "Diesel returns", "body")
    theirs = reports.add("chloe", "talk-1", "Polo revenue", "body")
    model = ScriptedModel([delete_call([mine.id, theirs.id, 999]), AIMessage("done")])

    outcome = await agent(model, reports).reply("delete these")

    assert outcome == DeletionRequest((summary(mine),))


@pytest.mark.parametrize("ids", [[], [999]])
async def test_nothing_to_delete_is_answered_without_asking_the_person(reports, ids) -> None:
    theirs = reports.add("chloe", "talk-1", "Polo revenue", "body")
    model = ScriptedModel([delete_call([*ids, theirs.id]), AIMessage("No such reports.")])

    outcome = await agent(model, reports).reply("delete these")

    assert outcome == "No such reports."
    assert last_tool_result(model)["status"] == "not_found"
    assert reports.find("chloe") == [theirs]


async def test_after_a_yes_exactly_the_shown_reports_are_deleted(reports) -> None:
    shown = reports.add("ben", "talk-1", "Diesel returns", "body")
    kept = reports.add("ben", "talk-1", "Joe's Jeans revenue", "body")
    model = ScriptedModel([delete_call([shown.id]), AIMessage("The report is gone.")])
    chat_agent = agent(model, reports)

    await chat_agent.reply("delete the Diesel report")
    reply = await chat_agent.resume(agreed=True)

    assert reply == "The report is gone."
    assert reports.find("ben") == [kept]
    assert last_tool_result(model) == {"status": "deleted", "deleted": 1}


async def test_without_a_yes_nothing_is_deleted_and_the_model_is_told(reports) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    model = ScriptedModel([delete_call([first.id]), AIMessage("Kept.")])
    chat_agent = agent(model, reports)

    await chat_agent.reply("delete the Diesel report")
    await chat_agent.resume(agreed=False)

    assert reports.find("ben") == [first]
    assert last_tool_result(model) == {"status": "cancelled_by_person"}


@pytest.mark.parametrize(("agreed", "deleted"), [(True, 1), (False, 0)])
async def test_every_answered_request_is_written_to_the_log(
    reports, caplog, agreed, deleted
) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    model = ScriptedModel([delete_call([first.id]), AIMessage("done")])
    chat_agent = agent(model, reports)

    await chat_agent.reply("delete the Diesel report")
    await chat_agent.resume(agreed=agreed)

    assert f"owner=ben shown=[{first.id}]" in caplog.text
    assert f"deleted={deleted}" in caplog.text


async def test_two_requests_in_one_model_message_become_one(reports) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    second = reports.add("ben", "talk-1", "Joe's Jeans revenue", "body")
    both = tool_calls(
        ("delete_reports", {"ids": [first.id]}, 0), ("delete_reports", {"ids": [second.id]}, 1)
    )
    model = ScriptedModel([both, AIMessage("done")])

    outcome = await agent(model, reports).reply("delete both")

    assert outcome == DeletionRequest((summary(first),))


async def test_asking_again_after_the_answer_is_an_error(reports) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    model = ScriptedModel([delete_call([first.id], 0), delete_call([first.id], 1)])
    chat_agent = agent(model, reports)

    await chat_agent.reply("delete the Diesel report")

    with pytest.raises(RuntimeError, match="twice"):
        await chat_agent.resume(agreed=False)


async def test_an_unanswered_request_does_not_block_the_next_question(reports) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    model = ScriptedModel([delete_call([first.id]), AIMessage("Hello.")])
    chat_agent = agent(model, reports)

    await chat_agent.reply("delete the Diesel report")

    assert await chat_agent.reply("hello") == "Hello."


async def test_an_answer_without_a_request_is_an_error(reports) -> None:
    with pytest.raises(RuntimeError, match="no deletion request"):
        await agent(ScriptedModel([]), reports).resume(agreed=True)


async def test_in_a_chat_a_yes_deletes_the_report_and_the_model_reports_it(reports) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    model = ScriptedModel([delete_call([first.id]), AIMessage("The report is gone.")])
    terminal = FakeTerminal(["delete the Diesel report"], confirm=True)

    await Chat(agent(model, reports), terminal, BEN).run()

    assert reports.find("ben") == []
    assert last_tool_result(model) == {"status": "deleted", "deleted": 1}
    assert "1. Diesel returns" in terminal.shown[1]
    assert terminal.shown[2:] == ["The report is gone."]
