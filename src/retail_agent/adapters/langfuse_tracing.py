# The Langfuse SDK is only partly typed.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import langfuse_lite
from langchain_core.callbacks import BaseCallbackHandler
from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler
from langfuse.types import (
    MaskOtelSpansFunction,
    MaskOtelSpansParams,
    MaskOtelSpansResult,
    OtelSpanIdentifier,
    OtelSpanPatch,
)

from retail_agent.domain.pii import PiiMask
from retail_agent.query.sanitize import error_text, redact

logger = logging.getLogger(__name__)

QUESTION = "question"


class NoTracer:
    """Stands in when traces cannot be recorded, so the chat still works."""

    recording = False

    def callbacks(self) -> list[BaseCallbackHandler]:
        return []

    @contextmanager
    def question(self, text: str) -> Generator["NoTracer"]:
        yield self

    def answered(self, reply: str) -> None:
        pass

    def failed(self, error: Exception) -> None:
        pass

    def close(self) -> None:
        pass


class CleanCallbackHandler(CallbackHandler):
    """Cleans an error text before Langfuse stores it as the status of a span.

    The mask hook below only reaches span attributes, and the status is not one of them.
    """

    def __init__(self, public_key: str, secrets: tuple[str, ...]) -> None:
        super().__init__(public_key=public_key)
        self._secrets = secrets

    def _get_error_level_and_status_message(
        self, error: BaseException
    ) -> tuple[Literal["DEFAULT", "ERROR"], str]:
        level, message = super()._get_error_level_and_status_message(error)
        return level, PiiMask().hide(error_text(message, self._secrets))


class LangfuseQuestion:
    def __init__(self, span: Any) -> None:
        self._span = span

    def answered(self, reply: str) -> None:
        self._span.update(output=reply)

    def failed(self, error: Exception) -> None:
        self._span.update(level="ERROR", status_message=type(error).__name__)


class LangfuseTracer:
    """Records one trace per question, with the model and tool calls inside it."""

    recording = True

    def __init__(
        self,
        client: Langfuse,
        handler: BaseCallbackHandler,
        user: str,
        conversation_id: str,
        local: langfuse_lite.LangfuseLite | None = None,
    ) -> None:
        self._client = client
        self._handler = handler
        self._user = user
        self._conversation_id = conversation_id
        self._local = local

    def callbacks(self) -> list[BaseCallbackHandler]:
        return [self._handler]

    @contextmanager
    def question(self, text: str) -> Generator[LangfuseQuestion]:
        with (
            propagate_attributes(user_id=self._user, session_id=self._conversation_id),
            self._client.start_as_current_observation(name=QUESTION, input=text) as span,
        ):
            yield LangfuseQuestion(span)

    def close(self) -> None:
        self._client.shutdown()
        if self._local:
            self._local.stop()


def start_local_langfuse(database: Path) -> langfuse_lite.LangfuseLite:
    database.parent.mkdir(parents=True, exist_ok=True)
    # langfuse-lite reports anonymous usage unless told not to. It reads this from the environment.
    os.environ["TELEMETRY_ENABLED"] = "false"
    return langfuse_lite.serve(db=database)


def cleaner(secrets: tuple[str, ...]) -> MaskOtelSpansFunction:
    """Build the hook that cleans every recorded text just before it is sent."""

    def clean(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
        patches: dict[OtelSpanIdentifier, OtelSpanPatch] = {}
        for identifier, span in params.spans.items():
            texts = {key: v for key, v in span.attributes.items() if isinstance(v, str)}
            cleaned = {key: PiiMask().hide(redact(text, secrets)) for key, text in texts.items()}
            changed = {key: text for key, text in cleaned.items() if text != texts[key]}
            if changed:
                patches[identifier] = OtelSpanPatch(set_attributes=changed)
        return MaskOtelSpansResult(span_patches=patches)

    return clean
