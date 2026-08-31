import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { JobTitleEntry } from '../types'

type SortKey = 'title' | 'family' | 'seniority'

export function JobTitlesTaxonomyPage({ onBack }: { onBack: () => void }) {
  const [titles, setTitles] = useState<JobTitleEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [family, setFamily] = useState('all')
  const [sortKey, setSortKey] = useState<SortKey>('title')

  useEffect(() => {
    api.browseJobTitlesTaxonomy().then(setTitles).catch((err) => setError(err.message))
  }, [])

  const families = useMemo(() => {
    if (!titles) return []
    return Array.from(new Set(titles.map((t) => t.family || 'Unclassified'))).sort()
  }, [titles])

  const filtered = useMemo(() => {
    if (!titles) return []
    const q = search.trim().toLowerCase()

    let rows = titles.filter((t) => {
      if (family !== 'all' && (t.family || 'Unclassified') !== family) return false
      if (q) {
        const haystack = `${t.title} ${t.aliases.join(' ')} ${t.related_titles.join(' ')}`.toLowerCase()
        if (!haystack.includes(q)) return false
      }
      return true
    })

    rows = [...rows].sort((a, b) => {
      if (sortKey === 'family') return (a.family || '').localeCompare(b.family || '')
      if (sortKey === 'seniority') return (a.seniority || '').localeCompare(b.seniority || '')
      return a.title.localeCompare(b.title)
    })

    return rows
  }, [titles, search, family, sortKey])

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Job titles taxonomy</h1>
          <p className="mt-1 text-sm text-ink-soft">
            {titles ? `${titles.length} canonical job titles` : 'Loading…'} — kept completely separate from Skills;
            new titles are approved from <span className="font-medium">Blocklist &amp; taxonomy</span>, not added
            here.
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
          placeholder="Search title, alias, or related title…"
          className="min-w-56 flex-1 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
        />
        <select
          value={family}
          onChange={(e) => setFamily(e.target.value)}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
        >
          <option value="all">All families</option>
          {families.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
        >
          <option value="title">Sort: title</option>
          <option value="family">Sort: family</option>
          <option value="seniority">Sort: seniority</option>
        </select>
      </div>

      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
              <th className="px-4 py-3 font-medium">Title</th>
              <th className="px-4 py-3 font-medium">Family</th>
              <th className="px-4 py-3 font-medium">Seniority</th>
              <th className="px-4 py-3 font-medium">Related titles</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t) => (
              <tr key={t.title} className="border-b border-line last:border-0 align-top">
                <td className="max-w-xs px-4 py-2.5">
                  <div className="font-medium text-ink" title={t.aliases.length ? `Aliases: ${t.aliases.join(', ')}` : undefined}>
                    {t.title}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-ink-soft">{t.family || '—'}</td>
                <td className="px-4 py-2.5 text-ink-soft">{t.seniority || '—'}</td>
                <td className="max-w-xs truncate px-4 py-2.5 text-ink-soft">
                  {t.related_titles.length ? t.related_titles.join(', ') : '—'}
                </td>
              </tr>
            ))}
            {titles && filtered.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-ink-soft">
                  No job titles match these filters.
                </td>
              </tr>
            )}
            {!titles && !error && (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-ink-soft">
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
