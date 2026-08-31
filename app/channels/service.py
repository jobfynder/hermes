from time import perf_counter

from app.access.models import ActionAccessRequest
from app.access.service import authorize_action
from app.channels.models import ChannelIntakeRequest, ChannelIntakeResponse, DocumentKind
from app.drafts.service import create_draft_object
from app.email_parsing.blocklist import is_blocked as is_sender_blocked
from app.email_parsing.classification_learning import get_domain_bias
from app.email_parsing.dedupe import register_and_check
from app.email_parsing.llm_fallback import apply_hotlist_fallback, apply_job_requirement_fallback
from app.email_parsing.parsers import (
    classify_email_by_confidence,
    parse_email_business_records,
)
from app.email_parsing.provenance import (
    build_email_parsing_provenance,
    build_signature_provenance,
    record_field_provenance,
)
from app.email_parsing.sender_resolver import looks_forwarded, resolve_original_sender
from app.email_parsing.signature import parse_email_signature
from app.email_parsing.signature_learning import apply_learned_signature_patterns
from app.email_parsing.spam import classify_spam
from app.understanding.taxonomy.candidates import record_skill_usage, record_taxonomy_candidates
from app.runtime.events import emit_event
from app.runtime.intake_log import (
    record_idempotency_key_if_new,
    record_intake,
)
from app.understanding.models import RawDocument
from app.understanding.service import understand_document


def build_duplicate_key(request: ChannelIntakeRequest) -> str:
    return f"{request.channel}:{request.source_message_id}"


def detect_document_kind(request: ChannelIntakeRequest) -> DocumentKind:
    if request.channel == "email":
        intended_document_kind = request.metadata.get(
            "intended_document_kind"
        )

        if intended_document_kind in {"hotlist", "job_description"}:
            return intended_document_kind

        # Recipient-address routing couldn't resolve this (ambiguous or a
        # single shared mailbox receiving both kinds -- see
        # app/email_parsing/routing.py). Before falling through to the
        # generic keyword-marker classification below, try the two
        # purpose-built parsers directly: each already does real
        # structural analysis to produce its own confidence score, which
        # is a stronger signal than a body-keyword list. Only fall
        # through if that's inconclusive too (both score 0, or an exact
        # tie).
        confidence_classification = classify_email_by_confidence(request.text or "")
        if confidence_classification is not None:
            return confidence_classification["document_kind"]

        # Content alone couldn't decide. Before falling through to a
        # generic keyword-marker guess, check whether *this sender's own
        # correction history* leans one way -- a real per-sender pattern
        # (app/email_parsing/classification_learning.py) beats a
        # content-blind keyword list, but never overrides a confident
        # content-based read above.
        domain_bias = get_domain_bias(request.sender.email if request.sender else None)
        if domain_bias is not None:
            emit_event(
                "intake.classification.domain_bias_applied",
                {
                    "sender_email": request.sender.email if request.sender else None,
                    "favored_document_kind": domain_bias["favored_document_kind"],
                    "correction_count": domain_bias["correction_count"],
                },
            )
            return domain_bias["favored_document_kind"]

    text = (request.text or "").lower()

    if not text and request.attachments:
        return "unknown"

    resume_markers = [
        "resume",
        "curriculum vitae",
        "professional summary",
        "work experience",
        "education",
    ]
    jd_markers = [
        "job description",
        "required skills",
        "responsibilities",
        "requirements",
        "rate",
        "location",
    ]
    hotlist_markers = [
        "hotlist",
        "available consultants",
        "bench list",
    ]
    vendor_markers = [
        "vendor list",
        "implementation partner",
        "prime vendor",
    ]

    if any(marker in text for marker in hotlist_markers):
        return "hotlist"
    if any(marker in text for marker in vendor_markers):
        return "vendor_list"
    if any(marker in text for marker in jd_markers):
        return "job_description"
    if any(marker in text for marker in resume_markers):
        return "resume"
    if "bench sales" in text:
        return "bench_sales_profile"
    if "recruiter" in text:
        return "recruiter_profile"

    return "plain_message" if text.strip() else "unknown"


def understanding_document_kind(document_kind: DocumentKind) -> str:
    if document_kind in {"resume", "job_description", "unknown"}:
        return document_kind

    return "message"

def draft_object_for(document_kind: DocumentKind) -> str:
    mapping = {
        "resume": "draft_consultant_profile",
        "job_description": "draft_job_requirement",
        "hotlist": "draft_hotlist",
        "recruiter_profile": "draft_recruiter_profile",
        "bench_sales_profile": "draft_bench_sales_profile",
        "consultant_profile": "draft_consultant_profile",
        "vendor_list": "draft_vendor_list",
        "plain_message": "draft_channel_note",
        "unknown": "draft_channel_note",
    }
    return mapping[document_kind]


def confidence_from_understanding(result: dict, document_kind: DocumentKind) -> float:
    quality = result.get("quality", {})
    score = quality.get("confidence")

    if isinstance(score, int | float):
        return float(score)

    if document_kind == "unknown":
        return 0.2
    if document_kind == "plain_message":
        return 0.6
    return 0.75


def enforce_optional_action_access(request: ChannelIntakeRequest) -> list[str]:
    if not request.actor_id and not request.role and not request.action:
        return []

    if not request.actor_id or not request.role or not request.action:
        return ["access_context_incomplete"]

    decision = authorize_action(
        ActionAccessRequest(
            actor_id=request.actor_id,
            role=request.role,
            action=request.action,
            channel=request.channel,
            metadata={
                "source_message_id": request.source_message_id,
            },
        )
    )

    if decision.status != "allowed":
        return [decision.reason or "action_not_allowed"]

    return []


def process_channel_intake(request: ChannelIntakeRequest) -> ChannelIntakeResponse:
    duplicate_key = build_duplicate_key(request)

    access_errors = enforce_optional_action_access(request)
    if access_errors:
        return ChannelIntakeResponse(
            channel=request.channel,
            source_message_id=request.source_message_id,
            intake_status="failed",
            document_kind="unknown",
            draft_object_type="draft_channel_note",
            requires_review=True,
            confidence=0.0,
            errors=access_errors,
            duplicate_key=duplicate_key,
        )

    # Blocklist check (HERMES-900): a human already decided about this
    # sender, so skip everything else -- no dedupe bookkeeping, no
    # understanding pipeline, no draft. Checked before the idempotency key
    # is even recorded so a blocked sender's mail leaves nothing behind
    # but the intake_log entry below, which is what makes blocking actually
    # reduce review-queue clutter at 5,000 emails/day instead of just
    # tagging it after the fact.
    block_match = is_sender_blocked(request.sender.email if request.sender else None)
    if block_match:
        record_intake(
            {
                "duplicate_key": duplicate_key,
                "channel": request.channel,
                "source_message_id": request.source_message_id,
                "status": "blocked",
                "document_kind": "unknown",
                "block_matched": block_match["match_type"],
                "block_value": block_match["value"],
                "block_reason": block_match["reason"],
            }
        )
        emit_event(
            "intake.blocked",
            {
                "duplicate_key": duplicate_key,
                "channel": request.channel,
                "source_message_id": request.source_message_id,
                "matched": block_match["match_type"],
                "value": block_match["value"],
            },
        )
        return ChannelIntakeResponse(
            channel=request.channel,
            source_message_id=request.source_message_id,
            intake_status="blocked",
            document_kind="unknown",
            requires_review=False,
            confidence=0.0,
            errors=[],
            duplicate_key=duplicate_key,
        )

    # Atomic check-and-set against the database: True only for the caller
    # that actually inserted the key first. Correct across hermes-api and
    # hermes-graph-consumer running as separate processes, and race-free
    # within one -- there is no separate check-then-insert window for two
    # near-simultaneous deliveries of the same message to both land in.
    is_new = record_idempotency_key_if_new(duplicate_key)

    if not is_new:
        record_intake(
            {
                "duplicate_key": duplicate_key,
                "channel": request.channel,
                "source_message_id": request.source_message_id,
                "status": "duplicate",
                "document_kind": "unknown",
            }
        )
        emit_event(
            "intake.duplicate",
            {
                "duplicate_key": duplicate_key,
                "channel": request.channel,
                "source_message_id": request.source_message_id,
            },
        )
        return ChannelIntakeResponse(
            channel=request.channel,
            source_message_id=request.source_message_id,
            intake_status="duplicate",
            document_kind="unknown",
            requires_review=True,
            confidence=0.0,
            errors=["duplicate_message"],
            duplicate_key=duplicate_key,
        )

    record_intake(
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
            "status": "received",
            "content_type": request.content_type,
            "has_text": bool(request.text),
            "attachment_count": len(request.attachments),
        }
    )
    emit_event(
        "intake.received",
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
        },
    )

    # Exact-content dedupe (spec 12.1, layer 2): a different
    # provider_message_id carrying the identical body -- e.g. the same
    # email forwarded to two aliases, or re-delivered by the provider
    # under a new id. Transport dedupe above already caught a retry of
    # the *same* id; this catches the same content arriving as a "new"
    # message. Never blocks intake -- every source message is preserved
    # and still becomes its own draft, just linked to the canonical one.
    content_dedupe = register_and_check(request.text or "", duplicate_key)
    if content_dedupe["is_exact_content_duplicate"]:
        emit_event(
            "intake.exact_content_duplicate",
            {
                "duplicate_key": duplicate_key,
                "canonical_duplicate_key": content_dedupe["canonical_duplicate_key"],
                "duplicate_group_id": content_dedupe["duplicate_group_id"],
            },
        )

    document_kind = detect_document_kind(request)

    if not request.text and not request.attachments:
        return ChannelIntakeResponse(
            channel=request.channel,
            source_message_id=request.source_message_id,
            intake_status="failed",
            document_kind=document_kind,
            draft_object_type=draft_object_for(document_kind),
            requires_review=True,
            confidence=0.0,
            errors=["empty_intake"],
            duplicate_key=duplicate_key,
        )

    understanding = understand_document(
        RawDocument(
            content=request.text or "",
            filename=None,
            content_type="text/plain",
            document_kind=understanding_document_kind(document_kind),
        )
    )

    understanding_dict = understanding.model_dump()
    structured_data = understanding_dict.get("structured_data", {})
    taxonomy_signals = structured_data.get("taxonomy_signals", {})

    normalized_skills = structured_data.get("normalized_skills", [])
    normalized_job_titles = structured_data.get("normalized_job_titles", [])

    confidence = confidence_from_understanding(
        result=understanding_dict,
        document_kind=document_kind,
    )

    email_parsing: dict = {}
    signature: dict = {}

    if request.channel == "email":
        email_parsing = parse_email_business_records(
            text=request.text or "",
            document_kind=document_kind,
        )

        # LLM extraction fallback (spec section 7.5, step 7) -- only
        # engages below FALLBACK_CONFIDENCE_THRESHOLD, using the same
        # audited LiteLLM/Langfuse path and the same prompts already
        # proven elsewhere (jf.jobs.jd.extract, jf.broadcast.hotlist.
        # extract). The deterministic parsers above never call an LLM
        # themselves -- this is a strictly separate, later stage. See
        # app/email_parsing/llm_fallback.py.
        if document_kind == "job_description":
            email_parsing, _ = apply_job_requirement_fallback(request.text or "", email_parsing)
        elif document_kind == "hotlist":
            email_parsing, _ = apply_hotlist_fallback(request.text or "", email_parsing)

        structured_data["email_parsing"] = email_parsing

        email_confidence = email_parsing.get("confidence")

        if isinstance(email_confidence, int | float):
            confidence = float(email_confidence)

        # Deterministic signature extraction (no LLM -- see
        # app/email_parsing/signature.py PARSER_METADATA). Additive to
        # structured_data, never overrides document_kind/email_parsing
        # confidence above: a signature is metadata about the sender, not
        # the business record the email is classified as.
        signature_started_at = perf_counter()
        signature = parse_email_signature(
            text=request.text or "",
            sender_email=request.sender.email if request.sender else None,
        )

        # Fills in any field the deterministic extraction above missed
        # using values a reviewer already confirmed for this same sender
        # domain (never overrides a value the parser did find) -- see
        # app/email_parsing/signature_learning.py.
        signature_sender_domain = (
            request.sender.email.rsplit("@", 1)[-1].lower()
            if request.sender and request.sender.email and "@" in request.sender.email
            else None
        )
        apply_learned_signature_patterns(signature.get("contact", {}), signature_sender_domain)

        structured_data["signature"] = signature

        emit_event(
            "signature.parser_latency",
            {
                "duplicate_key": duplicate_key,
                "latency_ms": round((perf_counter() - signature_started_at) * 1000, 3),
            },
        )

        emit_event(
            "signature.detected" if signature["detected"] else "signature.not_detected",
            {
                "duplicate_key": duplicate_key,
                "channel": request.channel,
                "source_message_id": request.source_message_id,
                "confidence": signature["confidence"],
                "fields_extracted": sorted(signature.get("contact", {}).keys()),
                "llm_calls": 0,
            },
        )

        if signature["detected"] and signature["requires_review"]:
            emit_event(
                "signature.low_confidence",
                {
                    "duplicate_key": duplicate_key,
                    "confidence": signature["confidence"],
                    "warnings": signature.get("warnings", []),
                },
            )

        if signature.get("quoted_signature_ignored"):
            emit_event(
                "signature.quoted_signature_ignored",
                {"duplicate_key": duplicate_key},
            )

        for warning in signature.get("warnings", []):
            if warning == "disclaimer_removed":
                emit_event("signature.disclaimer_removed", {"duplicate_key": duplicate_key})
            elif warning.endswith("_not_detected") and signature["detected"]:
                emit_event(
                    "signature.extraction_failure_by_field",
                    {"duplicate_key": duplicate_key, "field": warning.removesuffix("_not_detected")},
                )

        for field_name in signature.get("contact", {}):
            emit_event(
                "signature.extraction_success_by_field",
                {"duplicate_key": duplicate_key, "field": field_name},
            )

    requires_review = (
        confidence < 0.7
        or document_kind in {"unknown", "plain_message"}
        or bool(email_parsing.get("requires_review"))
    )

    record_intake(
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
            "status": "parsed",
            "document_kind": document_kind,
            "normalized_skills": normalized_skills,
            "normalized_job_titles": normalized_job_titles,
            "confidence": confidence,
            "requires_review": requires_review,
        }
    )
    emit_event(
        "intake.parsed",
        {
            "duplicate_key": duplicate_key,
            "channel": request.channel,
            "source_message_id": request.source_message_id,
            "document_kind": document_kind,
            "normalized_skills": normalized_skills,
            "normalized_job_titles": normalized_job_titles,
        },
    )

    draft_type = draft_object_for(document_kind)

    # Spam heuristic (HERMES-900): unlike the blocklist check above, this
    # runs on every message from a sender nobody has judged yet, and it
    # only ever flags -- create_draft_object still runs below, just with
    # status forced to 'spam' instead of the usual draft/needs_review, so
    # a human reviews and either deletes it or reclassifies it back.
    spam_reasons = classify_spam(
        text=request.text or "",
        document_kind=document_kind,
        confidence=confidence,
    )
    if spam_reasons:
        emit_event(
            "intake.flagged_spam",
            {
                "duplicate_key": duplicate_key,
                "channel": request.channel,
                "source_message_id": request.source_message_id,
                "reasons": spam_reasons,
            },
        )

    # Forwarded-sender resolution (spec 4.1). normalize_email_payload()
    # (app/providers/email/service.py) already computes this ahead of time
    # for the webhook path, where a Reply-To header may be available --
    # reuse that if present. Recomputed here from request.text as a
    # channel-level fallback so the same guarantee holds regardless of
    # entry point (webhook, Gmail/Graph connector, or a direct call),
    # since ChannelIntakeRequest itself carries no reply_to field.
    original_sender_candidate = request.metadata.get("original_sender_candidate")
    if (
        not original_sender_candidate
        and request.channel == "email"
        and looks_forwarded(request.text or "")
    ):
        original_sender_candidate = resolve_original_sender(request.text or "")

    draft = create_draft_object(
        draft_type=draft_type,
        source="channel_text_intake",
        source_ref=duplicate_key,
        channel=request.channel,
        source_message_id=request.source_message_id,
        payload={
            "text": request.text or "",
            "document_kind": document_kind,
            "structured_data": structured_data,
        },
        normalized_skills=normalized_skills,
        normalized_job_titles=normalized_job_titles,
        taxonomy_signals=taxonomy_signals,
        confidence=confidence,
        requires_review=requires_review,
        status_override="spam" if spam_reasons else None,
        metadata={
            "duplicate_key": duplicate_key,
            "content_type": request.content_type,
            "sender": request.sender.model_dump() if request.sender else None,
            "original_sender_candidate": original_sender_candidate,
            "spam_reasons": spam_reasons,
            "exact_content_duplicate_of": (
                content_dedupe["canonical_duplicate_key"]
                if content_dedupe["is_exact_content_duplicate"]
                else None
            ),
            "duplicate_group_id": content_dedupe["duplicate_group_id"],
            **{
                # Carries any other channel-specific extras set upstream
                # through to the draft without hardcoding channel-specific
                # keys here.
                key: value
                for key, value in request.metadata.items()
                if key not in {"duplicate_key", "content_type", "original_sender_candidate"}
            },
        },
    )

    if email_parsing:
        # Field-level provenance (spec section 10): one entry per extracted
        # field, keyed by this draft's id as the parse_run_id (this
        # codebase creates exactly one parse per intake, so the draft
        # already is the parse-run record -- no separate id needed).
        record_field_provenance(
            parse_run_id=draft.draft_id,
            entries=build_email_parsing_provenance(email_parsing),
        )

    if signature.get("detected"):
        record_field_provenance(
            parse_run_id=draft.draft_id,
            entries=build_signature_provenance(signature),
        )

    # Taxonomy candidate detection (HERMES-900): surfaces skill/job-title
    # -shaped tokens the taxonomy doesn't recognize for human review --
    # never added automatically, see app/understanding/taxonomy/
    # candidates.py. Best-effort and after the draft already exists: a
    # failure here must never block draft creation, which is the part
    # that actually matters to the reviewer.
    try:
        sender_domain = (
            request.sender.email.rsplit("@", 1)[-1].lower()
            if request.sender and request.sender.email and "@" in request.sender.email
            else None
        )
        candidate_job_titles: list[str] = []
        for record in (email_parsing.get("records") or []):
            title = record.get("job_title") or record.get("primary_job_title")
            if title:
                candidate_job_titles.append(title)

        record_taxonomy_candidates(
            text=request.text or "",
            draft_id=draft.draft_id,
            sender_domain=sender_domain,
            job_titles=candidate_job_titles,
        )
    except Exception as exc:  # noqa: BLE001
        emit_event(
            "taxonomy_candidates.record_failed",
            {"duplicate_key": duplicate_key, "error": str(exc)},
        )

    # Skill usage stats: which canonical skills this draft actually
    # matched, for the taxonomy browse page's "times seen" / "last seen"
    # columns. Best-effort, same reasoning as the block above.
    try:
        matched_skill_names: list[str] = []
        for record in (email_parsing.get("records") or []):
            matched_skill_names.extend(record.get("required_skills") or [])
            matched_skill_names.extend(record.get("preferred_skills") or [])
            matched_skill_names.extend(record.get("primary_skills") or [])
        record_skill_usage(matched_skill_names)
    except Exception as exc:  # noqa: BLE001
        emit_event(
            "skill_usage.record_failed",
            {"duplicate_key": duplicate_key, "error": str(exc)},
        )

    return ChannelIntakeResponse(
        channel=request.channel,
        source_message_id=request.source_message_id,
        intake_status="parsed",
        document_kind=document_kind,
        understanding_result={
            **understanding_dict,
            "draft_id": draft.draft_id,
        },
        taxonomy_signals=taxonomy_signals,
        normalized_skills=normalized_skills,
        normalized_job_titles=normalized_job_titles,
        draft_object_type=draft_type,
        requires_review=requires_review,
        confidence=confidence,
        errors=[],
        duplicate_key=duplicate_key,
    )
