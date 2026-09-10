# Review parsing repair

The September 2026 review backlog contained valid postings whose titles were missed because of a leading dot in .NET, parentheses, missing role keywords, or hiring prefixes. Some single postings were split at screening steps or contact roles, creating incomplete records. The parser now handles those title formats, recovers labeled table/body headings, and validates section boundaries after stripping relay banners and signoffs. Explicit Any Visa text is retained.

POST /drafts/backfill/jobs supports kind `review-reparse`. It snapshots only job requirement drafts currently in needs_review, excluding human corrections. The existing durable worker parses outside write transactions, commits bounded batches, records item outcomes, checks concurrent edits, and supports pause/resume/cancel. This operation does not publish jobs. Existing full-reparse and signature-company-fill jobs remain valid.

Validation: regression suite including synthetic relay, .NET, Designer, SDET, blank form fields, screening lists, recruiter signatures, genuine multi-job emails, and review-only selection. Read-only production preview confirms the supplied example parses without review warnings. Preserve unresolved records for further diagnosis; do not lower completeness thresholds.

Rollback: keep prior images for API, Graph consumer, and backfill worker. Pause active repair jobs before rollback. The additive kind constraint remains compatible with older job kinds; older workers must not resume a review-reparse job.
