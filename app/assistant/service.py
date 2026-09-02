"""Natural-language query assistant for the Hermes admin dashboard.

Deliberately NOT a text-to-SQL agent -- an LLM given raw SQL access to
production data is a real safety/correctness risk (a subtly wrong
WHERE clause returns a subtly wrong number with total confidence). Set
of fixed, safe, read-only TOOLS instead, each backed by the exact same
functions the dashboard's own charts call (app/reporting/service.py),
plus one search tool. The model can only ever call one of these -- it
picks which one and with what parameters, never writes its own query.

Two-step flow per question:
1. One LLM call: given the question and a plain description of the
   available tools, pick ONE tool (or "none" for a question that
   doesn't need data, e.g. "what can you ask me") and its parameters.
2. Run that tool (a plain Python function call, no LLM involved), then
   one more LLM call: given the question and the tool's JSON result,
   write a short, concrete, natural-language answer.

A tool-selection response that fails to parse, or names a tool that
doesn't exist, falls back to a plain "I couldn't find data for that"
answer rather than guessing -- same fail-safe philosophy as the daily
triage job.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.prompt_runtime.models import PromptRenderedMessage
from app.prompt_runtime.service import _call_litellm_with_model, litellm_configured
from app.reporting.service import (
    get_ai_dependency_report,
    get_candidate_queue_health,
    get_classification_report,
    get_dashboard_overview,
    get_ingestion_health,
    get_llm_cost_trend,
    get_parsing_quality,
    get_review_queue_report,
    get_signature_quality_report,
    get_taxonomy_overview,
    get_triage_activity,
)
from app.understanding.taxonomy.candidates import list_taxonomy_candidates

MODEL = "anthropic/claude-haiku-4-5"


def _search_pending_candidates(signal_type: str = "all", search: str = "", limit: int = 20) -> dict[str, Any]:
    candidates = list_taxonomy_candidates(status="pending")
    if signal_type != "all":
        candidates = [c for c in candidates if c["signal_type"] == signal_type]
    if search:
        needle = search.lower()
        candidates = [c for c in candidates if needle in c["term"].lower()]
    candidates.sort(key=lambda c: -c["occurrence_count"])
    total_matches = len(candidates)
    return {
        "total_matches": total_matches,
        "shown": candidates[: max(1, min(limit, 50))],
    }


# Each tool: (description shown to the model, callable, param names it accepts).
_TOOLS: dict[str, tuple[str, Callable[..., Any], list[str]]] = {
    "taxonomy_overview": (
        "Current canonical skills/job-titles taxonomy size, and how many were added in "
        "the last 7 and 30 days. No parameters.",
        get_taxonomy_overview,
        [],
    ),
    "queue_health": (
        "Current pending taxonomy-candidate backlog by type (skill/job_title/"
        "boilerplate_line), and the age in days of the oldest pending item in each. "
        "No parameters.",
        get_candidate_queue_health,
        [],
    ),
    "triage_activity": (
        "Daily counts of taxonomy candidates approved/rejected, split by whether it was "
        "the automated daily triage job or a human reviewer. Parameter: days (int, "
        "default 14) -- how many days back to look.",
        get_triage_activity,
        ["days"],
    ),
    "llm_cost_trend": (
        "Daily LLM API spend in dollars, from Langfuse. Parameter: days (int, default "
        "30) -- how many days back to look.",
        get_llm_cost_trend,
        ["days"],
    ),
    "parsing_quality": (
        "Recent parsed-email draft volume: total count, average confidence, percent "
        "needing human review, and a breakdown by draft type. Parameter: days (int, "
        "default 7) -- how many days back to look.",
        get_parsing_quality,
        ["days"],
    ),
    "ingestion_health": (
        "Raw email intake: how many arrived, how many were successfully parsed, how "
        "many were duplicates, the processing success rate, emails received per hour, "
        "and a breakdown by channel (email, etc). Parameter: days (int, default 7).",
        get_ingestion_health,
        ["days"],
    ),
    "classification_report": (
        "How incoming email got classified -- counts and average confidence per draft "
        "type (job requirement, hotlist, etc), plus a daily trend. Parameter: days "
        "(int, default 7).",
        get_classification_report,
        ["days"],
    ),
    "ai_dependency_report": (
        "What share of drafts needed an LLM call versus were handled by the "
        "deterministic parser alone (parser-only vs AI-assisted), plus LLM cost over "
        "the same window and cost per 1000 drafts. Parameter: days (int, default 7).",
        get_ai_dependency_report,
        ["days"],
    ),
    "review_queue_report": (
        "Drafts by status (draft/needs_review/published/spam), plus the specific "
        "reasons drafts need review (missing company, missing job title, missing "
        "skills, etc) ranked by frequency. Parameter: days (int, default 7) -- affects "
        "only the review-reason breakdown, not the status counts (which are always "
        "current). ",
        get_review_queue_report,
        ["days"],
    ),
    "signature_quality_report": (
        "Per-field accuracy for the email SIGNATURE parser (sender name, email, "
        "company, phone, job title, address, etc) -- fill rate, precision measured "
        "from actual human corrections (not just stated confidence), false-positive "
        "rate, and a confidence-calibration gap (positive means Hermes is more "
        "confident than it turns out to be correct). Use this for any question about "
        "signature/sender-name/company extraction quality or false positives. "
        "Parameter: days (int, default 30).",
        get_signature_quality_report,
        ["days"],
    ),
    "dashboard_overview": (
        "Everything at once: taxonomy overview + queue health + 14-day triage activity "
        "+ 30-day LLM cost + 7-day parsing quality. Use this for a broad \"how are things "
        "going\" question rather than calling several narrower tools. No parameters.",
        get_dashboard_overview,
        [],
    ),
    "search_pending_candidates": (
        "Search the list of taxonomy candidates still awaiting review. Parameters: "
        "signal_type (one of 'skill', 'job_title', 'boilerplate_line', 'all' -- default "
        "'all'), search (a text substring to match against the term, case-insensitive, "
        "default empty = no filter), limit (int, default 20, max 50).",
        _search_pending_candidates,
        ["signal_type", "search", "limit"],
    ),
}


def _tool_catalog_text() -> str:
    lines = []
    for name, (description, _fn, _params) in _TOOLS.items():
        lines.append(f"- {name}: {description}")
    return "\n".join(lines)


_SELECT_TOOL_SYSTEM_PROMPT = (
    "You are the query-planning step of a natural-language dashboard assistant for "
    "Hermes, an IT staffing email-parsing and taxonomy platform. Given the user's "
    "question, pick exactly ONE tool from this list that would answer it, with "
    "parameters:\n\n"
    f"{_tool_catalog_text()}\n\n"
    "If the question doesn't need any data (a greeting, \"what can you ask\", small "
    "talk), respond with tool \"none\" instead.\n\n"
    "Reply with ONLY a JSON object, no other text: "
    '{"tool": "<tool_name_or_none>", "params": {...}}. '
    "Only include parameters the tool actually accepts, using its exact parameter names."
)

_ANSWER_SYSTEM_PROMPT = (
    "You are a dashboard assistant for Hermes, an IT staffing email-parsing and "
    "taxonomy platform. You were asked a question, ran a data lookup, and got back a "
    "JSON result. Write a short, concrete, plain-English answer using the actual "
    "numbers from the result -- 2-4 sentences, no preamble, no restating the question. "
    "If the result is empty or shows nothing notable, say so plainly rather than "
    "inventing detail. Never mention 'JSON', 'tool', or the mechanics of how you got "
    "the answer -- just answer as if you already knew it."
)

_NO_DATA_SYSTEM_PROMPT = (
    "You are a dashboard assistant for Hermes, an IT staffing email-parsing and "
    "taxonomy platform. The user's message doesn't need a data lookup (a greeting, "
    "small talk, or a question about what you can help with). Reply briefly and "
    "naturally. If asked what you can do, mention you can answer questions about the "
    "skills/job-title taxonomy, the review-candidate backlog, daily automated triage "
    "activity, LLM cost, and email-parsing quality."
)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _call_llm(system_prompt: str, user_content: str) -> str | None:
    messages = [
        PromptRenderedMessage(role="system", content=system_prompt),
        PromptRenderedMessage(role="user", content=user_content),
    ]
    try:
        output, _usage = _call_litellm_with_model(messages, MODEL)
        return output
    except Exception:  # noqa: BLE001
        return None


def answer_query(question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Returns {"answer": str, "tool_used": str | None, "data": dict | None}."""
    if not question or not question.strip():
        return {"answer": "Ask me something about the taxonomy, review queue, cost, or parsing quality.",
                "tool_used": None, "data": None}

    if not litellm_configured():
        return {
            "answer": "The assistant needs an LLM connection to answer questions, and none is configured right now.",
            "tool_used": None,
            "data": None,
        }

    history_text = ""
    if history:
        recent = history[-6:]
        history_text = "\n\nRecent conversation:\n" + "\n".join(
            f"{turn.get('role', 'user')}: {turn.get('content', '')}" for turn in recent
        )

    plan_raw = _call_llm(_SELECT_TOOL_SYSTEM_PROMPT, f"Question: {question}{history_text}")
    plan = _extract_json_object(plan_raw) if plan_raw else None

    tool_name = (plan or {}).get("tool", "none")
    params = (plan or {}).get("params") or {}

    if not plan or tool_name == "none" or tool_name not in _TOOLS:
        answer = _call_llm(_NO_DATA_SYSTEM_PROMPT, question)
        return {
            "answer": answer or "I couldn't find data for that -- try asking about taxonomy size, the review "
                                 "queue, triage activity, LLM cost, or parsing quality.",
            "tool_used": None,
            "data": None,
        }

    _description, fn, allowed_params = _TOOLS[tool_name]
    safe_params = {k: v for k, v in params.items() if k in allowed_params}

    try:
        result = fn(**safe_params)
    except Exception as e:  # noqa: BLE001
        return {
            "answer": f"I tried to look that up but the query failed ({e}).",
            "tool_used": tool_name,
            "data": None,
        }

    result_text = json.dumps(result, default=str)[:6000]
    answer = _call_llm(_ANSWER_SYSTEM_PROMPT, f"Question: {question}\n\nData: {result_text}")

    return {
        "answer": answer or "I found the data but couldn't summarize it -- see the raw result below.",
        "tool_used": tool_name,
        "data": result,
    }
