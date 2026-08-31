import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { BlocklistEntry, TaxonomyCandidateEntry } from '../types'

function CandidateSection({
  title,
  description,
  emptyMessage,
  termLabel,
  showTypeColumn,
  candidates,
  busy,
  editingId,
  editValue,
  selectedIds,
  onStartEdit,
  onEditValueChange,
  onSaveEdit,
  onCancelEdit,
  onApprove,
  onReject,
  onToggleSelected,
  onToggleSelectAll,
  onBulkApprove,
  onBulkReject,
}: {
  title: string
  description: string
  emptyMessage: string
  termLabel: string
  showTypeColumn?: boolean
  candidates: TaxonomyCandidateEntry[]
  busy: boolean
  editingId: number | null
  editValue: string
  selectedIds: Set<number>
  onStartEdit: (c: TaxonomyCandidateEntry) => void
  onEditValueChange: (value: string) => void
  onSaveEdit: (id: number) => void
  onCancelEdit: () => void
  onApprove: (id: number) => void
  onReject: (id: number) => void
  onToggleSelected: (id: number) => void
  onToggleSelectAll: (ids: number[]) => void
  onBulkApprove: (ids: number[]) => void
  onBulkReject: (ids: number[]) => void
}) {
  const ids = candidates.map((c) => c.id)
  const selectedInSection = ids.filter((id) => selectedIds.has(id))

  return (
    <section className="mb-8 rounded-xl border border-line bg-surface p-5">
      <h2 className="mb-3 text-sm font-semibold text-ink">{title}</h2>
      <p className="mb-4 text-xs text-ink-soft">{description}</p>

      {candidates.length > 0 && (
        <div className="mb-3 flex items-center justify-between rounded-lg border border-line bg-paper px-3 py-2">
          <span className="text-xs text-ink-soft">
            {selectedInSection.length > 0 ? `${selectedInSection.length} selected` : 'Select rows to act on them in bulk'}
          </span>
          <div className="flex gap-3">
            <button
              disabled={busy || selectedInSection.length === 0}
              onClick={() => onBulkApprove(selectedInSection)}
              className="text-xs font-medium text-accent hover:underline disabled:opacity-40"
            >
              Approve selected
            </button>
            <button
              disabled={busy || selectedInSection.length === 0}
              onClick={() => onBulkReject(selectedInSection)}
              className="text-xs font-medium text-fail hover:underline disabled:opacity-40"
            >
              Reject selected
            </button>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-line">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
              <th className="w-8 px-3 py-2">
                {candidates.length > 0 && (
                  <input
                    type="checkbox"
                    checked={selectedInSection.length === ids.length}
                    onChange={() => onToggleSelectAll(ids)}
                    className="accent-accent"
                    aria-label="Select all"
                  />
                )}
              </th>
              {showTypeColumn && <th className="px-3 py-2 font-medium">Type</th>}
              <th className="px-3 py-2 font-medium">{termLabel}</th>
              <th className="px-3 py-2 font-medium">Seen</th>
              <th className="px-3 py-2 font-medium">Distinct senders</th>
              <th className="px-3 py-2 font-medium">Last seen</th>
              <th className="px-3 py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <tr key={c.id} className="border-b border-line last:border-0">
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(c.id)}
                    onChange={() => onToggleSelected(c.id)}
                    className="accent-accent"
                    aria-label={`Select ${c.term}`}
                  />
                </td>
                {showTypeColumn && (
                  <td className="px-3 py-2 text-xs text-ink-soft">
                    {c.signal_type === 'job_title' ? 'Job title' : 'Skill'}
                  </td>
                )}
                <td className="px-3 py-2 font-medium text-ink">
                  {editingId === c.id ? (
                    <input
                      autoFocus
                      value={editValue}
                      onChange={(e) => onEditValueChange(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') onSaveEdit(c.id)
                        if (e.key === 'Escape') onCancelEdit()
                      }}
                      className="w-full rounded border border-accent bg-paper px-2 py-1 text-sm text-ink outline-none"
                    />
                  ) : (
                    <span className="group inline-flex items-center gap-2">
                      {c.term}
                      <button
                        onClick={() => onStartEdit(c)}
                        className="text-xs font-normal text-ink-soft opacity-0 group-hover:opacity-100 hover:text-accent hover:underline"
                      >
                        Edit
                      </button>
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-ink-soft">{c.occurrence_count}×</td>
                <td className="max-w-56 truncate px-3 py-2 text-ink-soft">
                  {c.distinct_senders.length > 0 ? c.distinct_senders.join(', ') : '—'}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-ink-soft">
                  {new Date(c.last_seen_at).toLocaleDateString()}
                </td>
                <td className="px-3 py-2 text-right">
                  {editingId === c.id ? (
                    <div className="flex justify-end gap-3">
                      <button
                        disabled={busy || !editValue.trim()}
                        onClick={() => onSaveEdit(c.id)}
                        className="text-xs font-medium text-accent hover:underline disabled:opacity-40"
                      >
                        Save
                      </button>
                      <button
                        disabled={busy}
                        onClick={onCancelEdit}
                        className="text-xs font-medium text-ink-soft hover:underline disabled:opacity-40"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="flex justify-end gap-3">
                      <button
                        disabled={busy}
                        onClick={() => onApprove(c.id)}
                        className="text-xs font-medium text-accent hover:underline disabled:opacity-40"
                      >
                        Approve
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => onReject(c.id)}
                        className="text-xs font-medium text-fail hover:underline disabled:opacity-40"
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {candidates.length === 0 && (
              <tr>
                <td colSpan={showTypeColumn ? 7 : 6} className="px-3 py-6 text-center text-ink-soft">
                  {emptyMessage}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function ModerationPage({ onBack }: { onBack: () => void }) {
  const [blocklist, setBlocklist] = useState<BlocklistEntry[] | null>(null)
  const [candidates, setCandidates] = useState<TaxonomyCandidateEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [newValue, setNewValue] = useState('')
  const [newMatchType, setNewMatchType] = useState<'domain' | 'email'>('domain')
  const [newReason, setNewReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  function load() {
    setError(null)
    api.listBlocklist().then(setBlocklist).catch((err) => setError(err.message))
    api
      .listTaxonomyCandidates('pending')
      .then((list) => {
        setCandidates(list)
        setSelectedIds((prev) => {
          const stillPending = new Set(list.map((c) => c.id))
          return new Set([...prev].filter((id) => stillPending.has(id)))
        })
      })
      .catch((err) => setError(err.message))
  }

  useEffect(load, [])

  const taxonomyCandidates = useMemo(
    () => candidates?.filter((c) => c.signal_type === 'skill' || c.signal_type === 'job_title') ?? [],
    [candidates],
  )
  const boilerplateCandidates = useMemo(
    () => candidates?.filter((c) => c.signal_type === 'boilerplate_line') ?? [],
    [candidates],
  )

  async function handleAddBlock() {
    if (!newValue.trim()) return
    setBusy(true)
    try {
      await api.addBlock(newMatchType, newValue.trim(), newReason.trim() || undefined)
      setNewValue('')
      setNewReason('')
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add block')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemoveBlock(id: number) {
    setBusy(true)
    try {
      await api.removeBlock(id)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove block')
    } finally {
      setBusy(false)
    }
  }

  async function handleApprove(id: number) {
    setBusy(true)
    try {
      await api.approveTaxonomyCandidate(id)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve candidate')
    } finally {
      setBusy(false)
    }
  }

  async function handleReject(id: number) {
    setBusy(true)
    try {
      await api.rejectTaxonomyCandidate(id)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject candidate')
    } finally {
      setBusy(false)
    }
  }

  function startEdit(c: TaxonomyCandidateEntry) {
    setEditingId(c.id)
    setEditValue(c.term)
  }

  async function handleSaveEdit(id: number) {
    if (!editValue.trim()) return
    setBusy(true)
    try {
      await api.editTaxonomyCandidate(id, editValue.trim())
      setEditingId(null)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update term')
    } finally {
      setBusy(false)
    }
  }

  function toggleSelected(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll(ids: number[]) {
    setSelectedIds((prev) => {
      const allSelected = ids.every((id) => prev.has(id))
      const next = new Set(prev)
      ids.forEach((id) => (allSelected ? next.delete(id) : next.add(id)))
      return next
    })
  }

  async function handleBulkApprove(ids: number[]) {
    if (ids.length === 0) return
    setBusy(true)
    try {
      const result = await api.bulkApproveTaxonomyCandidates(ids)
      setActionMessage(
        result.failed.length === 0
          ? `Approved ${result.ok_count} candidates.`
          : `Approved ${result.ok_count}, ${result.failed.length} failed (already reviewed by someone else?).`,
      )
      setSelectedIds(new Set())
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk approve failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleBulkReject(ids: number[]) {
    if (ids.length === 0) return
    setBusy(true)
    try {
      const result = await api.bulkRejectTaxonomyCandidates(ids)
      setActionMessage(
        result.failed.length === 0
          ? `Rejected ${result.ok_count} candidates.`
          : `Rejected ${result.ok_count}, ${result.failed.length} failed (already reviewed by someone else?).`,
      )
      setSelectedIds(new Set())
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk reject failed')
    } finally {
      setBusy(false)
    }
  }

  const sharedSectionProps = {
    busy,
    editingId,
    editValue,
    selectedIds,
    onStartEdit: startEdit,
    onEditValueChange: setEditValue,
    onSaveEdit: handleSaveEdit,
    onCancelEdit: () => setEditingId(null),
    onApprove: handleApprove,
    onReject: handleReject,
    onToggleSelected: toggleSelected,
    onToggleSelectAll: toggleSelectAll,
    onBulkApprove: handleBulkApprove,
    onBulkReject: handleBulkReject,
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Blocklist &amp; taxonomy</h1>
          <p className="mt-1 text-sm text-ink-soft">
            Control which senders reach the review queue, and approve new skills before they affect matching.
          </p>
        </div>
        <button
          onClick={onBack}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-soft transition hover:text-ink"
        >
          Back to drafts
        </button>
      </header>

      {error && <div className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}
      {actionMessage && (
        <div className="mb-4 rounded-lg border border-line bg-paper px-4 py-3 text-sm text-ink-soft">
          {actionMessage}
        </div>
      )}

      <section className="mb-8 rounded-xl border border-line bg-surface p-5">
        <h2 className="mb-3 text-sm font-semibold text-ink">Sender blocklist</h2>
        <p className="mb-4 text-xs text-ink-soft">
          Mail from a blocked domain or address is discarded before it ever becomes a draft.
        </p>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <select
            value={newMatchType}
            onChange={(e) => setNewMatchType(e.target.value as 'domain' | 'email')}
            className="rounded-lg border border-line bg-paper px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent"
          >
            <option value="domain">Domain</option>
            <option value="email">Exact email</option>
          </select>
          <input
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            placeholder={newMatchType === 'domain' ? 'spamvendor.com' : 'someone@spamvendor.com'}
            className="min-w-56 rounded-lg border border-line bg-paper px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
          />
          <input
            value={newReason}
            onChange={(e) => setNewReason(e.target.value)}
            placeholder="Reason (optional)"
            className="min-w-40 flex-1 rounded-lg border border-line bg-paper px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
          />
          <button
            disabled={busy || !newValue.trim()}
            onClick={handleAddBlock}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
          >
            Block
          </button>
        </div>

        <div className="overflow-hidden rounded-lg border border-line">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Value</th>
                <th className="px-3 py-2 font-medium">Reason</th>
                <th className="px-3 py-2 font-medium">Blocked</th>
                <th className="px-3 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {blocklist?.map((b) => (
                <tr key={b.id} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 text-ink-soft">{b.match_type}</td>
                  <td className="px-3 py-2 font-medium text-ink">{b.value}</td>
                  <td className="px-3 py-2 text-ink-soft">{b.reason ?? '—'}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-ink-soft">
                    {new Date(b.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      disabled={busy}
                      onClick={() => handleRemoveBlock(b.id)}
                      className="text-xs font-medium text-fail hover:underline disabled:opacity-40"
                    >
                      Unblock
                    </button>
                  </td>
                </tr>
              ))}
              {blocklist && blocklist.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-ink-soft">
                    Nothing blocked yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <CandidateSection
        title="Taxonomy candidates"
        description={`Skill and job-title terms Hermes doesn't recognize yet, seen in real postings (${taxonomyCandidates.filter((c) => c.signal_type === 'skill').length} skill, ${taxonomyCandidates.filter((c) => c.signal_type === 'job_title').length} job title). Approving adds it to the matching taxonomy immediately — skills and job titles are always kept in separate files, never mixed.`}
        emptyMessage="No new terms waiting for review."
        termLabel="Term"
        showTypeColumn
        candidates={taxonomyCandidates}
        {...sharedSectionProps}
      />

      <CandidateSection
        title="Boilerplate patterns"
        description="Recurring footer/signature lines seen across 3+ different senders that the automatic cleaner doesn't already strip out of job descriptions. Approving removes this exact line from every future posting immediately."
        emptyMessage="No recurring boilerplate lines waiting for review yet."
        termLabel="Line"
        candidates={boilerplateCandidates}
        {...sharedSectionProps}
      />
    </div>
  )
}
