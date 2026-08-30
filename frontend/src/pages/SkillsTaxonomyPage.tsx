import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { CanonicalSkillEntry } from '../types'

type SortKey = 'name' | 'times_seen' | 'last_seen_at'

function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const diffMs = Date.now() - new Date(iso).getTime()
  const days = Math.floor(diffMs / 86400000)
  if (days < 1) return 'today'
  if (days === 1) return '1 day ago'
  return `${days} days ago`
}

export function SkillsTaxonomyPage({ onBack }: { onBack: () => void }) {
  const [skills, setSkills] = useState<CanonicalSkillEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [sortKey, setSortKey] = useState<SortKey>('times_seen')

  useEffect(() => {
    api.browseSkillsTaxonomy().then(setSkills).catch((err) => setError(err.message))
  }, [])

  const categories = useMemo(() => {
    if (!skills) return []
    return Array.from(new Set(skills.map((s) => s.category || 'Uncategorized'))).sort()
  }, [skills])

  const filtered = useMemo(() => {
    if (!skills) return []
    const q = search.trim().toLowerCase()

    let rows = skills.filter((s) => {
      if (category !== 'all' && (s.category || 'Uncategorized') !== category) return false
      if (q) {
        const haystack = `${s.name} ${s.aliases.join(' ')}`.toLowerCase()
        if (!haystack.includes(q)) return false
      }
      return true
    })

    rows = [...rows].sort((a, b) => {
      if (sortKey === 'name') return a.name.localeCompare(b.name)
      if (sortKey === 'times_seen') return b.times_seen - a.times_seen
      // last_seen_at, most recent first, nulls last
      if (!a.last_seen_at) return 1
      if (!b.last_seen_at) return -1
      return new Date(b.last_seen_at).getTime() - new Date(a.last_seen_at).getTime()
    })

    return rows
  }, [skills, search, category, sortKey])

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Skills taxonomy</h1>
          <p className="mt-1 text-sm text-ink-soft">
            {skills ? `${skills.length} canonical skills` : 'Loading…'} — new terms are approved from{' '}
            <span className="font-medium">Blocklist &amp; taxonomy</span>, not added here.
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

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search skill or alias…"
          className="min-w-56 flex-1 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
        >
          <option value="all">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
        >
          <option value="times_seen">Sort: most used</option>
          <option value="last_seen_at">Sort: recently seen</option>
          <option value="name">Sort: name</option>
        </select>
      </div>

      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
              <th className="px-4 py-3 font-medium">Skill</th>
              <th className="px-4 py-3 font-medium">Category</th>
              <th className="px-4 py-3 font-medium">Aliases</th>
              <th className="px-4 py-3 font-medium">Times seen</th>
              <th className="px-4 py-3 font-medium">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr key={s.name} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 font-medium text-ink">{s.name}</td>
                <td className="px-4 py-2.5 text-ink-soft">{s.category || '—'}</td>
                <td className="max-w-64 truncate px-4 py-2.5 text-ink-soft">
                  {s.aliases.length ? s.aliases.join(', ') : '—'}
                </td>
                <td className="px-4 py-2.5 text-ink-soft">{s.times_seen}</td>
                <td className="px-4 py-2.5 text-ink-soft">{timeAgo(s.last_seen_at)}</td>
              </tr>
            ))}
            {skills && filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-ink-soft">
                  No skills match these filters.
                </td>
              </tr>
            )}
            {!skills && !error && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-ink-soft">
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
