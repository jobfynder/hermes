# Hermes Company Acquisition and Job Supply Engine

## Boundary and current state

Hermes owns source intake, normalization, provenance, company and recruiter resolution, job identity, activity scoring, and acquisition preparation. CORE receives only explicitly approved, verified records through an idempotent handoff. Discovery is not verification, a sender domain is not proof of employment, and an email requirement is not proof a job is still open.

The user confirmed there is no existing company list to import. The first company directory is now built from structured signature evidence in Hermes drafts. `hermes_companies` provides stable domain-grouped IDs; `company_observations` retains source-backed contacts and requirements; `company_projection_state` enables resumable deterministic discovery and correction updates. Every company starts unverified and unclaimed. Corporate domain grouping is observed evidence, not legal identity or proof of employment.

## Target data model

- `companies`: immutable company_id, canonical name, aliases, legal identifiers when available, claim status, verification status, first/last seen, and merge redirects.
- `company_domains`: normalized domain, company_id, domain role, verification evidence, and validity dates. Shared mail providers and relay domains are never identity anchors. Conflicting ownership produces a resolution case.
- `company_sources`: company_id, source type, permitted source URL, careers URL, ATS provider, sync policy, last successful sync and cursor. Source status is independent of company verification.
- `recruiters`: canonical recruiter_id and verified contact identities; company associations live in a separate table with evidence, confidence, valid dates, and proposed/confirmed/rejected status.
- `jobs`: canonical job_id and company_id, optional end_client_company_id, source requisition identifiers, normalized title/location/employment data, status, and freshness. Staffing agency and end client are separate relationships.
- `job_observations`: source identity, source record ID, payload hash, observed time, source job status, immutable provenance reference, and canonical job_id. Multiple observations may describe one job.
- `company_events`: append-only, idempotent activity observations. Corrections and retractions reference the original observation.
- `company_claims`: verified claimant identity, evidence of company authority, scope, status, and audit history. Email-domain possession alone does not authorize control over every related company.
- `core_handoffs`: approved object version, idempotency key, quality-gate result, delivery state, retries, and CORE identifiers.

## Deterministic resolution

1. Match a company by existing canonical ID, verified domain identity, or approved alias. Preserve unresolved observations when evidence conflicts. Names alone suggest a match; they do not silently merge companies.
2. Match recruiters by verified normalized email/identity. Store observed company affiliation as proposed until verified.
3. Match jobs by company plus authoritative source requisition ID. For cross-channel observations without that ID, use a versioned deterministic fingerprint of company, normalized title, location/work mode, employment type, and substantive description. Incomplete fingerprints and near matches go to a duplicate-review group; do not merge jobs merely because titles match.
4. Keep an immutable observation for every source. Reprocessing the same source version is a no-op. Edits update the canonical projection while retaining history.
5. Close a career-source observation only after an authoritative closure or a successful complete source scan with a configured grace period. A failed crawl never closes jobs. Source-specific closure does not override a fresh recruiter-confirmed posting.

## Processing order

Source -> deterministic parse -> signature and approved correction rules -> company resolution -> recruiter association -> job identity -> quality gates -> company graph projection -> explainable scoring -> acquisition queue -> verified claim -> approved CORE handoff.

Routine intake, backfills, deduplication, enrichment from known rules, scoring, and source reconciliation use no LLM. Only the final extraction fallback may use one after deterministic attempts fail; cache successful identical requests and retain review status when required fields remain missing.

## Activity and trust

Keep activity and trust separate. Activity is an explainable weighted score over unique, recent jobs, verified recruiter actions, source changes, responses, and later submissions/outcomes. Store component values, weight version, and calculation time. Repeated emails do not multiply job counts. Verification, source reliability, conflicting evidence, and stale information determine trust; high volume cannot buy verification.

## Delivery sequence and acceptance gates

1. Delivered: create the first source-backed directory from existing Hermes drafts. Shared email/relay domains and name-only mentions are excluded from automatic linking. The Companies page provides search, pagination, detail, activity components, and links to source drafts.
2. Delivered: continuously project new and corrected source drafts through the supervised worker, in bounded transactions, with no LLM calls. Observed contacts remain unverified. Future verification and company merge workflows must preserve immutable IDs and source evidence.
3. Add canonical jobs and multi-source observations; test cross-channel duplicates, changed requirements, stale observations, and separate agency/end-client identities.
4. Add approved ATS/career adapters with bounded polling, per-source checkpoints, retries, and complete-scan closure safeguards.
5. Add an internal acquisition queue with transparent activity/trust components and claim readiness. Invitations require an explicitly approved campaign; no outbound messaging is enabled merely by discovery.
6. Add verified company claiming and feed management. Only then enable an approved, idempotent CORE handoff behind explicit quality gates.

These engine components are a target design, not a claim that all have been implemented. Report performance, taxonomy duplicate prevention, and the source-backed Companies directory are delivered. Career/ATS connectors, invitations, verified company claims, canonical job lifecycle management, and CORE handoffs remain future stages.
