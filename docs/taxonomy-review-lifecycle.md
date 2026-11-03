# Taxonomy and boilerplate review lifecycle

This document is the operational contract for Hermes taxonomy learning. The Chrome extension and email ingestion may discover evidence, but they never publish a new skill or global boilerplate rule automatically.

## New skill from the Chrome extension

1. The user chooses **Add to Jobfynder review**.
2. Core enforces the per-user weekly quota and sends a stable, idempotent request to Hermes.
3. Hermes deterministically normalizes, rejects obvious noise, checks the canonical names and every governed alias, and consolidates duplicates in `taxonomy_candidates`.
4. The pending row is visible immediately under **Blocklist & taxonomy → Taxonomy candidates**. The page refreshes every 15 seconds and also has **Refresh queues**.
5. A permitted human reviewer edits, approves, or rejects the term.
6. Approval updates the writable canonical taxonomy and invalidates matcher caches immediately. No restart or redeploy is required.

Repeated submissions never consume another unique-term quota slot. Core still reconciles a repeated queued term with Hermes so a restored or replaced Hermes database cannot leave a permanent “queued but invisible” record.

## Existing skill enrichment

Requests for missing definitions, recruiter explanations, aliases, relationships, or related roles are consolidated by canonical skill. They appear under **Skill enrichment requests**. Complete the governed fields in the taxonomy before approval; approval never invents missing content.

## Boilerplate patterns

Hermes records only eligible recurring lines and consolidates identical evidence. A boilerplate candidate becomes review-visible only after the same line is observed from at least eight distinct sender domains. It appears under **Boilerplate patterns**. Human approval is mandatory because approval removes that exact line from future parsed requirements. Approved rules take effect immediately through cache invalidation.

## What is automatic

- deterministic canonical and alias matching
- noise rejection and duplicate consolidation
- evidence counts and source-domain aggregation
- candidate and enrichment queue refresh
- cache invalidation after an approved taxonomy or boilerplate change

## What is deliberately not automatic

- adding a skill to the canonical taxonomy
- approving an enrichment request
- globally stripping a new boilerplate line
- publishing any extension capture to Pulse, the network, or a job record

These remain human-governed actions. LLM assistance may prepare or categorize review material, but it is not an approval authority.

## Operational verification

- Pending skills/job titles/boilerplate: `GET /taxonomy-candidates?status=pending`
- Pending enrichment: `GET /taxonomy-enrichment-requests?status=pending`
- Canonical taxonomy: `GET /understanding/taxonomy/skills/page`
- Queue health and triage history: the Hermes Reports page

If the extension reports `queued` but a new-skill row is absent, verify that Core contains the reconciliation fix using the stable `extension-crowdseed:<id>` request reference, then submit the same term once more. Hermes will recreate the missing candidate without using another quota slot.
