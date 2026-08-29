"""Hermes landing database (spec: parsed emails, drafts, claims, and
provenance live in a database owned by Hermes, separate from Jobfynder
Core's database -- nothing reaches Core until an explicit push step;
see docs/hermes-architecture-frozen-v1.md section 2, "Hermes proposes,
Core executes").

Replaces the earlier JSONL-files-under-/hermes-runtime storage (app/
drafts/service.py, app/claim/service.py, app/email_parsing/provenance.py,
app/email_parsing/dedupe.py, app/runtime/intake_log.py all wrote there
directly) with a real Postgres database, so parsed emails can actually be
tracked, searched, and reported on instead of living only as files on
disk. A one-time import of any pre-existing JSONL data into this schema
lives in scripts/hermes-landing-db-import-jsonl.py.
"""

from __future__ import annotations

import contextlib
import json
import os
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL", "")

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Lazily-created, process-wide connection pool. Lazy so importing
    this module never requires a live database (unit tests, scripts that
    don't touch the DB) -- the pool only opens on first real use."""
    global _pool

    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set -- the Hermes landing database is required "
                "for drafts/claims/provenance storage. See .env.example."
            )
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=True)

    return _pool


@contextlib.contextmanager
def cursor() -> Iterator[Any]:
    """Yields a dict-row cursor inside its own transaction -- commits on
    clean exit, rolls back on exception. This is the only way the rest
    of the codebase touches the database; nothing holds a connection
    open across a request."""
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur


SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    draft_id            UUID PRIMARY KEY,
    draft_type          TEXT NOT NULL,
    status              TEXT NOT NULL,
    source              TEXT NOT NULL,
    source_ref          TEXT,
    channel             TEXT,
    source_message_id   TEXT,
    title               TEXT,
    summary             TEXT,
    payload             JSONB NOT NULL DEFAULT '{}',
    normalized_skills    JSONB NOT NULL DEFAULT '[]',
    normalized_job_titles JSONB NOT NULL DEFAULT '[]',
    taxonomy_signals    JSONB NOT NULL DEFAULT '{}',
    confidence          DOUBLE PRECISION NOT NULL DEFAULT 0,
    requires_review     BOOLEAN NOT NULL DEFAULT TRUE,
    errors              JSONB NOT NULL DEFAULT '[]',
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_drafts_draft_type ON drafts (draft_type);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts (status);
CREATE INDEX IF NOT EXISTS idx_drafts_channel ON drafts (channel);
CREATE INDEX IF NOT EXISTS idx_drafts_created_at ON drafts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_drafts_source_message_id ON drafts (source_message_id);

CREATE TABLE IF NOT EXISTS field_provenance (
    id                  BIGSERIAL PRIMARY KEY,
    parse_run_id        TEXT NOT NULL,
    field_path          TEXT NOT NULL,
    raw_value           TEXT,
    normalized_value    JSONB,
    source_region       TEXT,
    extractor           TEXT NOT NULL,
    extraction_method   TEXT NOT NULL,
    confidence          DOUBLE PRECISION NOT NULL,
    value_kind          TEXT NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_provenance_parse_run_id ON field_provenance (parse_run_id);
CREATE INDEX IF NOT EXISTS idx_provenance_extractor ON field_provenance (extractor);
CREATE INDEX IF NOT EXISTS idx_provenance_field_path ON field_provenance (field_path);

CREATE TABLE IF NOT EXISTS email_claims (
    claim_id                UUID PRIMARY KEY,
    draft_id                UUID NOT NULL REFERENCES drafts (draft_id),
    token                   TEXT NOT NULL UNIQUE,
    status                  TEXT NOT NULL,
    recruiter_email         TEXT NOT NULL,
    recruiter_name          TEXT,
    resolution_method       TEXT NOT NULL,
    resolution_confidence   DOUBLE PRECISION NOT NULL,
    prefilled_fields        JSONB NOT NULL DEFAULT '{}',
    correction_diff         JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at                 TIMESTAMPTZ,
    claimed_at               TIMESTAMPTZ,
    published_at            TIMESTAMPTZ,
    expires_at              TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_draft_id ON email_claims (draft_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON email_claims (status);

CREATE TABLE IF NOT EXISTS content_hash_index (
    body_hash       TEXT PRIMARY KEY,
    duplicate_key   TEXT NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key             TEXT PRIMARY KEY,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS intake_log (
    id              BIGSERIAL PRIMARY KEY,
    duplicate_key   TEXT NOT NULL,
    channel         TEXT NOT NULL,
    source_message_id TEXT,
    status          TEXT NOT NULL,
    detail          JSONB NOT NULL DEFAULT '{}',
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_intake_log_duplicate_key ON intake_log (duplicate_key);
CREATE INDEX IF NOT EXISTS idx_intake_log_recorded_at ON intake_log (recorded_at DESC);

-- Self-learning classification feedback: every recruiter correction to
-- document_kind (via claim confirm) becomes a row here, keyed by sender
-- domain so future confidence-gate decisions for that domain can be
-- biased by real outcomes instead of starting cold every time.
CREATE TABLE IF NOT EXISTS classification_feedback (
    id                      BIGSERIAL PRIMARY KEY,
    draft_id                UUID NOT NULL,
    sender_domain           TEXT,
    sender_email            TEXT,
    predicted_document_kind TEXT NOT NULL,
    corrected_document_kind TEXT NOT NULL,
    predicted_confidence    DOUBLE PRECISION NOT NULL,
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_classification_feedback_domain ON classification_feedback (sender_domain);

-- Tracks whether/when a PUBLISHED draft was pushed to Jobfynder Core's
-- job board (POST /hermes/job/create). One row per push attempt so a
-- retry after a failure is visible, not silently overwritten.
CREATE TABLE IF NOT EXISTS core_pushes (
    id              BIGSERIAL PRIMARY KEY,
    draft_id        UUID NOT NULL REFERENCES drafts (draft_id),
    status          TEXT NOT NULL,
    core_job_id     TEXT,
    core_job_url    TEXT,
    error           TEXT,
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_core_pushes_draft_id ON core_pushes (draft_id);

-- Sender blocklist (HERMES-900 spam/volume control): a domain or exact
-- email address a human has explicitly decided to stop hearing from.
-- Checked at the very top of channel intake (app/channels/service.py) --
-- a match means the message is logged to intake_log and discarded before
-- a draft is ever created, so blocking a noisy sender actually reduces
-- review-queue clutter instead of just tagging it after the fact. A
-- domain entry (email IS NULL) blocks every address at that domain; an
-- email entry blocks only that one address, even if its domain isn't
-- otherwise blocked.
CREATE TABLE IF NOT EXISTS sender_blocklist (
    id              BIGSERIAL PRIMARY KEY,
    match_type      TEXT NOT NULL CHECK (match_type IN ('domain', 'email')),
    value           TEXT NOT NULL,
    reason          TEXT,
    source_draft_id UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_blocklist_match ON sender_blocklist (match_type, value);

-- Candidate skills/job titles seen in postings that don't match anything
-- in the taxonomy (app/understanding/taxonomy/canonical_skills.json /
-- job_titles.json). Accumulates occurrence_count across separate emails
-- so a one-off typo doesn't look the same as a real new tool name showing
-- up repeatedly across different senders -- reviewed and approved via
-- the taxonomy-candidates admin endpoints (app/routers/taxonomy_admin.py)
-- rather than added automatically, since an unreviewed addition can
-- silently corrupt matching for every future email.
CREATE TABLE IF NOT EXISTS taxonomy_candidates (
    id                  BIGSERIAL PRIMARY KEY,
    signal_type         TEXT NOT NULL CHECK (signal_type IN ('skill', 'job_title')),
    term                TEXT NOT NULL,
    normalized_term     TEXT NOT NULL,
    occurrence_count    INTEGER NOT NULL DEFAULT 1,
    distinct_senders    JSONB NOT NULL DEFAULT '[]',
    sample_draft_ids    JSONB NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at         TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_taxonomy_candidates_term ON taxonomy_candidates (signal_type, normalized_term);
CREATE INDEX IF NOT EXISTS idx_taxonomy_candidates_status ON taxonomy_candidates (status);
"""


def init_schema() -> None:
    with cursor() as cur:
        cur.execute(SCHEMA)


def to_jsonb(value: Any) -> str:
    """psycopg adapts Python dict/list to jsonb automatically when the
    column type is known from the table, but for ad hoc params (e.g.
    inside a CASE or a function call) an explicit json.dumps is safer
    than relying on adaptation guessing right."""
    return json.dumps(value, default=str)
