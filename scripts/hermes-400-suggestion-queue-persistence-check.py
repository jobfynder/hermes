from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.understanding.taxonomy import suggestion_store
from app.understanding.taxonomy.normalizer import normalize_skill, normalize_job_title
from app.understanding.taxonomy.suggestions import build_taxonomy_suggestions


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_fuzzy_hint_attached_without_skipping_review() -> None:
    result = build_taxonomy_suggestions(
        skills=['React Js'],
        job_titles=[],
        source_context='fuzzy-test',
    )

    suggestions = result['suggestions']
    require(len(suggestions) == 1, 'React Js should still create exactly one suggestion')

    suggestion = suggestions[0]
    require(suggestion['status'] == 'review_required', 'fuzzy-matched term must still require review')
    require(suggestion['fuzzy_match'] is not None, 'React Js should get a fuzzy_match hint against React/ReactJS')
    require(
        suggestion['fuzzy_match']['candidate_canonical_value'] == 'React',
        f"expected fuzzy hint to point at React, got {suggestion['fuzzy_match']}",
    )


def test_persisted_queue_deduplicates_and_counts_occurrences() -> None:
    for _ in range(3):
        build_taxonomy_suggestions(
            skills=['Quantum ML Framework'],
            job_titles=[],
            source_context='dedup-test',
        )

    queue = suggestion_store.list_suggestions(status='review_required')
    matches = [item for item in queue if item.observed_term == 'Quantum ML Framework']

    require(len(matches) == 1, 'the same unknown term must collapse into one queue entry, not three')
    require(matches[0].occurrence_count == 3, f'expected occurrence_count=3, got {matches[0].occurrence_count}')
    require(matches[0].source_contexts == ['dedup-test'], 'duplicate source_context should not be appended twice')


def test_approve_makes_the_term_normalize_immediately() -> None:
    build_taxonomy_suggestions(
        skills=['Snowflake DBT Pipeline'],
        job_titles=[],
        source_context='approve-test',
    )

    before = normalize_skill('Snowflake DBT Pipeline')
    require(before['matched'] is False, 'term must be unmatched before approval')

    suggestion_id = 'skill__snowflake dbt pipeline'.replace(' ', '_')
    approved = suggestion_store.approve_suggestion(suggestion_id, reviewed_by='test-reviewer')
    require(approved is not None, 'approve_suggestion must find the persisted record')
    require(approved.status == 'approved', 'status must become approved')

    after = normalize_skill('Snowflake DBT Pipeline')
    require(after['matched'] is True, 'approved term must now normalize as matched, with no restart')
    require(after['normalized'] == 'Snowflake DBT Pipeline', 'approved term should normalize to itself as a new canonical skill')


def test_reject_leaves_normalizer_unaffected() -> None:
    build_taxonomy_suggestions(
        skills=['Nonsense Skill Xyz'],
        job_titles=[],
        source_context='reject-test',
    )

    suggestion_id = 'skill__nonsense_skill_xyz'
    rejected = suggestion_store.reject_suggestion(suggestion_id, reviewed_by='test-reviewer', note='not a real skill')
    require(rejected is not None, 'reject_suggestion must find the persisted record')
    require(rejected.status == 'rejected', 'status must become rejected')

    after = normalize_skill('Nonsense Skill Xyz')
    require(after['matched'] is False, 'rejected term must remain unmatched')


def test_pinned_legacy_contract_unchanged() -> None:
    result = build_taxonomy_suggestions(
        skills=['JavaScript', 'ReactJS', 'Vector Database', 'Vector Database'],
        job_titles=['SRE', 'Prompt Engineer'],
        source_context='step-014-test',
    )

    require(result['result_version'] == 'hermes_taxonomy_suggestion_queue_v1', 'result_version must be unchanged')
    require(result['accepted_count'] == 0, 'accepted_count must remain 0 - legacy contract')

    observed = {(str(i['suggestion_type']), str(i['observed_term'])) for i in result['suggestions']}
    require(('skill', 'JavaScript') not in observed, 'known skill must not be suggested')
    require(('skill', 'ReactJS') not in observed, 'known alias must not be suggested')
    require(('job_title', 'SRE') not in observed, 'known title alias must not be suggested')

    for suggestion in result['suggestions']:
        require(suggestion['status'] == 'review_required', 'legacy contract: status must be review_required')
        require(suggestion['confidence'] == 'low', 'legacy contract: confidence must be low')


def run() -> None:
    tests = [
        test_fuzzy_hint_attached_without_skipping_review,
        test_persisted_queue_deduplicates_and_counts_occurrences,
        test_approve_makes_the_term_normalize_immediately,
        test_reject_leaves_normalizer_unaffected,
        test_pinned_legacy_contract_unchanged,
    ]

    for test in tests:
        test()
        print(f'PASS: {test.__name__}')

    print('PASS: HERMES-400 taxonomy suggestion queue persistence + fuzzy hint checks')


if __name__ == '__main__':
    run()
