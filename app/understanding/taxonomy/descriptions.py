"""Recruiter-facing skill definitions (HERMES-950), in the spirit of
GlossaryTech: one clear, jargon-free sentence per skill so a non-
technical recruiter reading "SAP BTP" or "TIBCO BusinessWorks" on a
resume understands what it is without leaving the page.

Goes through the same LiteLLM gateway every other Hermes AI capability
uses (app/prompt_runtime/service.py) -- no direct provider calls. Not
routed through a registered Langfuse prompt, unlike the live parsing
pipeline's LLM fallback: this only ever runs from an admin action
(approving a taxonomy candidate, or the one-time backfill script), never
in the request path of a real email being parsed, so the tracing/cost-
attribution a registered prompt gives isn't needed the same way. Kept
strictly best-effort -- a description is a nice-to-have annotation, not
something any parsing decision depends on, so a failure here must never
break the caller.
"""

from __future__ import annotations

import os

from app.prompt_runtime.models import PromptRenderedMessage
from app.prompt_runtime.service import _call_litellm_with_model, litellm_configured

_SYSTEM_PROMPT = (
    "You write entries for a technical skills glossary aimed at IT recruiters "
    "who are not engineers. For the given term, write exactly one sentence "
    "(maximum 25 words) explaining what it is and what it is used for, in "
    "plain language a non-technical recruiter can understand instantly while "
    "reading a candidate's resume. Do not use other jargon to define the "
    "term. Do not start the sentence by repeating the term's name. Return "
    "only the sentence, no preamble, no quotation marks."
)


def generate_skill_description(name: str, category: str | None = None) -> str | None:
    if not litellm_configured():
        return None

    user_prompt = f"Term: {name}"
    if category:
        user_prompt += f"\nCategory: {category}"

    messages = [
        PromptRenderedMessage(role="system", content=_SYSTEM_PROMPT),
        PromptRenderedMessage(role="user", content=user_prompt),
    ]

    try:
        output, _usage = _call_litellm_with_model(
            messages, model=os.getenv("HERMES_PROMPT_DEFAULT_MODEL", "anthropic/claude-haiku-4-5")
        )
    except Exception:  # noqa: BLE001
        return None

    description = (output or "").strip().strip('"')

    return description or None
