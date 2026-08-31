# SOP — Recruiter Email Data Quality (Multi-Position Emails & Freemail Senders)

Status: Active
Owns: how Hermes handles two known-tricky real-world email patterns without
silently guessing wrong data onto the live Jobfynder job board.

---

## Why this doc exists

Hermes now sits directly in front of the live Jobfynder site — a published
job requirement goes to Core's job board, not to a private staging area.
Two real patterns showed up in production traffic that the parser wasn't
built for, and got it wrong in ways a reviewer wouldn't necessarily catch
by eye: multiple job positions bundled into one email, and recruiters
sending through personal (freemail) addresses instead of a company domain.
This is the standing policy for both, and the rule to follow when a new
variant of either shows up.

---

## 1. Multiple positions in one email

**What it looks like:** a recruiter (often via a job-board relay like
jobs.nvoids.com) lists several open roles in one email, usually as a
numbered list:

```
1) Power Platform Developer
   Sacramento, CA
   - Power Apps, Dataverse, Power Automate, SharePoint

2) Power BI Developer / BI Consultant
   Sacramento, CA
   - Power BI dashboards, data modeling, reporting/analytics
```

**What Hermes does (as of `feat/multi-position-email-parsing`):**

- A numbered list starting at `1)` with 2+ items is detected and split into
  **separate job requirement records**, one per position, each reviewable
  and publishable independently.
- Each record gets its own title (pulled from the first line of its own
  numbered item) and its own job description/skills, scoped to just that
  position's text — never a mix of all positions.
- A field one position states but another leaves blank (location is the
  common case, when it's written once for the whole list) is filled in
  from whichever position in the same email did state it. Nothing is
  invented if *no* position in the email has it.
- The relay's boilerplate footer ("Keywords: ...", "View this job online",
  "Happy recruiting", the resend-of-the-subject-line) is bounded out at the
  email's signoff marker (`--`) and never leaks into any position's job
  description.
- These go through **deterministic parsing only** — the LLM fallback never
  runs on a multi-position result. It was built to patch one job's missing
  fields, not to disentangle several jobs bundled together; sending it a
  multi-position email risks it silently merging or hallucinating across
  positions. A multi-position email with gaps stays multiple honestly-
  incomplete records for a human to fill in, not one LLM-smoothed guess.

**Reviewer's job:** each position shows up as its own draft on the review
page. Check each one on its own merits — a wrong field on position 2
doesn't mean positions 1 and 3 are also wrong, and correcting one doesn't
touch the others.

**What still needs a human, deliberately:** a numbered list is the only
format currently detected. A multi-position email that instead uses bullet
points (`•`), separator lines (`===`), or plain paragraph breaks between
positions still comes through as one combined record today. If this shows
up as a recurring pattern, treat it the same way the numbered-list case was
handled: get a real example, confirm the failure mode, add a detector —
don't try to guess a generic "detect any kind of list" rule up front.

---

## 2. Recruiters sending from freemail addresses

**What it looks like:** the sender's email is `@gmail.com`, `@yahoo.com`,
`@outlook.com`, `@hotmail.com`, or another shared public provider, instead
of a company domain (`@acmestaffing.com`).

**Why this matters:** a sender *domain* only reliably identifies one
company when it's a real corporate domain. A shared provider is used by
thousands of unrelated people — treating "gmail.com" as if it belonged to
one company is how a real incident happened: one recruiter's corrected
name/title/company got auto-applied to 806 other drafts from completely
different recruiters who also happen to use gmail.com.

**What Hermes does:**

- **No cross-email pattern learning for freemail domains.** The signature
  learning system (`app/email_parsing/signature_learning.py`) that lets a
  reviewer's correction auto-fill the same gap on a sender's *next* email
  never records or applies anything for a domain on the freemail list —
  every email from a freemail sender is judged purely on its own content,
  every time.
- **No inferring a company name from the domain string itself.** A
  heuristic like turning `abcstaffing.com` into "Abcstaffing" was
  deliberately not built — it's unreliable and it's moot for freemail
  senders anyway (`gmail.com` obviously isn't a company name). If the
  email's own text states a company, the deterministic parser or LLM
  fallback finds it there; if it doesn't, `company` stays blank and the
  record correctly requires review rather than presenting a guess as fact.
- **Company name (and other identity fields) missing is expected and
  correct**, not a bug, when a freemail sender's email genuinely never
  states a company. Don't try to force-fill it from the domain.

**Reviewer's job:** treat any identity field (recruiter name, title,
company) on a freemail-sourced draft as unverified until the email's own
content actually supports it. A blank company field here is the system
being honest, not broken.

**The freemail domain list** lives in `_FREEMAIL_DOMAINS`
(`app/email_parsing/signature_learning.py`) — currently gmail, yahoo,
outlook, hotmail, live, msn, aol, icloud, me.com, protonmail, gmx, ymail,
rediffmail. Extend it there if a new shared provider shows up in traffic;
never remove a domain from it to "unlock" learning for a specific sender.

---

## General principle behind both

**Uncertain data goes to review, it is never silently guessed onto the
live site.** Every fix in this doc adds a new way to *correctly extract
more* real information (splitting positions apart, learning a confirmed
correction for a real company domain) — none of them add a new way to
*infer* information that isn't actually in the email. When those two goals
conflict, correctness wins and the field stays blank for a human to fill
in.
