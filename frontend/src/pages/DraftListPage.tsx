import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { ConfidenceMeter } from '../components/ConfidenceMeter'
import { draftTypeLabel } from '../components/DraftTypeLabel'
import { StatusBadge } from '../components/StatusBadge'
import type { DraftObject, DraftObjectType, DraftStatus } from '../types'

const TYPE_FILTERS: (DraftObjectType | 'all')[] = [
  'all',
  'draft_job_requirement',
  'draft_hotlist',
  'draft_consultant_profile',
  'draft_recruiter_profile',
  'draft_bench_sales_profile',
  'draft_vendor_list',
  'draft_channel_note',
]

const STATUS_FILTERS: (DraftStatus | 'all')[] = ['all', 'needs_review', 'draft', 'published', 'rejected']

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function DraftListPage({ onSelect }: { onSelect: (id: string) => void }) {
  const [drafts, setDrafts] = useState<DraftObject[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState<DraftObjectType | 'all'>('all')
  const [statusFilter, setStatusFilter] = useState<DraftStatus | 'all'>('all')
  const [search, setSearch] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null)

  function load() {
    setError(null)
    api
      .listDrafts()
      .then((d) => {
        setDrafts(d)
        setLastLoadedAt(new Date())
      })
      .catch((err) => setError(err.message ?? 'Failed to load drafts'))
  }

  useEffect(load, [])

  useEffect(() => {
    if (!autoRefresh) return
    const id = window.setInterval(load, 30000)
    return () => window.clearInterval(id)
  }, [autoRefresh])

  const filtered = useMemo(() => {
    if (!drafts) return []
    const q = search.trim().toLowerCase()
    return drafts.filter((d) => {
      if (typeFilter !== 'all' && d.draft_type !== typeFilter) return false
      if (statusFilter !== 'all' && d.status !== statusFilter) return false
      if (q) {
        const haystack = `${d.title ?? ''} ${d.metadata.sender?.email ?? ''} ${d.source_message_id ?? ''}`.toLowerCase()
        if (!haystack.includes(q)) return false
      }
      return true
    })
  }, [drafts, typeFilter, statusFilter, search])

  const counts = useMemo(() => {
    if (!drafts) return { total: 0, needsReview: 0 }
    return {
      total: drafts.length,
      needsReview: drafts.filter((d) => d.status === 'needs_review').length,
    }
  }, [drafts])

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Parsed emails</h1>
          <p className="mt-1 text-sm text-ink-soft">
            {counts.total} total &middot; {counts.needsReview} awaiting review
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastLoadedAt && (
            <span className="text-xs text-ink-soft">
              Updated {lastLoadedAt.toLocaleTimeString()}
            </span>
          )}
          <label className="flex items-center gap-1.5 text-xs text-ink-soft">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="accent-accent"
            />
            Auto-refresh
          </label>
          <button
            onClick={load}
            className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-soft transition hover:text-ink"
          >
            Refresh
          </button>
        </div>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search title, sender, message id…"
          className="min-w-56 flex-1 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as DraftObjectType | 'all')}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
        >
          {TYPE_FILTERS.map((t) => (
            <option key={t} value={t}>
              {t === 'all' ? 'All types' : draftTypeLabel(t)}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as DraftStatus | 'all')}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s === 'all' ? 'All statuses' : s.replace('_', ' ')}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>
      )}

      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
              <th className="px-4 py-3 font-medium">Title</th>
              <th className="px-4 py-3 font-medium">Type</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Confidence</th>
              <th className="px-4 py-3 font-medium">Sender</th>
              <th className="px-4 py-3 font-medium">Received</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((d) => (
              <tr
                key={d.draft_id}
                onClick={() => onSelect(d.draft_id)}
                className="cursor-pointer border-b border-line last:border-0 hover:bg-paper"
              >
                <td className="max-w-72 truncate px-4 py-3 font-medium text-ink">{d.title || '(untitled)'}</td>
                <td className="px-4 py-3">{draftTypeLabel(d.draft_type)}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={d.status} />
                </td>
                <td className="px-4 py-3">
                  <ConfidenceMeter value={d.confidence} />
                </td>
                <td className="max-w-48 truncate px-4 py-3 text-ink-soft">
                  {d.metadata.sender?.email ?? d.metadata.original_sender_candidate?.email ?? '—'}
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-ink-soft">{timeAgo(d.created_at ?? null)}</td>
              </tr>
            ))}
            {drafts && filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-ink-soft">
                  No drafts match these filters.
                </td>
              </tr>
            )}
            {!drafts && !error && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-ink-soft">
                  Loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
