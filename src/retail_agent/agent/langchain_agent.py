# LangChain's agent types are only partly known to the type checker.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from retail_agent.domain.report import DeletionRequest, ReportSummary


class LangChainAgent:
    def __init__(
        self,
        model: BaseChatModel,
        fallback: BaseChatModel,
        tools: Sequence[BaseTool],
        system_prompt: str,
        *,
        max_model_calls: int,
        max_tool_calls: Mapping[str, int],
        timeout_s: float,
    ) -> None:
        self._graph = create_agent(  # pyright: ignore[reportCallIssue]
            model,
            tools,
            system_prompt=system_prompt,
            checkpointer=InMemorySaver(),
            middleware=[  # pyright: ignore[reportArgumentType]
                ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="error"),
                *(
                    ToolCallLimitMiddleware(tool_name=name, run_limit=limit)
                    for name, limit in max_tool_calls.items()
                ),
                ModelFallbackMiddleware(fallback),
            ],
        )
        self._timeout_s = timeout_s
        self._thread = _new_thread()
        self._waiting: DeletionRequest | None = None

    async def reply(self, message: str) -> str | DeletionRequest:
        if self._waiting:
            # The last deletion request was never answered, so that turn is unfinished.
            self._forget()
        return await self._run({"messages": [{"role": "user", "content": message}]})

    async def resume(self, agreed: bool) -> str:
        """Continue after a deletion request with the person's answer."""
        if self._waiting is None:
            raise RuntimeError("no deletion request is waiting for an answer")
        approved = [report.id for report in self._waiting.reports] if agreed else []
        outcome = await self._run(Command(resume=approved))
        if isinstance(outcome, DeletionRequest):
            self._forget()
            raise RuntimeError("the model asked to delete reports twice for one question")
        return outcome

    async def _run(self, step: dict[str, Any] | Command[Any]) -> str | DeletionRequest:
        try:
            async with asyncio.timeout(self._timeout_s):
                state = await self._graph.ainvoke(step, self._thread)
        except Exception:
            # A failed question leaves a half-finished turn in the memory, so the memory is dropped.
            self._forget()
            raise
        pauses = state.get("__interrupt__")
        if pauses:
            shown = tuple(ReportSummary(**report) for report in pauses[0].value)
            self._waiting = DeletionRequest(shown)
            return self._waiting
        self._waiting = None
        text = str(state["messages"][-1].text)
        if not text.strip():
            raise RuntimeError("the model returned an empty answer")
        return text

    def _forget(self) -> None:
        self._thread = _new_thread()
        self._waiting = None


def _new_thread() -> RunnableConfig:
    return {"configurable": {"thread_id": str(uuid4())}}
