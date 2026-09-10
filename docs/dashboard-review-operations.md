# Dashboard performance and review reconciliation

The parsed-email dashboard requests `/drafts/page`, which performs filtering,
search, counts, and pagination in PostgreSQL. Page size defaults to 50 and is
bounded at 200. Only fields needed by the table are returned. Search is
debounced and prior requests are cancelled; hidden tabs do not auto-refresh.
The legacy summary endpoint remains available for compatibility.

Production read-only measurements on September 10, 2026: the old list returned
15,117 visible records, about 20.35 MB, in 2.69 seconds before browser overhead.
The new first page returned 50 records, about 27 KB, in 0.34 seconds. The
needs-review page took 0.31 seconds; a Java search took 1.16 seconds.

`POST /drafts/review/reconcile-ready` requires drafts:publish permission and
defaults to dry_run=true. It only repairs stale needs_review statuses when
both intake and parser confidence meet the existing threshold, all records
are clear, there are no warnings/errors, the document kind matches, and no
human correction exists. No records are published. The previous status and
rule are recorded in draft metadata in the same transaction as the repair.

Missing company or candidate names are not fabricated. The existing review
rules remain in force unless the owner explicitly approves a policy change.
