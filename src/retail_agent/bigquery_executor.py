# The Google client is only partly typed.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
import logging
import time
from dataclasses import replace
from typing import Any

from google.api_core import exceptions as api
from google.auth import exceptions as auth
from google.cloud import bigquery
from google.cloud.bigquery.retry import DEFAULT_RETRY

from retail_agent.query_executor import Estimate, Failed, FailureKind, Fetched
from retail_agent.sql_guard import Allowed

logger = logging.getLogger(__name__)

KIND_BY_REASON: dict[str, FailureKind] = {
    "invalidQuery": "invalid_query",
    "bytesBilledLimitExceeded": "too_expensive",
    "resourcesExceeded": "too_expensive",
    "responseTooLarge": "too_expensive",
    "stopped": "timeout",
    "timeout": "timeout",
    # Returned for a project id that does not exist.
    "badRequest": "misconfigured",
    "quotaExceeded": "unavailable",
    "rateLimitExceeded": "unavailable",
    "backendError": "unavailable",
    "internalError": "unavailable",
}
KIND_BY_TYPE: tuple[tuple[type[Exception], FailureKind], ...] = (
    (TimeoutError, "timeout"),
    (api.DeadlineExceeded, "timeout"),
    (api.RetryError, "timeout"),
    (auth.GoogleAuthError, "misconfigured"),
    (api.Forbidden, "misconfigured"),
    (api.Unauthorized, "misconfigured"),
    (api.NotFound, "misconfigured"),
    (api.BadRequest, "invalid_query"),
)
MIN_WAIT_S = 1.0
CANCEL_TIMEOUT_S = 1.0


class BigQueryExecutor:
    def __init__(self, client: bigquery.Client, *, max_bytes_billed: int, timeout_s: float) -> None:
        self._client = client
        self._max_bytes_billed = max_bytes_billed
        self._timeout_s = timeout_s

    def dry_run(self, query: Allowed) -> Estimate | Failed:
        try:
            job = self._submit(query, bigquery.QueryJobConfig(dry_run=True))
            if job.total_bytes_processed is None:
                return Failed("unavailable", "dry run returned no estimate")
            return Estimate(bytes_processed=job.total_bytes_processed)
        except Exception as error:
            return _never_reached_bigquery(classify(error))

    def execute(self, query: Allowed, max_rows: int) -> Fetched | Failed:
        started = time.monotonic()
        job = None
        try:
            job = self._submit(
                query,
                bigquery.QueryJobConfig(
                    maximum_bytes_billed=self._max_bytes_billed,
                    job_timeout_ms=int(self._timeout_s * 1000),
                ),
            )
            time_left = max(MIN_WAIT_S, self._timeout_s - (time.monotonic() - started))
            rows = job.result(max_results=max_rows, timeout=time_left)
            return Fetched(
                columns=tuple(field.name for field in rows.schema),
                rows=tuple(tuple(row.values()) for row in rows),
                bytes_processed=job.total_bytes_processed,
                cache_hit=bool(job.cache_hit),
                job_id=job.job_id,
            )
        except Exception as error:
            failed = classify(error)
            if job is None:
                return _never_reached_bigquery(failed)
            if failed.kind == "timeout":
                self._cancel(job)
            return replace(failed, job_id=job.job_id)

    def _submit(self, query: Allowed, config: bigquery.QueryJobConfig) -> bigquery.QueryJob:
        # Without these limits a lost connection keeps the call waiting for up to ten minutes.
        return self._client.query(
            query.sql,
            job_config=config,
            timeout=self._timeout_s,
            retry=DEFAULT_RETRY.with_timeout(self._timeout_s),
            job_retry=None,
        )

    def _cancel(self, job: bigquery.QueryJob) -> None:
        try:
            job.cancel(retry=None, timeout=CANCEL_TIMEOUT_S)
        except Exception:
            logger.warning("could not cancel job %s", job.job_id, exc_info=True)


def classify(error: Exception) -> Failed:
    details: dict[str, Any] = {}
    if isinstance(error, api.GoogleAPICallError) and error.errors:
        first = error.errors[0]
        if isinstance(first, dict):
            details = first
    kind = KIND_BY_REASON.get(details.get("reason", "")) or _kind_by_type(error)
    cause = f"{type(error).__name__}: {error}".removesuffix(": ")
    return Failed(kind, details.get("message") or cause)


def _never_reached_bigquery(failed: Failed) -> Failed:
    """A timeout before any job exists is a connection problem, not a slow query."""
    return replace(failed, kind="unavailable") if failed.kind == "timeout" else failed


def _kind_by_type(error: Exception) -> FailureKind:
    for error_type, kind in KIND_BY_TYPE:
        if isinstance(error, error_type):
            return kind
    logger.error("unexpected error from the BigQuery client", exc_info=error)
    return "unavailable"
