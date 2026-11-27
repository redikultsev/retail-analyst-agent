from decimal import Decimal

import pytest
from fakes import BrokenModel, FakeExecutor, ScriptedModel, sql_call
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import AIMessage

from retail_agent.langchain_agent import LangChainAgent
from retail_agent.policy import Brands, Policy
from retail_agent.query_executor import Fetched
from retail_agent.warehouse import Warehouse

BEN_SCOPE = Brands(frozenset({"Diesel", "Joe's Jeans"}))


def agent(
    model, executor=None, *, fallback=None, max_model_calls=10, max_queries=6, timeout_s=5.0
) -> LangChainAgent:
    warehouse = Warehouse(
        executor or FakeExecutor(),
        Policy(scope=BEN_SCOPE),
        max_bytes=1_000_000,
        max_result_chars=20_000,
        secrets=(),
    )
    return LangChainAgent(
        model,
        fallback or ScriptedModel([]),
        warehouse,
        "You are a retail analyst.",
        max_model_calls=max_model_calls,
        max_queries=max_queries,
        timeout_s=timeout_s,
    )


async def test_reply_is_the_models_final_text() -> None:
    model = ScriptedModel([sql_call("SELECT name FROM products"), AIMessage("Jeans sell best.")])

    assert await agent(model).reply("what sells best?") == "Jeans sell best."


async def test_the_models_sql_runs_under_the_users_brands() -> None:
    executor = FakeExecutor()
    model = ScriptedModel([sql_call("SELECT name FROM products"), AIMessage("done")])

    await agent(model, executor).reply("what sells best?")

    query, _ = executor.fetches[0]
    assert "Diesel" in query.sql


async def test_the_model_reads_the_result_as_json() -> None:
    executor = FakeExecutor(fetch=Fetched(("name", "revenue"), (("Jeans", Decimal("120.50")),), 1))
    model = ScriptedModel([sql_call("SELECT name FROM products"), AIMessage("done")])

    await agent(model, executor).reply("what sells best?")

    assert '["Jeans", "120.50"]' in model.seen[-1]


async def test_a_refused_query_goes_back_to_the_model_as_a_refusal() -> None:
    model = ScriptedModel([sql_call("SELECT email FROM users"), AIMessage("I cannot show that.")])

    await agent(model).reply("list customer emails")

    assert '"status": "denied"' in model.seen[-1]


async def test_earlier_questions_stay_in_the_conversation() -> None:
    model = ScriptedModel([AIMessage("Which period?"), AIMessage("done")])
    chat_agent = agent(model)

    await chat_agent.reply("revenue by month")
    await chat_agent.reply("this year")

    assert "revenue by month" in model.seen[-1]


async def test_queries_stop_at_the_limit_for_one_question() -> None:
    executor = FakeExecutor()
    model = ScriptedModel([*(sql_call("SELECT 1", n) for n in range(3)), AIMessage("done")])

    await agent(model, executor, max_queries=2).reply("dig deeper")

    assert len(executor.fetches) == 2


async def test_too_many_model_calls_end_the_question_with_an_error() -> None:
    model = ScriptedModel([sql_call("SELECT 1", n) for n in range(5)])

    with pytest.raises(ModelCallLimitExceededError):
        await agent(model, max_model_calls=2).reply("dig deeper")


async def test_fallback_model_answers_when_the_main_one_fails() -> None:
    fallback = ScriptedModel([AIMessage("from the fallback")])

    assert await agent(BrokenModel(), fallback=fallback).reply("hello") == "from the fallback"


async def test_a_failed_question_is_forgotten() -> None:
    model = ScriptedModel([sql_call("SELECT 1", 0), sql_call("SELECT 1", 1), AIMessage("done")])
    chat_agent = agent(model, max_model_calls=2)

    with pytest.raises(ModelCallLimitExceededError):
        await chat_agent.reply("a question that is too hard")
    await chat_agent.reply("an easy question")

    assert "too hard" not in model.seen[-1]


async def test_an_empty_answer_is_an_error() -> None:
    model = ScriptedModel([AIMessage("")])

    with pytest.raises(RuntimeError, match="empty"):
        await agent(model).reply("hello")


async def test_a_question_that_takes_too_long_ends_with_an_error() -> None:
    model = ScriptedModel([AIMessage("too late")])

    with pytest.raises(TimeoutError):
        await agent(model, timeout_s=0).reply("hello")
