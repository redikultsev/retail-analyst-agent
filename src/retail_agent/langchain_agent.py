# LangChain's agent types are only partly known to the type checker.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from retail_agent.sql_tool import sql_tool
from retail_agent.warehouse import Warehouse


class LangChainAgent:
    def __init__(
        self,
        model: BaseChatModel,
        fallback: BaseChatModel,
        warehouse: Warehouse,
        system_prompt: str,
        *,
        max_model_calls: int,
        max_queries: int,
        timeout_s: float,
    ) -> None:
        run_sql = sql_tool(warehouse)
        self._graph = create_agent(  # pyright: ignore[reportCallIssue]
            model,
            [run_sql],
            system_prompt=system_prompt,
            checkpointer=InMemorySaver(),
            middleware=[  # pyright: ignore[reportArgumentType]
                ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="error"),
                ToolCallLimitMiddleware(tool_name=run_sql.name, run_limit=max_queries),
                ModelFallbackMiddleware(fallback),
            ],
        )
        self._timeout_s = timeout_s
        self._conversation = _new_conversation()

    async def reply(self, message: str) -> str:
        try:
            async with asyncio.timeout(self._timeout_s):
                state = await self._graph.ainvoke(
                    {"messages": [{"role": "user", "content": message}]}, self._conversation
                )
        except Exception:
            # A failed question leaves a half-finished turn in the memory, so the memory is dropped.
            self._conversation = _new_conversation()
            raise
        text = str(state["messages"][-1].text)
        if not text.strip():
            raise RuntimeError("the model returned an empty answer")
        return text


def _new_conversation() -> RunnableConfig:
    return {"configurable": {"thread_id": str(uuid4())}}
