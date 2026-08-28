# Task: HERMES Email Signature Parser (deterministic)

Build a deterministic Email Signature Parser as part of the existing Hermes
email parsing engine (`app/email_parsing/`). Do **not** create a separate
service, a new architecture, or an LLM-based extractor. Reuse this
repo's existing parser pipeline, conventions, schemas, logging, and
observability.

The parser must **not** call an LLM for normal signature extraction.

## 0. Grounding — read this before writing code

This brief was written after inspecting the actual repo, not from a spec
in isolation. Confirm these are still accurate before starting (things
move):

- **Integration point**: `app/channels/service.py`, function
  `process_channel_intake()`, around lines 280-292. It currently does:
  ```python
  if request.channel == "email":
      email_parsing = parse_email_business_records(
          text=request.text or "",
          document_kind=document_kind,
      )
      structured_data["email_parsing"] = email_parsing
  ```
  Signature parsing should hook in right after this, adding a sibling
  `structured_data["signature"]` key — see Phase 7 for the exact shape.
  Do not restructure this function beyond what's needed to call the new
  signature parser.

- **Existing module to extend**: `app/email_parsing/`
  - `parsers.py` — `parse_hotlist_email`, `parse_requirement_email`,
    `parse_email_business_records`, `classify_email_by_confidence`. Add
    a new `signature.py` (or similarly named module) alongside these,
    not a new top-level package.
  - `provenance.py` — `_entry()` builds one provenance row
    (`field_path`, `raw_value`, `normalized_value`, `source_region`,
    `extractor`, `extraction_method`, `confidence`, `value_kind`).
    `build_job_requirement_provenance` / `build_hotlist_provenance` are
    the pattern to follow for a new `build_signature_provenance()`.
    Provenance rows are persisted via `record_field_provenance()` into
    `runtime/provenance/{parse_run_id}.jsonl` — reuse this, don't build
    a parallel store.
  - `sender_resolver.py` — already does forwarded-header detection
    (`looks_forwarded`, `resolve_original_sender`,
    `_FORWARD_MARKER_RE`), infra-address filtering
    (`_INFRA_ADDRESS_MARKERS`), and a public `find_body_contact_email()`.
    **Reuse this directly** for Phase 5 (cross-check against
    `From:`/authoritative sender) and Phase 1 (excluding forwarded
    headers / quoted blocks) — do not reimplement forward detection.
  - `dedupe.py` — exact-content duplicate detection at the *message*
    level (sha256 of full body, via `app/runtime/jsonl_store.py`). This
    is a different concern from Phase 6 (ignoring a signature that
    reappears inside quoted history *within one message*) — Phase 6
    needs new in-message logic, not a call into this module. If you do
    need message-level dedupe of extracted signature contacts across
    messages, follow the same `jsonl_store.append_jsonl`/`read_jsonl`
    pattern this module uses, don't invent a new persistence layer.

- **Parser metadata convention**: every parser in this module exposes a
  `PARSER_METADATA = {"name": ..., "version": ..., "uses_llm": False}`
  dict (see top of `parsers.py`, `sender_resolver.py`). The signature
  parser must do the same, e.g.
  `"name": "hermes_email_signature_parser"`, and it must always report
  `"uses_llm": False`.

- **Confidence/review threshold convention**: existing parsers use
  `0.70` as the `requires_review` cutoff and log which fields are
  missing as `warnings` entries. Match this unless there's a strong
  reason not to (say so if you deviate).

- **Observability convention**: there is no separate metrics system.
  Observability is `app/runtime/events.py::emit_event(event_type,
  payload)`, appended to `runtime/events/events.jsonl`. Phase 9's
  metrics (`signatures_detected`, `extraction_success_by_field`, etc.)
  should be emitted as `emit_event()` calls with a consistent
  `event_type` prefix (e.g. `signature.detected`,
  `signature.extraction_failed`), not a new metrics module.

- **Two gaps you'll hit immediately — resolve before Phase 10/11**:
  1. `requirements.txt` (repo root) has no phone-parsing library. Add
     `phonenumbers` there if you use it for Phase 2/3 phone
     normalization.
  2. There is currently **no `tests/` directory and no pytest config**
     anywhere in this repo (checked — none exists). Phase 10's fixture
     suite is new test infrastructure, not an addition to something
     existing. Before writing fixtures, decide and state the test
     runner/layout (e.g. `tests/email_parsing/test_signature.py` with
     pytest) — this is a call worth surfacing back to the requester
     before generating 20+ fixture files against a runner that doesn't
     exist yet.

## Objective

Detect an email sender's signature block and convert it into normalized
structured contact data, as a deterministic (non-LLM) step in the
existing pipeline:

```
raw email -> existing email parser -> body cleanup -> signature detection
-> field extraction -> normalization -> confidence scoring
-> existing Hermes parsed output (structured_data["signature"])
```

## Phase 1 — Signature block detection

Detect likely signature boundaries using deterministic rules, including
sign-off markers: `--`, `Thanks`, `Thank you`, `Regards`, `Best`,
`Best regards`, `Kind regards`, `Sincerely`, `Warm regards`, `Cheers`,
`Respectfully`.

Also detect signatures with no sign-off phrase, using structural
patterns near the bottom of the email: name, job title, company,
phone/mobile, email, URL, LinkedIn, address/location.

Exclude:
- quoted previous emails (reuse `sender_resolver._FORWARD_MARKER_RE` /
  `looks_forwarded()` as a starting point for detecting the boundary
  where quoted/forwarded content begins)
- forwarded message headers
- confidentiality notices / legal disclaimers
- unsubscribe text
- social-media boilerplate
- tracking URLs
- marketing footers

Preserve the original detected block verbatim as `signature_raw`.

## Phase 2 — Field extraction

Extract where available: `full_name`, `first_name`, `middle_name`,
`last_name`, `job_title`, `department`, `company_name`, `email`,
`phone`, `mobile`, `extension`, `website`, `linkedin_url`, `address`,
`city`, `state`, `postal_code`, `country`, other social links.

Use deterministic techniques only: regex, this repo's existing
NER/taxonomy where applicable (`app/understanding/parsers/contact.py`
already exists — check it before writing a new name/contact regex set
from scratch), `phonenumbers` for phone parsing, email validation, URL
normalization, title taxonomy, company-name heuristics, line-position
context.

Do not infer fields that are not present in the text.

## Phase 3 — Normalize

- emails -> lowercase
- phone numbers -> E.164 where possible (via `phonenumbers`)
- URLs -> canonical form; LinkedIn URLs normalized
- whitespace / Unicode normalized
- title formatting normalized
- US state names/codes normalized where safely identifiable

Preserve both original and normalized values.

## Phase 4 — Confidence scoring

Every extracted field carries `value`, `confidence`, `source` (line or
span), and `extraction method` — mirror the shape `provenance.py`
already uses (`_entry()`), don't invent a parallel schema. Example:

```json
{
  "phone": {
    "value": "+12145551234",
    "raw": "(214) 555-1234",
    "confidence": 0.99,
    "method": "phone_regex",
    "source": "M: (214) 555-1234"
  }
}
```

Never silently guess a value with no textual basis.

## Phase 5 — Existing email data takes precedence

Cross-check signature data against authoritative email metadata (the
`From:` header / `request.sender`, and `sender_resolver.py`'s
`resolve_original_sender()` for the forwarded case). If the signature
lists a different email address than the authoritative sender, retain
both, distinguished as `sender_email` vs `signature_email`. Never
overwrite authoritative header identity with lower-confidence signature
data.

## Phase 6 — Deduplication

Prevent a signature that repeats inside quoted history *within the same
message* from producing duplicate contacts. Parse only the current
(top) message's signature by default. Support parsing historical
signatures as an explicit opt-in parameter, disabled by default — do
not enable it in the default `process_channel_intake()` path.

## Phase 7 — Wire into Hermes output

Extend `structured_data` (already computed in
`process_channel_intake()`) with a `signature` key sibling to the
existing `email_parsing` key:

```json
{
  "signature": {
    "detected": true,
    "raw": "...",
    "contact": {},
    "confidence": 0.91
  }
}
```

This must be additive — existing consumers reading
`structured_data["email_parsing"]` or the rest of
`ChannelIntakeResponse` must see no schema break. If `signature.detected`
is `false`, still emit the key with an empty/null `contact` rather than
omitting it, so downstream consumers don't need an `in` check.

## Phase 8 — Guardrails

- No LLM calls.
- No external enrichment API calls.
- Never treat disclaimer/legal footer text as contact data.
- Never create a person merely because a name occurs somewhere in the
  body.
- Never let signature data overwrite header-derived sender identity.
- Never discard raw source values (`signature_raw` always preserved).
- Never hallucinate a field that isn't textually present.

## Phase 9 — Observability

Emit via `app/runtime/events.py::emit_event()` (see Grounding above),
one event type per counter: `signatures_detected`,
`signatures_not_detected`, `extraction_success_by_field`,
`extraction_failure_by_field`, `low_confidence_signatures`,
`disclaimer_removed`, `quoted_signature_ignored`, `parser_latency`.
Every emitted payload for this feature should make it obvious
`llm_calls: 0` — either as an explicit field or by construction (no
LLM/Portkey/LiteLLM client import anywhere in this module).

## Phase 10 — Tests

Resolve the "no tests directory exists yet" gap first (see Grounding).
Then build a fixture suite covering at least: plain-text signature,
HTML signature, recruiter signature, consultant signature,
staffing-company signature, Gmail signature, Outlook signature,
signature with logo/images, phone + extension, multiple phone numbers,
international phone, LinkedIn, website, postal address, no signature,
short signature, confidentiality disclaimer, long legal disclaimer,
forwarded email, replied email, nested email thread, "Sent from my
iPhone", signature containing another email address, malformed HTML.

Include regression tests proving `parse_email_business_records()` /
`process_channel_intake()` behavior for hotlist and job_description
emails is unchanged by this addition.

## Phase 11 — Benchmark

Build a benchmark from sanitized real Jobfynder emails (ask the
requester for a source/location — none is checked into this repo).
Track precision/recall for: signature detection, name, title, company,
email, phone, LinkedIn.

Production gate: email extraction precision >= 99%, phone precision
>= 98%, signature-block detection precision >= 95%, zero regressions in
existing `email_parsing` behavior, zero LLM calls.

## Deliverables, in order

Before modifying production code:
1. Confirm the Grounding section above is still accurate (files move).
2. Identify the exact integration point (should still be
   `app/channels/service.py::process_channel_intake`).
3. List files to be added/modified.
4. Propose the `structured_data["signature"]` schema (Phase 7) precisely,
   field by field.
5. List reusable existing utilities you'll call into (expect at least
   `sender_resolver.py`, `provenance.py`'s `_entry()` pattern, and
   `app/understanding/parsers/contact.py` if it's applicable).
6. Flag anything already implemented that must not be duplicated.

Then implement in small commits. Do not create new infrastructure
beyond what Phase 10 requires. Do not refactor unrelated Hermes
modules. Do not add an LLM fallback without explicit approval from the
requester.

## Recommended extension (not required to ship v1, but design for it)

Don't treat this as only a signature parser — its normalized output is
a candidate **Contact Identity** record for Jobfynder's
recruiter/company network:

```
Recruiter sends job email
        |
Hermes parses job + Hermes parses signature
        |
Recruiter identity: John Smith / ABC Staffing / john@abc.com /
214-555-1234 / LinkedIn...
        |
match against existing Jobfynder person/company
        |
attach provenance: "Observed in email signature"
```

Do **not** automatically create a new Jobfynder Person/Company from a
signature. Match against existing records first; store an unmatched
identity as provisional contact data only. This is a downstream
consumer of `structured_data["signature"]`, not something this task's
parser itself should implement — flag the matching/dedup step as a
follow-up rather than building it inline here.
