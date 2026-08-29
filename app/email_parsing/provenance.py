import json
from typing import Any

from app.runtime.db import cursor


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


def build_signature_provenance(signature: dict[str, Any]) -> list[dict[str, Any]]:
    '''Field-level provenance for app/email_parsing/signature.py's output,
    one row per extracted contact field -- same shape as
    build_job_requirement_provenance/build_hotlist_provenance above, keyed
    under "signature.<field>" instead of "job."/"consultant.<n>.".
    '''
    if not signature.get('detected'):
        return []

    extractor = signature.get('parser', {}).get('name', 'hermes_email_signature_parser')
    entries: list[dict[str, Any]] = []

    for field_name, field_data in signature.get('contact', {}).items():
        if not isinstance(field_data, dict):
            continue

        entries.append(
            _entry(
                f'signature.{field_name}',
                field_data.get('raw'),
                extractor=extractor,
                extraction_method=field_data.get('method', 'deterministic'),
                confidence=float(field_data.get('confidence', 0.0)),
                source_region=field_data.get('source'),
            )
        )
        entries[-1]['normalized_value'] = field_data.get('value')

    return entries


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
    if not entries:
        return

    with cursor() as cur:
        cur.executemany(
            '''
            INSERT INTO field_provenance (
                parse_run_id, field_path, raw_value, normalized_value,
                source_region, extractor, extraction_method, confidence, value_kind
            ) VALUES (
                %(parse_run_id)s, %(field_path)s, %(raw_value)s, %(normalized_value)s,
                %(source_region)s, %(extractor)s, %(extraction_method)s, %(confidence)s, %(value_kind)s
            )
            ''',
            [
                {
                    'parse_run_id': parse_run_id,
                    'field_path': entry['field_path'],
                    'raw_value': (
                        entry['raw_value'] if isinstance(entry.get('raw_value'), str) or entry.get('raw_value') is None
                        else json.dumps(entry['raw_value'], default=str)
                    ),
                    'normalized_value': json.dumps(entry.get('normalized_value'), default=str),
                    'source_region': entry.get('source_region'),
                    'extractor': entry['extractor'],
                    'extraction_method': entry['extraction_method'],
                    'confidence': entry['confidence'],
                    'value_kind': entry['value_kind'],
                }
                for entry in entries
            ],
        )


def load_field_provenance(parse_run_id: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            'SELECT parse_run_id, field_path, raw_value, normalized_value, source_region, '
            'extractor, extraction_method, confidence, value_kind, recorded_at '
            'FROM field_provenance WHERE parse_run_id = %s ORDER BY id',
            (parse_run_id,),
        )
        rows = cur.fetchall()

    for row in rows:
        row['recorded_at'] = row['recorded_at'].isoformat()

    return rows


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
