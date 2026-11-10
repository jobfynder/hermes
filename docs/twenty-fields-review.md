# Twenty CRM field review (2026-11-10)

Source of truth for "what Twenty holds": the sync's own schema definitions
(`/opt/jfcrm/runtime-20261104/twenty/{company,person,hiring-signal}-schema.mjs`). Which fields are actually
filled: measured on a random 6,000-event sample of the last 3 days of the sync's outbox. The live Twenty UI was
not inspected (no browser connection, and no CRM credentials were used).

## What is in use and healthy

| Object | Filled with real data on every event |
|---|---|
| Company | `companyType`, `workModel`, `firstObservedAt`, `lastObservedAt`, `requirements7d/30d/90d`, `activeRecruiterCount`, `knownRecruiterCount`, `primarySkills`, `primaryLocations` (about 73% have skills/locations) |
| Person (recruiter) | `firstObservedAt`, `lastObservedAt`, `requirements7d/30d/90d`, `primarySkills`, `primaryLocations` (about 99% / 97%) |
| Hiring signal | `signalType`, `source`, `sourceReference`, `observedAt`, `jobTitle`, `skills`, `location` (92%), `workMode`, `hermesConfidence` |

Scores and tiers (`gtmScore`, `gtmTier`, `companyHeat`, `recruiterScore`) are computed by the sync itself from these
inputs.

## Defined in Twenty but never filled by Hermes (clutter today)

- Company: `staffingType`, `linkedinUrl`, `requirementVelocity` (no calculation policy), `jobfynderCompanyId`,
  `jobfynderRegistered`, `jobfynderActiveRecruiters`, `jobfynderJobsPublished`, `networkPenetration`.
- Person: `recruiterType`, `activityStatus`, `gtmStatus` (free text, "allowed values are not yet defined"),
  `primaryWorkModel`, `jobfynderUserId`, `jobfynderRegistered`, `profileCompleted`, `firstJobPosted`, `activated`.
- Hiring signal: `status` (free text, no allowed values), `jobfynderDraftId`, `jobfynderJobId`.
- Human-managed (leave as is): `gtmLifecycle`, `gtmOwner`, `lastContactAt`, `nextAction`, `nextActionAt`, `nextFollowUpAt`.

Recommendation, to keep it simple: hide the never-filled fields from the Twenty views (a view setting, it does not
change the data model), and only start filling the `jobfynder*` fields when Jobfynder Core is the source for them.

## Biggest gap: the hiring signal has no commercial detail

Hermes now extracts, and the CRM team needs when deciding who to call, but a hiring signal in Twenty carries none of:

| Proposed field (HiringSignal) | Type | Source in Hermes |
|---|---|---|
| `employmentType` | SELECT: CONTRACT, CONTRACT_TO_HIRE, FULL_TIME, PART_TIME | `employment_type` (about 70% filled and rising; `employment_type_basis` says how it was derived) |
| `rateMin`, `rateMax` | NUMBER | `rate_min`, `rate_max` |
| `rateUnit` | SELECT: HOUR, DAY, MONTH, YEAR | `rate_unit` |
| `durationMonths` | NUMBER | `duration_months` |
| `jobfynderDraftId` (already exists) | TEXT | fill it with the Hermes draft id so a signal links back to its email |

Five small fields, all already extracted. Company-level roll-ups (for example "share of contract roles", "typical rate")
can be derived later from these without new Hermes work.

## Why none of this can be changed from Hermes

1. The sync **pins the complete GraphQL type of Company, Person and HiringSignal**
   (`pinned-sync-contract.mjs`). Adding or changing any field in Twenty makes it report
   `UNSUPPORTED_DESTINATION_DRIFT` and pause until the contract is re-pinned.
2. The runtime refuses to start if any of its files change without a re-signed activation approval
   (`RUNTIME_FINGERPRINT_NOT_APPROVED`).

So the order of work is: (a) create the fields in Twenty, (b) update `production-plan.mjs`/`payload.mjs` and the
pinned contract, (c) re-sign the approval, (d) restart. A field added in Twenty before (b) and (c) stops the sync.
This is a change for the sync owner to run end to end; it was not attempted from Hermes.
