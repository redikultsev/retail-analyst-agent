import json
import logging
from dataclasses import asdict

from langchain.tools import tool
from langchain_core.tools import BaseTool
from langgraph.types import interrupt

from retail_agent.domain.report import Report, ReportLibrary, ReportSummary

logger = logging.getLogger(__name__)

DELETE_REPORTS = "delete_reports"


def report_tools(reports: ReportLibrary, owner: str, conversation_id: str) -> list[BaseTool]:
    @tool
    def save_report(title: str, body: str) -> str:
        """Save a report to the library of the person you are talking to.

        The body is Markdown. Call this only when the person asks to save or create a report.
        """
        saved = reports.add(owner, conversation_id, title, body)
        return _json({"saved": {"id": saved.id, "title": saved.title}})

    @tool
    def find_reports(mentioning: str | None = None, this_conversation: bool = False) -> str:
        """List the saved reports of the person you are talking to.

        mentioning keeps the reports whose title or text contains that text.
        this_conversation keeps the reports saved in the current conversation.
        Without arguments it lists every saved report.
        """
        found = reports.find(
            owner,
            mentioning=mentioning,
            conversation_id=conversation_id if this_conversation else None,
        )
        return _json({"reports": [asdict(_summary(report)) for report in found]})

    @tool(DELETE_REPORTS)
    def delete_reports(ids: list[int]) -> str:
        """Delete saved reports by id, after the person agrees. Take the ids from find_reports.

        The person sees the reports and decides. Returns what happened.
        """
        found = reports.find(owner, ids=ids)
        if not found:
            return _json({"status": "not_found", "message": "No such reports."})
        # The run stops here until the person answers, then this function starts again
        # from the top. So the lines above only read, and the deletion comes after.
        approved: list[int] = interrupt([asdict(_summary(report)) for report in found])
        deleted = reports.delete(owner, approved) if approved else 0
        logger.warning(
            "deletion request settled: owner=%s shown=%s approved=%s deleted=%s",
            owner,
            [report.id for report in found],
            approved,
            deleted,
        )
        if not approved:
            return _json({"status": "cancelled_by_person"})
        return _json({"status": "deleted", "deleted": deleted})

    return [save_report, find_reports, delete_reports]


def _summary(report: Report) -> ReportSummary:
    return ReportSummary(report.id, report.title, report.created_at.date().isoformat())


def _json(result: dict[str, object]) -> str:
    return json.dumps(result, ensure_ascii=False)
