"""Field-level accuracy (HERMES-950), computed from field_provenance
rather than a hand-labeled test corpus. The signal already exists and was
already documented as the plan (see record_recruiter_correction's
docstring in app/email_parsing/provenance.py) -- it just had no reader
until now. Every field Hermes extracts gets one provenance row; every
time a human (recruiter via their claim link, or a reviewer via inline
editing on the review page -- app/drafts/corrections.py) changes that
value, a second row lands with extractor='recruiter_correction' or
'reviewer_correction' and the original value preserved as raw_value. That
is a real, continuously-growing labeled dataset with zero extra data
entry from anyone.

Two numbers per field, not one, because they answer different questions:

- fill_rate: of the drafts Hermes saw, in what share did it produce a
  non-empty value for this field at all? A recall measure -- low fill
  rate means the parser is leaving the field blank too often.
- precision: of the values it DID produce, what share did a human leave
  untouched? Computed by looking at each correction's own raw_value
  (the value being replaced): if raw_value was itself empty, the
  correction fixed a fill_rate miss, not a wrong value, so it's excluded
  from the precision denominator entirely -- otherwise a field Hermes
  correctly leaves blank half the time would look like it has terrible
  precision purely because of the other half.
"""

from __future__ import annotations

from app.runtime.db import cursor

JOB_REQUIREMENT_FIELDS = [
    "job_title",
    "company",
    "linkedin_url",
    "required_skills",
    "preferred_skills",
    "years_of_experience",
    "location",
    "work_authorization",
    "employment_type",
    "rate_or_salary",
]

HOTLIST_CONSULTANT_FIELDS = [
    "candidate_name",
    "candidate_email",
    "candidate_phone",
    "primary_job_title",
    "primary_skills",
    "years_of_experience",
    "current_location",
    "work_authorization",
    "availability",
    "expected_rate",
]

# Signature parsing (app/email_parsing/signature.py) runs on every
# email regardless of document kind -- job requirement, hotlist,
# whatever -- so unlike the two field lists above, this isn't scoped to
# one draft_type (see draft_type=None handling in _field_accuracy_for_
# type below).
SIGNATURE_FIELDS = [
    "full_name",
    "first_name",
    "last_name",
    "middle_name",
    "email",
    "phone",
    "mobile",
    "company_name",
    "website",
    "job_title",
    "linkedin_url",
    "city",
    "state",
    "address",
    "postal_code",
]

CORRECTION_EXTRACTORS = ("recruiter_correction", "reviewer_correction")

# Below this many extraction attempts, a precision/fill-rate percentage is
# noise -- one bad email can swing it 20 points. The dashboard shows the
# raw counts either way, but flags the percentage as unreliable under
# this threshold rather than presenting a confident-looking number.
MIN_RELIABLE_SAMPLE = 10


def _is_empty(value) -> bool:
    return value is None or value == "" or value == []


def _field_accuracy_for_type(
    draft_type: str | None,
    field_path_prefix: str,
    fields: list[str],
    days: int,
    strip_ordinal: bool,
) -> dict[str, dict]:
    """draft_type=None means "across every draft type" -- needed for
    signature fields, which get extracted regardless of whether the
    email turned out to be a job requirement, a hotlist, or anything
    else (app/email_parsing/signature.py runs unconditionally).
    """
    with cursor() as cur:
        if draft_type is None:
            cur.execute(
                "SELECT count(*) AS n FROM drafts WHERE created_at > now() - (%s || ' days')::interval",
                (days,),
            )
        else:
            cur.execute(
                "SELECT count(*) AS n FROM drafts WHERE draft_type = %s AND created_at > now() - (%s || ' days')::interval",
                (draft_type, days),
            )
        total_drafts = cur.fetchone()["n"]

        if draft_type is None:
            cur.execute(
                """
                SELECT fp.field_path, fp.extractor, fp.value_kind, fp.raw_value, fp.confidence
                FROM field_provenance fp
                JOIN drafts d ON d.draft_id::text = fp.parse_run_id
                WHERE fp.field_path LIKE %s
                  AND fp.recorded_at > now() - (%s || ' days')::interval
                """,
                (f"{field_path_prefix}%", days),
            )
        else:
            cur.execute(
                """
                SELECT fp.field_path, fp.extractor, fp.value_kind, fp.raw_value, fp.confidence
                FROM field_provenance fp
                JOIN drafts d ON d.draft_id::text = fp.parse_run_id
                WHERE d.draft_type = %s
                  AND fp.field_path LIKE %s
                  AND fp.recorded_at > now() - (%s || ' days')::interval
                """,
                (draft_type, f"{field_path_prefix}%", days),
            )
        rows = cur.fetchall()

    per_field = {
        field: {"filled": 0, "corrected_wrong": 0, "corrected_missing": 0, "confidence_sum": 0.0}
        for field in fields
    }

    for row in rows:
        suffix = row["field_path"][len(field_path_prefix):]
        if strip_ordinal:
            # "consultant.<ordinal>.<field>" -- the ordinal already served
            # its purpose (keeping distinct consultants' rows from
            # colliding); accuracy groups across all consultants by field
            # name alone.
            parts = suffix.split(".", 1)
            field = parts[1] if len(parts) == 2 else None
        else:
            field = suffix

        if field not in per_field:
            continue

        bucket = per_field[field]

        if row["extractor"] in CORRECTION_EXTRACTORS:
            if _is_empty(row["raw_value"]):
                bucket["corrected_missing"] += 1
            else:
                bucket["corrected_wrong"] += 1
        elif row["value_kind"] != "UNKNOWN":
            bucket["filled"] += 1
            bucket["confidence_sum"] += row["confidence"] or 0.0

    results: dict[str, dict] = {}

    for field, bucket in per_field.items():
        filled = bucket["filled"]
        corrected_wrong = bucket["corrected_wrong"]
        precision_denominator = filled  # filled already excludes empty originals
        precision = (
            round(100 * max(0, filled - corrected_wrong) / precision_denominator, 1)
            if precision_denominator > 0
            else None
        )
        fill_rate = round(100 * filled / total_drafts, 1) if total_drafts > 0 else None
        avg_confidence = round(100 * bucket["confidence_sum"] / filled, 1) if filled > 0 else None
        # Positive means Hermes is systematically MORE confident than it
        # turns out to be correct (overconfident, the dangerous
        # direction -- a wrong value gets less scrutiny from a reviewer
        # who trusts the confidence score). Negative means underconfident
        # -- annoying but safe.
        calibration_gap = (
            round(avg_confidence - precision, 1) if avg_confidence is not None and precision is not None else None
        )

        results[field] = {
            "field": field,
            "total_drafts": total_drafts,
            "filled_count": filled,
            "fill_rate": fill_rate,
            "corrected_wrong_count": corrected_wrong,
            "corrected_missing_count": bucket["corrected_missing"],
            "precision": precision,
            "false_positive_rate": round(100 - precision, 1) if precision is not None else None,
            "avg_stated_confidence": avg_confidence,
            "calibration_gap": calibration_gap,
            "reliable": precision_denominator >= MIN_RELIABLE_SAMPLE,
        }

    return results


def compute_accuracy_summary(days: int = 30) -> dict:
    job_fields = _field_accuracy_for_type(
        draft_type="draft_job_requirement",
        field_path_prefix="job.",
        fields=JOB_REQUIREMENT_FIELDS,
        days=days,
        strip_ordinal=False,
    )
    hotlist_fields = _field_accuracy_for_type(
        draft_type="draft_hotlist",
        field_path_prefix="consultant.",
        fields=HOTLIST_CONSULTANT_FIELDS,
        days=days,
        strip_ordinal=True,
    )
    signature_fields = _field_accuracy_for_type(
        draft_type=None,
        field_path_prefix="signature.",
        fields=SIGNATURE_FIELDS,
        days=days,
        strip_ordinal=False,
    )

    def _sort(fields: dict[str, dict]) -> list[dict]:
        return sorted(fields.values(), key=lambda f: (f["precision"] is None, f["precision"] or 0))

    return {
        "days": days,
        "job_requirement_fields": _sort(job_fields),
        "hotlist_fields": _sort(hotlist_fields),
        "signature_fields": _sort(signature_fields),
    }
