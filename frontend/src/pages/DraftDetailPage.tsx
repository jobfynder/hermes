import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import { ConfidenceMeter } from '../components/ConfidenceMeter'
import { draftTypeLabel } from '../components/DraftTypeLabel'
import { FieldRow } from '../components/FieldRow'
import { StatusBadge } from '../components/StatusBadge'
import type {
  DraftObject,
  DraftObjectType,
  EmailClaim,
  EmailParsingResult,
  FieldProvenanceEntry,
  HotlistConsultantRecord,
  JobRequirementRecord,
  SignatureResult,
} from '../types'

const JOB_FIELDS: [string, keyof JobRequirementRecord][] = [
  ['Job title', 'job_title'],
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

  useEffect(load, [draftId])

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
        {actionMessage && <span className="text-sm text-ink-soft">{actionMessage}</span>}
      </div>

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

          {claim && (
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
            </Card>
          )}

          {draft.metadata.core_push && (
            <Card title="Jobfynder Core">
              <FieldRow label="Push status" value={draft.metadata.core_push.status} />
              {draft.metadata.core_push.core_job_url ? (
                <FieldRow label="Job listing" value={draft.metadata.core_push.core_job_url} />
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
