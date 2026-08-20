from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.understanding.taxonomy import suggestion_store
from app.understanding.taxonomy.normalizer import normalize_skill
from app.understanding.taxonomy.suggestions import build_taxonomy_suggestions


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_near_duplicate_auto_approves_and_normalizes_immediately() -> None:
    before = normalize_skill('Postgre SQL')
    require(before['matched'] is False, 'Postgre SQL must be unmatched before auto-approval')

    result = build_taxonomy_suggestions(
        skills=['Postgre SQL'],
        job_titles=[],
        source_context='auto-approve-test',
    )

    require(result['accepted_count'] == 1, f"expected accepted_count=1, got {result['accepted_count']}")
    require(len(result['suggestions']) == 0, 'auto-approved term must not appear in the review queue')
    require(len(result['auto_approved']) == 1, 'auto-approved term must appear in the auto_approved list')
    require(
        result['auto_approved'][0]['suggested_canonical_value'] == 'PostgreSQL',
        f"expected auto-approval to resolve to React, got {result['auto_approved'][0]}",
    )

    after = normalize_skill('Postgre SQL')
    require(after['matched'] is True, 'Postgre SQL must normalize immediately after auto-approval, no restart')
    require(after['normalized'] == 'PostgreSQL', f"expected normalized=PostgreSQL, got {after['normalized']}")


def test_auto_approved_suggestion_is_persisted_with_audit_trail() -> None:
    suggestion_id = suggestion_store.suggestion_id_for('skill', 'postgre sql')
    record = suggestion_store.get_suggestion(suggestion_id)

    require(record is not None, 'auto-approved suggestion must still be persisted for audit purposes')
    require(record.status == 'approved', 'persisted record must show status=approved')
    require(record.reviewed_by == 'hermes_auto_fuzzy_match', 'reviewed_by must identify this as system-approved, not a human')
    require(record.resolved_canonical_value == 'PostgreSQL', 'resolved_canonical_value must be recorded')


def test_genuinely_new_term_still_requires_review() -> None:
    result = build_taxonomy_suggestions(
        skills=['Some Totally Novel Skill Nobody Has'],
        job_titles=[],
        source_context='no-fuzzy-match-test',
    )

    require(result['accepted_count'] == 0, 'a genuinely novel term must not be auto-approved')
    require(len(result['suggestions']) == 1, 'a genuinely novel term must still create exactly one review-required suggestion')
    require(result['suggestions'][0]['status'] == 'review_required', 'status must be review_required')


def test_pinned_legacy_contract_still_unchanged() -> None:
    result = build_taxonomy_suggestions(
        skills=['JavaScript', 'ReactJS', 'Vector Database', 'Vector Database'],
        job_titles=['SRE', 'Prompt Engineer'],
        source_context='step-014-test',
    )

    require(result['result_version'] == 'hermes_taxonomy_suggestion_queue_v1', 'result_version must be unchanged')
    require(result['accepted_count'] == 0, 'none of the pinned fixtures are near-duplicates - accepted_count must be 0 for this call')

    observed = {(str(i['suggestion_type']), str(i['observed_term'])) for i in result['suggestions']}
    require(('skill', 'Vector Database') in observed, 'Vector Database must still require review (not a near-duplicate of anything)')
    require(('job_title', 'Prompt Engineer') in observed, 'Prompt Engineer must still require review')
    require(('skill', 'JavaScript') not in observed, 'known skill must not be suggested')
    require(('skill', 'ReactJS') not in observed, 'known alias must not be suggested')

    for suggestion in result['suggestions']:
        require(suggestion['status'] == 'review_required', 'legacy contract: status must be review_required')
        require(suggestion['confidence'] == 'low', 'legacy contract: confidence must be low')


def run() -> None:
    tests = [
        test_near_duplicate_auto_approves_and_normalizes_immediately,
        test_auto_approved_suggestion_is_persisted_with_audit_trail,
        test_genuinely_new_term_still_requires_review,
        test_pinned_legacy_contract_still_unchanged,
    ]

    for test in tests:
        test()
        print(f'PASS: {test.__name__}')

    print('PASS: HERMES-400 taxonomy near-duplicate auto-approval checks')


if __name__ == '__main__':
    run()
