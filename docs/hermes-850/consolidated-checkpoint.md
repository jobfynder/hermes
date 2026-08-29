# HERMES-850 Email Intelligence Upgrade — Consolidated Checkpoint

Status: Complete, deployed to production
Branch history: feature/hermes-850-landing-db, feature/hermes-850-llm-fallback,
feature/hermes-850-self-learning, feature/hermes-850-core-push,
feature/hermes-review-frontend (all merged to main)
Server: jobfynder-intel-01 (167.71.217.230), service `/opt/hermes`

---

## Goal

Answer one question: how do we make the email parser reliably tell hotlists
apart from job requirements, catch what the deterministic parser misses,
learn from corrections over time, get parsed jobs onto the job board, and
give a human a real tool to check the work — without touching Core's
production deployment.

Rules carried over from earlier phases, still true:

- Deterministic parsing first. LLM is a fallback, not the default path.
- Every parsed field keeps provenance: was it extracted deterministically,
  filled by the LLM, or corrected by a recruiter.
- Hermes code always goes to `main`. Core code only ever goes to Core's
  `features` branch — Core's production server was never touched this
  phase.

---

## Completed

### 1. Landing database (Postgres)

Parsed drafts used to live in JSONL files on disk. That broke down across
two processes (`hermes-api` and `hermes-graph-consumer`) and made
concurrent access unsafe. Replaced with a dedicated `hermes-postgres`
Docker service — its own database, not shared with Core.

Tables: `drafts`, `field_provenance`, `email_claims`, `content_hash_index`,
`idempotency_keys`, `intake_log`, `classification_feedback`, `core_pushes`.

Old JSONL data was imported once via `hermes-landing-db-import-jsonl.py`
(safe to re-run, skips rows already imported).

Fixed along the way: a dedupe bug where duplicate-detection was cached in
memory per-process (so the consumer and API could each think a duplicate
email was new), and a bug in the claim service where `expires_at` was
silently dropped on update.

### 2. LLM fallback

Deterministic parsing still runs first and is still free. When it can't
find enough fields, or hotlist confidence is low, Hermes now calls the
existing audited LLM path (same LiteLLM/Langfuse setup and prompts used
elsewhere — `jf.jobs.jd.extract` for job requirements,
`jf.broadcast.hotlist.extract` for hotlists). No new prompts were created.

Rules:

- Job requirements: LLM only fills fields that are still empty. It never
  overwrites something the deterministic parser already found.
- Hotlists: below a confidence threshold (0.70), the LLM's record list
  replaces the deterministic one, since a hotlist is a full record, not a
  handful of independent fields.
- Every LLM-filled field is tagged in provenance as `llm_fallback`, so a
  reviewer can see exactly which fields to double check.

### 3. Self-learning classification

Some senders send only hotlists, some only job requirements, but their
subject lines don't always say so clearly. Hermes now remembers: when a
recruiter reclassifies a draft (hotlist to job requirement, or the other
way), that correction is recorded against the sender's domain.

Once a domain has 2+ corrections in the same direction, that becomes a
bias Hermes uses — but only to break a genuine tie in confidence. It never
overrides a parse the deterministic parser or LLM was already confident
about.

### 4. Push to Jobfynder Core (job board)

When a draft is published, Hermes now also tries to push it to Core as a
real job, via `POST /hermes/job/create` (shared-secret auth, same pattern
Hermes already used for other Core calls).

This is best-effort: if Core is unreachable or rejects the payload,
publishing in Hermes still succeeds — the push result (`pushed`,
`skipped`, or `failed`, with a reason) is recorded on the draft's metadata
and in a dedicated `core_pushes` table, so nothing is silently lost.

Jobs sourced this way are attributed to a fixed Hermes Sourcing system
user in Core (`hermes-sourcing@jobfynder.com`), a real claimed account —
not an "unclaimed contact" — so the job shows up correctly owned in
Core's directory and search.

Caught in testing: Cloudflare's WAF was blocking these calls with a 403
because Python's default HTTP User-Agent looks like a bot. Fixed by
sending a real `User-Agent` header. Confirmed live against Core.

Core-side change (branch `features` only, **not deployed to Core
production**): `POST /hermes/job/create` now accepts a full parsed-job
payload and a `sourceType: 'EMAIL'`, and creates the job through Core's
normal job-creation service instead of a stripped-down path.

### 5. Review frontend

Replaced the old single-file `draft-review.html` page with a proper
frontend: Vite + React + TypeScript + Tailwind, served at `/review`.

What it shows for each draft:

- The parsed job or hotlist fields, each one tagged with where it came
  from (deterministic, LLM, or recruiter correction)
- The detected email signature, if any
- The raw source email, collapsible
- The claim record, if a recruiter link was sent — including exactly what
  they corrected (before/after)
- The Core push result, if the draft was published
- Publish / Reject / Reclassify actions, wired to the real API

Backend additions this needed, now live: `created_at`/`updated_at` on
drafts, `GET /drafts/{id}/provenance`, `GET /drafts/{id}/claim`.

Packaging: a multi-stage Dockerfile builds the frontend with Node and
copies the build output into the same image FastAPI already ships, so
there's still just one container to deploy.

---

## Current Endpoints (new/changed this phase)

- GET /review — serves the new frontend (was a static HTML page)
- GET /drafts/{id}/provenance
- GET /drafts/{id}/claim
- POST /drafts/{id}/reclassify

---

## Validation

Every change in this phase went through the same pipeline: isolated git
worktree, throwaway Postgres + Docker network, full `hermes-850-*.py`
regression suite run against a freshly reset schema, then commit, backup
branch, `main`, redeploy, health check, cleanup. Zero regressions, zero
unplanned restarts in production across the whole phase.

Check scripts (all passing):

- hermes-850-claim-check.py
- hermes-850-core-job-push-check.py
- hermes-850-dedupe-check.py
- hermes-850-email-integration-check.py
- hermes-850-email-llm-fallback-check.py
- hermes-850-email-parsing-check.py
- hermes-850-provenance-check.py
- hermes-850-review-endpoints-check.py
- hermes-850-self-learning-classification-check.py
- hermes-850-sender-resolution-check.py

---

## Current State

Hermes now has a real database instead of files on disk, catches more
real emails through the LLM fallback without giving up the
deterministic-first guarantee, gets smarter about hotlist-vs-job over
time per sender, pushes published jobs onto the Jobfynder job board
automatically, and has a review tool a non-engineer can actually use to
check the parser's work.

Core's production server is unchanged. The Core-side endpoint upgrade
that Hermes' push relies on is live only on Core's `features` branch —
Core production is still running the older `main` build, so
`core_push.status` will currently come back `failed` (endpoint rejects
the fuller payload) until Core deploys `features` to production. Hermes
handles that gracefully already (best-effort, recorded, never blocks
publish).

---

## Next

Not done this phase, worth planning separately:

1. Deploy Core's `features` branch to Core production — a decision for
   the Core/product owner, not something Hermes can or should do on its
   own. Until then, the Core push feature is built and tested but not
   actually landing jobs on the live board.
2. Tune signature parsing against more real forwarded emails. The user
   offered to forward test emails for this specifically; that offer
   hasn't been followed up on yet.
3. Watch the self-learning classification in production for a few weeks
   — the 2-correction threshold was a starting guess, not tuned against
   real recruiter behavior yet.
