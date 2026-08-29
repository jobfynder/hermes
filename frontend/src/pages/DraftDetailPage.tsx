import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import { ConfidenceMeter } from '../components/ConfidenceMeter'
import { draftTypeLabel } from '../components/DraftTypeLabel'
import { FieldRow } from '../components/FieldRow'
import { ProvenanceChip } from '../components/ProvenanceChip'
import { StatusBadge } from '../components/StatusBadge'
import type {
  ClaimPrepareResult,
  DraftObject,
  DraftObjectType,
  EmailClaim,
  EmailParsingResult,
  FieldProvenanceEntry,
  HotlistConsultantRecord,
  JobRequirementRecord,
  SignatureResult,
} from '../types'

const CLAIMABLE_TYPES: DraftObjectType[] = ['draft_job_requirement', 'draft_hotlist']

function claimLink(claim: Pick<EmailClaim, 'token'>): string {
  return `${window.location.origin}/claim/${claim.token}`
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

const JOB_FIELDS: [string, keyof JobRequirementRecord][] = [
  ['Job title', 'job_title'],
  ['Company', 'company'],
  ['Location', 'location'],
  ['Rate / salary', 'rate_or_salary'],
  ['Employment type', 'employment_type'],
  ['Work authorization', 'work_authorization'],
  ['Years of experience', 'years_of_experience'],
  ['Required skills', 'required_skills'],
  ['Preferred skills', 'preferred_skills'],
]

const HOTLIST_FIELDS: [string, keyof HotlistConsultantRecord][] = [
  ['Name', 'candidate_name'],
  ['Title', 'primary_job_title'],
  ['Skills', 'primary_skills'],
  ['Experience', 'years_of_experience'],
  ['Location', 'current_location'],
  ['Work authorization', 'work_authorization'],
  ['Availability', 'availability'],
  ['Rate', 'expected_rate'],
  ['Email', 'candidate_email'],
  ['Phone', 'candidate_phone'],
]

const RECLASSIFY_TARGETS: DraftObjectType[] = [
  'draft_job_requirement',
  'draft_hotlist',
  'draft_channel_note',
]

function provenanceMap(entries: FieldProvenanceEntry[]): Map<string, FieldProvenanceEntry> {
  const map = new Map<string, FieldProvenanceEntry>()
  for (const e of entries) map.set(e.field_path, e)
  return map
}

export function DraftDetailPage({ draftId, onBack }: { draftId: string; onBack: () => void }) {
  const [draft, setDraft] = useState<DraftObject | null>(null)
  const [provenance, setProvenance] = useState<FieldProvenanceEntry[]>([])
  const [claim, setClaim] = useState<EmailClaim | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [showRawText, setShowRawText] = useState(false)
  const [showJobDescription, setShowJobDescription] = useState(false)
  const [preparedClaim, setPreparedClaim] = useState<ClaimPrepareResult | null>(null)

  function load() {
    setError(null)
    Promise.all([api.getDraft(draftId), api.getProvenance(draftId), api.getClaim(draftId)])
      .then(([d, p, c]) => {
        setDraft(d)
        setProvenance(p)
        setClaim(c)
      })
      .catch((err) => setError(err.message ?? 'Failed to load draft'))
  }

  useEffect(() => {
    setPreparedClaim(null)
    setShowJobDescription(false)
    load()
  }, [draftId])

  const pmap = useMemo(() => provenanceMap(provenance), [provenance])

  const emailParsing = draft?.payload.structured_data as
    | { email_parsing?: EmailParsingResult; signature?: SignatureResult; text?: string }
    | undefined
  const parsing = emailParsing?.email_parsing
  const signature = emailParsing?.signature
  const rawText = (draft?.payload.text as string) ?? ''

  async function handlePublish() {
    setBusy(true)
    setActionMessage(null)
    try {
      const result = await api.publishDraft(draftId)
      setActionMessage(result.status === 'published' ? 'Published.' : `Could not publish: ${result.errors.join(', ')}`)
      load()
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Publish failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleReject() {
    const reason = window.prompt('Reason for rejecting this draft (optional):') ?? undefined
    setBusy(true)
    setActionMessage(null)
    try {
      await api.rejectDraft(draftId, reason)
      setActionMessage('Rejected.')
      load()
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Reject failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleReclassify(newType: DraftObjectType) {
    setBusy(true)
    setActionMessage(null)
    try {
      await api.reclassifyDraft(draftId, newType)
      setActionMessage(`Reclassified as ${draftTypeLabel(newType)}.`)
      load()
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Reclassify failed')
    } finally {
      setBusy(false)
    }
  }

  async function handlePrepareClaim() {
    setBusy(true)
    setActionMessage(null)
    try {
      const result = await api.prepareClaim(draftId)
      setPreparedClaim(result)
      if (result.status === 'blocked') {
        setActionMessage(`Could not prepare claim: ${result.errors.join(', ') || 'not eligible yet'}`)
      } else {
        setClaim(result.claim)
      }
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Prepare claim failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleCopyClaimLink(c: Pick<EmailClaim, 'token'>) {
    const ok = await copyToClipboard(claimLink(c))
    setActionMessage(ok ? 'Claim link copied.' : 'Could not copy — select and copy the link manually.')
  }

  async function handleMarkClaimSent(claimId: string) {
    setBusy(true)
    setActionMessage(null)
    try {
      const updated = await api.markClaimSent(claimId)
      setClaim(updated)
      setActionMessage('Marked as sent.')
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Mark as sent failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!window.confirm('Permanently delete this draft? This cannot be undone.')) return
    setBusy(true)
    setActionMessage(null)
    try {
      const result = await api.deleteDraft(draftId)
      if (result.deleted) {
        onBack()
      } else {
        setActionMessage(`Could not delete: ${result.reason ?? 'unknown reason'}`)
      }
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleBlockSender() {
    const senderEmail = draft?.metadata.sender?.email
    if (!senderEmail) {
      setActionMessage('This draft has no sender email to block.')
      return
    }
    const domain = senderEmail.split('@')[1] ?? senderEmail
    if (!window.confirm(`Block all future mail from ${domain}?`)) return
    setBusy(true)
    setActionMessage(null)
    try {
      const result = await api.blockDraftSender(draftId, 'domain')
      setActionMessage(result.blocked ? `Blocked ${result.value}.` : `Could not block: ${result.reason}`)
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Block sender failed')
    } finally {
      setBusy(false)
    }
  }

  if (error) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <button onClick={onBack} className="text-sm text-accent hover:underline">
          ← Back to list
        </button>
        <div className="mt-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>
      </div>
    )
  }

  if (!draft) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8 text-sm text-ink-soft">Loading…</div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <button onClick={onBack} className="text-sm text-accent hover:underline">
        ← Back to list
      </button>

      <header className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold text-ink">{draft.title || '(untitled)'}</h1>
            <StatusBadge status={draft.status} />
          </div>
          <p className="mt-1 text-sm text-ink-soft">
            {draftTypeLabel(draft.draft_type)} &middot; via {draft.channel ?? draft.source}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ConfidenceMeter value={draft.confidence} />
        </div>
      </header>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          disabled={busy || draft.status === 'published'}
          onClick={handlePublish}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
        >
          Publish
        </button>
        <button
          disabled={busy || draft.status === 'rejected'}
          onClick={handleReject}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fail transition hover:bg-fail-soft disabled:opacity-40"
        >
          Reject
        </button>
        {RECLASSIFY_TARGETS.filter((t) => t !== draft.draft_type).map((t) => (
          <button
            key={t}
            disabled={busy}
            onClick={() => handleReclassify(t)}
            className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-soft transition hover:text-ink disabled:opacity-40"
          >
            Mark as {draftTypeLabel(t)}
          </button>
        ))}
        <span className="mx-1 h-5 w-px bg-line" />
        <button
          disabled={busy || draft.status === 'published'}
          onClick={handleDelete}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fail transition hover:bg-fail-soft disabled:opacity-40"
        >
          Delete
        </button>
        <button
          disabled={busy || !draft.metadata.sender?.email}
          onClick={handleBlockSender}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-soft transition hover:text-ink disabled:opacity-40"
        >
          Block sender's domain
        </button>
        {actionMessage && <span className="text-sm text-ink-soft">{actionMessage}</span>}
      </div>

      {draft.status === 'spam' && draft.metadata.spam_reasons && draft.metadata.spam_reasons.length > 0 && (
        <div className="mt-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">
          Flagged as likely spam: {draft.metadata.spam_reasons.join(', ').replace(/_/g, ' ')}. Review below —
          reclassify it if this was a mistake, or delete it if it's junk.
        </div>
      )}

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {parsing && parsing.document_kind === 'job_description' && parsing.records.length > 0 && (
            <Card title="Parsed job requirement">
              {parsing.llm_fallback?.used && (
                <AiAssistNote fields={parsing.llm_filled_fields ?? []} />
              )}
              {JOB_FIELDS.map(([label, key]) => (
                <FieldRow
                  key={key}
                  label={label}
                  value={(parsing.records[0] as JobRequirementRecord)[key]}
                  provenance={pmap.get(`job.${key}`)}
                />
              ))}
              <div className="flex items-start justify-between gap-4 border-b border-line py-2.5 last:border-0">
                <span className="w-40 shrink-0 text-sm text-ink-soft">LinkedIn</span>
                <div className="flex-1">
                  {(parsing.records[0] as JobRequirementRecord).linkedin_url ? (
                    <a
                      href={(parsing.records[0] as JobRequirementRecord).linkedin_url ?? undefined}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm text-accent hover:underline"
                    >
                      {(parsing.records[0] as JobRequirementRecord).linkedin_url}
                    </a>
                  ) : (
                    <span className="text-sm text-ink-soft italic">—</span>
                  )}
                </div>
                <ProvenanceChip entry={pmap.get('job.linkedin_url')} />
              </div>
              <div className="flex items-start justify-between gap-4 border-b border-line py-2.5 last:border-0">
                <span className="w-40 shrink-0 text-sm text-ink-soft">Job description</span>
                <div className="flex-1">
                  {(parsing.records[0] as JobRequirementRecord).job_description ? (
                    <>
                      <button
                        onClick={() => setShowJobDescription((v) => !v)}
                        className="text-sm text-accent hover:underline"
                      >
                        {showJobDescription ? 'Hide' : 'Show'} full description
                      </button>
                      {showJobDescription && (
                        <pre className="scrollbar-thin mono mt-3 max-h-96 overflow-auto rounded-lg bg-paper p-3 text-xs whitespace-pre-wrap text-ink">
                          {(parsing.records[0] as JobRequirementRecord).job_description}
                        </pre>
                      )}
                    </>
                  ) : (
                    <span className="text-sm text-ink-soft italic">—</span>
                  )}
                </div>
                <ProvenanceChip entry={pmap.get('job.job_description')} />
              </div>
            </Card>
          )}

          {parsing && parsing.document_kind === 'hotlist' && parsing.records.length > 0 && (
            <Card title={`Hotlist — ${parsing.records.length} consultant${parsing.records.length === 1 ? '' : 's'}`}>
              {parsing.llm_fallback?.used && <AiAssistNote fields={['this entire hotlist split']} />}
              <div className="space-y-4">
                {(parsing.records as HotlistConsultantRecord[]).map((record, i) => (
                  <div key={i} className="rounded-lg border border-line p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-sm font-semibold text-ink">{record.candidate_name || `Consultant ${i + 1}`}</span>
                      <ConfidenceMeter value={record.parse_confidence} compact />
                    </div>
                    {HOTLIST_FIELDS.map(([label, key]) => (
                      <FieldRow
                        key={key}
                        label={label}
                        value={record[key]}
                        provenance={pmap.get(`consultant.${i + 1}.${key}`)}
                      />
                    ))}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {signature?.detected && (
            <Card title="Detected signature">
              {Object.entries(signature.contact).map(([field, data]) => (
                <FieldRow
                  key={field}
                  label={field.replace(/_/g, ' ')}
                  value={data.value}
                  provenance={pmap.get(`signature.${field}`)}
                />
              ))}
            </Card>
          )}

          <Card title="Raw email">
            <button
              onClick={() => setShowRawText((v) => !v)}
              className="text-sm text-accent hover:underline"
            >
              {showRawText ? 'Hide' : 'Show'} raw text
            </button>
            {showRawText && (
              <pre className="scrollbar-thin mono mt-3 max-h-96 overflow-auto rounded-lg bg-paper p-3 text-xs whitespace-pre-wrap text-ink">
                {rawText || '(no text captured)'}
              </pre>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Source">
            <FieldRow label="Channel" value={draft.channel} />
            <FieldRow label="Message ID" value={draft.source_message_id} />
            <FieldRow label="Sender" value={draft.metadata.sender?.email} />
            {draft.metadata.original_sender_candidate?.email && (
              <FieldRow
                label="Resolved sender"
                value={`${draft.metadata.original_sender_candidate.email} (${draft.metadata.original_sender_candidate.extraction_method})`}
              />
            )}
            {draft.metadata.exact_content_duplicate_of && (
              <FieldRow label="Duplicate of" value={draft.metadata.exact_content_duplicate_of} />
            )}
            {draft.metadata.rejection_reason && (
              <FieldRow label="Rejection reason" value={draft.metadata.rejection_reason} />
            )}
          </Card>

          {claim ? (
            <Card title="Claim & verify">
              <FieldRow label="Status" value={claim.status} />
              <FieldRow label="Recruiter" value={`${claim.recruiter_name ?? ''} ${claim.recruiter_email}`.trim()} />
              <FieldRow
                label="Resolution"
                value={`${claim.resolution_method} (${Math.round(claim.resolution_confidence * 100)}%)`}
              />
              <FieldRow label="Sent" value={claim.sent_at} />
              <FieldRow label="Claimed" value={claim.claimed_at} />
              <FieldRow label="Published" value={claim.published_at} />
              {claim.correction_diff && Object.keys(claim.correction_diff).length > 0 && (
                <div className="mt-2">
                  <p className="text-xs font-medium tracking-wide text-ink-soft uppercase">Recruiter corrections</p>
                  {Object.entries(claim.correction_diff).map(([field, diff]) => (
                    <div key={field} className="mt-1.5 text-sm">
                      <span className="text-ink-soft">{field}: </span>
                      <span className="text-fail line-through">{String(diff.before ?? '—')}</span>
                      {' → '}
                      <span className="text-pass">{String(diff.after ?? '—')}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={() => handleCopyClaimLink(claim)}
                  className="rounded-lg border border-line bg-paper px-3 py-1.5 text-xs font-medium text-ink-soft transition hover:text-ink"
                >
                  Copy claim link
                </button>
                {claim.status === 'PENDING_CLAIM' && !claim.sent_at && (
                  <button
                    disabled={busy}
                    onClick={() => handleMarkClaimSent(claim.claim_id)}
                    className="rounded-lg border border-line bg-paper px-3 py-1.5 text-xs font-medium text-ink-soft transition hover:text-ink disabled:opacity-40"
                  >
                    Mark link as sent
                  </button>
                )}
              </div>
            </Card>
          ) : (
            CLAIMABLE_TYPES.includes(draft.draft_type) && (
              <Card title="Claim & verify">
                <p className="text-sm text-ink-soft">
                  No claim link generated yet. Preparing one lets a recruiter open a prefilled
                  listing, correct anything wrong, and publish it themselves.
                </p>
                <button
                  disabled={busy}
                  onClick={handlePrepareClaim}
                  className="mt-3 rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
                >
                  Prepare claim link
                </button>
                {preparedClaim?.claim && preparedClaim.status !== 'blocked' && (
                  <div className="mt-3 space-y-2 rounded-lg border border-line bg-paper p-3">
                    <div className="flex items-center justify-between gap-2">
                      <code className="mono truncate text-xs text-ink">{claimLink(preparedClaim.claim)}</code>
                      <button
                        onClick={() => preparedClaim.claim && handleCopyClaimLink(preparedClaim.claim)}
                        className="shrink-0 rounded-lg border border-line bg-surface px-2.5 py-1 text-xs font-medium text-ink-soft transition hover:text-ink"
                      >
                        Copy
                      </button>
                    </div>
                    {preparedClaim.email_subject && (
                      <details className="text-xs text-ink-soft">
                        <summary className="cursor-pointer select-none">Preview email to send</summary>
                        <p className="mt-2 font-medium text-ink">{preparedClaim.email_subject}</p>
                        <pre className="mono mt-1 whitespace-pre-wrap text-ink-soft">{preparedClaim.email_body}</pre>
                      </details>
                    )}
                    <button
                      disabled={busy}
                      onClick={() => preparedClaim.claim && handleMarkClaimSent(preparedClaim.claim.claim_id)}
                      className="rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-soft transition hover:text-ink disabled:opacity-40"
                    >
                      Mark link as sent
                    </button>
                  </div>
                )}
              </Card>
            )
          )}

          {draft.metadata.core_push && (
            <Card title="Jobfynder Core">
              <FieldRow label="Push status" value={draft.metadata.core_push.status} />
              {draft.metadata.core_push.core_job_url ? (
                <a
                  href={draft.metadata.core_push.core_job_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-block text-sm text-accent hover:underline"
                >
                  View job listing →
                </a>
              ) : (
                <FieldRow label="Reason" value={draft.metadata.core_push.reason} />
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <h2 className="mb-2 text-sm font-semibold text-ink">{title}</h2>
      {children}
    </div>
  )
}

function AiAssistNote({ fields }: { fields: string[] }) {
  return (
    <div className="mb-3 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
      AI-assisted extraction filled in {fields.length ? fields.join(', ') : 'some fields'} — the parser alone
      wasn't confident enough on its own.
    </div>
  )
}
