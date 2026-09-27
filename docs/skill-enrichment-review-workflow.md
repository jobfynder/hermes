# Skill taxonomy enrichment review

Known canonical skills may be missing recruiter-facing context. The Chrome extension can request any of these fields through Jobfynder Core: `definition`, `recruiter_explanation`, `aliases`, `relationships`, and `related_roles`.

Hermes stores each request in `taxonomy_enrichment_requests`. A request is evidence for review and cannot change matching or taxonomy output by itself.

## Review flow

1. `POST /skill-intelligence/suggestions` queues an `enrichment` request. Hermes removes fields already populated on the canonical card and merges repeated evidence into the one pending row for that skill.
2. `POST /taxonomy-enrichment-requests/{id}/generate` claims proposal generation. Hermes first fills any definition available in the deterministic glossary and derives related roles from governed job titles. It calls `jf.taxonomy.skill-enrichment.propose` through the existing prompt runtime only for fields still missing. The combined JSON result is stored as a proposal only.
3. A reviewer can correct the draft with `PUT /taxonomy-enrichment-requests/{id}/proposal`.
4. `POST /taxonomy-enrichment-requests/{id}/review` with `{"decision":"approved"}` applies the exact reviewed values. `{"decision":"rejected"}` closes the request without changing the taxonomy.

Both proposal generation and review endpoints require `drafts:publish`. Listing requests requires `drafts:read`.

## Enforcement

- One pending request exists per canonical skill. Request evidence is normalized under a unique `(request_id, request_ref)` key, so repeated request IDs do not increment evidence twice even after the bounded display preview is full.
- Fields already populated are not queued and are never overwritten during approval.
- A ready proposal is reused; concurrent generation is claimed once. A stale `generating` claim can be retried after ten minutes.
- Adding a newly requested field invalidates the older proposal so stale LLM output cannot be approved.
- Alias collisions with another canonical skill are rejected.
- Relationships accept only the controlled relationship vocabulary and must resolve to another existing canonical skill.
- Approval records the reviewer, approved values, apply result, prompt run, model, and field-level taxonomy provenance.
- LLM output never writes directly to `canonical_skills.json`. Only an authenticated human approval can apply it.

## New-skill crowdseeding

The extension presents crowdseed CTAs only for terms detected in page highlighting or the selected-text action card. Core enforces 100 unique normalized new-skill contributions per authenticated user per UTC week before calling Hermes. Repeated clicks for the same term do not consume another quota slot.

Hermes applies its deterministic noise, exact-known, loose-identity, and pending-candidate checks before recording evidence. A reviewer still approves or rejects the candidate. On approval, an explicit reviewer category wins; otherwise Hermes applies deterministic category rules and calls `jf.taxonomy.skill-candidate.classify` only when those rules cannot decide. The LLM must choose an existing category. Description generation follows the same deterministic-first, LLM-fallback order. No candidate becomes a published skill before the human approval action.
