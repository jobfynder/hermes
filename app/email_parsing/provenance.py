from datetime import UTC, datetime
from typing import Any

from app.runtime.jsonl_store import append_jsonl, read_jsonl, runtime_path


def _provenance_path(parse_run_id: str):
    return runtime_path('provenance', f'{parse_run_id}.jsonl')


# Which parser-output keys become provenance rows, per document kind. Names
# match this codebase's actual parser record fields (app/email_parsing/
# parsers.py), not the spec doc's job.title_raw-style naming -- tracking
# real field names is more useful than matching a doc that was written
# before this parser existed.
JOB_REQUIREMENT_FIELDS = [
    'job_title',
    'job_description',
    'required_skills',
    'preferred_skills',
    'years_of_experience',
    'location',
    'work_authorization',
    'employment_type',
    'rate_or_salary',
]

HOTLIST_CONSULTANT_FIELDS = [
    'candidate_name',
    'candidate_email',
    'candidate_phone',
    'primary_job_title',
    'primary_skills',
    'years_of_experience',
    'current_location',
    'work_authorization',
    'availability',
    'expected_rate',
]


def _value_kind(value: Any) -> str:
    if value is None or value == '' or value == []:
        return 'UNKNOWN'
    return 'EXTRACTED'


def _entry(
    field_path: str,
    value: Any,
    *,
    extractor: str,
    extraction_method: str,
    confidence: float,
    source_region: str | None = None,
) -> dict[str, Any]:
    return {
        'field_path': field_path,
        'raw_value': value,
        'normalized_value': value,
        'source_region': source_region,
        'extractor': extractor,
        'extraction_method': extraction_method,
        'confidence': confidence,
        'value_kind': _value_kind(value),
    }


def build_job_requirement_provenance(record: dict[str, Any], extractor: str) -> list[dict[str, Any]]:
    confidence = float(record.get('parse_confidence', 0.0))
    return [
        _entry(f'job.{field}', record.get(field), extractor=extractor, extraction_method='deterministic', confidence=confidence)
        for field in JOB_REQUIREMENT_FIELDS
    ]


def build_hotlist_provenance(record: dict[str, Any], extractor: str) -> list[dict[str, Any]]:
    ordinal = record.get('source_row') or record.get('source_block') or 0
    confidence = float(record.get('parse_confidence', 0.0))
    return [
        _entry(
            f'consultant.{ordinal}.{field}',
            record.get(field),
            extractor=extractor,
            extraction_method='deterministic',
            confidence=confidence,
        )
        for field in HOTLIST_CONSULTANT_FIELDS
    ]


def build_email_parsing_provenance(email_parsing: dict[str, Any]) -> list[dict[str, Any]]:
    '''Fan out one parse_email_business_records() result into field-level
    provenance entries across all of its records (spec section 10).
    '''
    document_kind = email_parsing.get('document_kind')
    extractor = email_parsing.get('parser', {}).get('name', 'hermes_email_deterministic_parser')
    entries: list[dict[str, Any]] = []

    for record in email_parsing.get('records', []):
        if document_kind == 'job_description':
            entries.extend(build_job_requirement_provenance(record, extractor))
        elif document_kind == 'hotlist':
            entries.extend(build_hotlist_provenance(record, extractor))

    return entries


def record_field_provenance(parse_run_id: str, entries: list[dict[str, Any]]) -> None:
    path = _provenance_path(parse_run_id)
    now = datetime.now(UTC).isoformat()

    for entry in entries:
        append_jsonl(path, {'parse_run_id': parse_run_id, 'recorded_at': now, **entry})


def load_field_provenance(parse_run_id: str) -> list[dict[str, Any]]:
    return read_jsonl(_provenance_path(parse_run_id))


def record_recruiter_correction(
    parse_run_id: str,
    field_path: str,
    before: Any,
    after: Any,
) -> dict[str, Any]:
    '''A claimed listing's recruiter-submitted correction becomes a new
    provenance row rather than overwriting the original deterministic/
    LLM-fallback entry -- this is the free accuracy-labeling signal the
    claim loop exists to produce (spec section 11.2): compare extractor
    output against extractor="recruiter_correction" rows over enough
    claimed records and you know which fields the parser gets wrong.
    '''
    entry = _entry(
        field_path,
        after,
        extractor='recruiter_correction',
        extraction_method='deterministic',
        confidence=1.0,
    )
    entry['raw_value'] = before
    record_field_provenance(parse_run_id, [entry])
    return entry
