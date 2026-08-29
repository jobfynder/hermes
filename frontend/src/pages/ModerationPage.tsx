import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BlocklistEntry, TaxonomyCandidateEntry } from '../types'

export function ModerationPage({ onBack }: { onBack: () => void }) {
  const [blocklist, setBlocklist] = useState<BlocklistEntry[] | null>(null)
  const [candidates, setCandidates] = useState<TaxonomyCandidateEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [newValue, setNewValue] = useState('')
  const [newMatchType, setNewMatchType] = useState<'domain' | 'email'>('domain')
  const [newReason, setNewReason] = useState('')
  const [busy, setBusy] = useState(false)

  function load() {
    setError(null)
    api.listBlocklist().then(setBlocklist).catch((err) => setError(err.message))
    api.listTaxonomyCandidates('pending').then(setCandidates).catch((err) => setError(err.message))
  }

  useEffect(load, [])

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

      <section className="rounded-xl border border-line bg-surface p-5">
        <h2 className="mb-3 text-sm font-semibold text-ink">Taxonomy candidates</h2>
        <p className="mb-4 text-xs text-ink-soft">
          Skill-shaped terms Hermes doesn't recognize yet, seen in real postings. Approving adds it to the
          taxonomy immediately &mdash; no redeploy needed.
        </p>

        <div className="overflow-hidden rounded-lg border border-line">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
                <th className="px-3 py-2 font-medium">Term</th>
                <th className="px-3 py-2 font-medium">Seen</th>
                <th className="px-3 py-2 font-medium">Distinct senders</th>
                <th className="px-3 py-2 font-medium">Last seen</th>
                <th className="px-3 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {candidates?.map((c) => (
                <tr key={c.id} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 font-medium text-ink">{c.term}</td>
                  <td className="px-3 py-2 text-ink-soft">{c.occurrence_count}×</td>
                  <td className="max-w-56 truncate px-3 py-2 text-ink-soft">
                    {c.distinct_senders.length > 0 ? c.distinct_senders.join(', ') : '—'}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-ink-soft">
                    {new Date(c.last_seen_at).toLocaleDateString()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        disabled={busy}
                        onClick={() => handleApprove(c.id)}
                        className="text-xs font-medium text-accent hover:underline disabled:opacity-40"
                      >
                        Approve
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => handleReject(c.id)}
                        className="text-xs font-medium text-fail hover:underline disabled:opacity-40"
                      >
                        Reject
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {candidates && candidates.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-ink-soft">
                    No new terms waiting for review.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
