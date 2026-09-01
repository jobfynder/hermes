import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { PaginationControls, usePagination } from '../components/Pagination'
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

function DescriptionCell({
  skill,
  onSave,
}: {
  skill: CanonicalSkillEntry
  onSave: (name: string, description: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  function startEdit() {
    setDraft(skill.description || '')
    setSaveError(null)
    setEditing(true)
  }

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    try {
      await onSave(skill.name, draft.trim())
      setEditing(false)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <div className="mt-1">
        <textarea
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setEditing(false)
          }}
          rows={2}
          placeholder="One clear, jargon-free sentence a recruiter would understand instantly."
          className="w-full rounded-lg border border-accent bg-paper px-2.5 py-1.5 text-xs text-ink outline-none"
        />
        {saveError && <div className="mt-1 text-xs text-fail">{saveError}</div>}
        <div className="mt-1.5 flex gap-2">
          <button
            disabled={saving}
            onClick={handleSave}
            className="rounded-md bg-accent px-2 py-0.5 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button
            disabled={saving}
            onClick={() => setEditing(false)}
            className="rounded-md border border-line px-2 py-0.5 text-xs text-ink-soft transition hover:text-ink disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="group mt-0.5 flex items-start gap-2">
      <span className="text-xs text-ink-soft">{skill.description || 'No description yet.'}</span>
      <button
        onClick={startEdit}
        title="Edit description"
        className="shrink-0 rounded-md px-1 text-xs text-ink-soft opacity-0 transition hover:bg-paper hover:text-ink group-hover:opacity-100"
      >
        Edit
      </button>
      {skill.description_source === 'human_edited' ? (
        <span
          className="shrink-0 rounded-full bg-line px-1.5 py-0.5 text-[10px] font-medium text-ink-soft"
          title={
            skill.description_edited_by
              ? `Edited by ${skill.description_edited_by}${skill.description_edited_at ? ` on ${new Date(skill.description_edited_at).toLocaleDateString()}` : ''}`
              : 'Edited by a reviewer'
          }
        >
          edited
        </span>
      ) : skill.description_source === 'ai_generated' ? (
        <span className="shrink-0 rounded-full bg-line px-1.5 py-0.5 text-[10px] font-medium text-ink-soft" title="Generated automatically, not yet reviewed">
          AI
        </span>
      ) : null}
    </div>
  )
}

export function SkillsTaxonomyPage({ onBack }: { onBack: () => void }) {
  const [skills, setSkills] = useState<CanonicalSkillEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [sortKey, setSortKey] = useState<SortKey>('times_seen')

  function load() {
    api.browseSkillsTaxonomy().then(setSkills).catch((err) => setError(err.message))
  }

  useEffect(load, [])

  async function handleSaveDescription(name: string, description: string) {
    const result = await api.updateSkillDescription(name, description)
    if (!result.updated) {
      throw new Error(result.reason || 'Update failed')
    }
    // Update in place rather than a full reload, so the rest of the
    // table (scroll position, other rows) doesn't jump.
    setSkills((prev) =>
      prev
        ? prev.map((s) =>
            s.name === name
              ? { ...s, description, description_source: 'human_edited' }
              : s,
          )
        : prev,
    )
  }

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
        const haystack = `${s.name} ${s.aliases.join(' ')} ${s.description || ''}`.toLowerCase()
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

  const { pageItems, page, pageCount, pageSize, setPage, setPageSize } = usePagination(
    filtered,
    `${search}|${category}|${sortKey}`,
  )

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
              <th className="px-4 py-3 font-medium">Times seen</th>
              <th className="px-4 py-3 font-medium">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((s) => (
              <tr key={s.name} className="border-b border-line last:border-0 align-top">
                <td className="max-w-xl px-4 py-2.5">
                  <div className="font-medium text-ink" title={s.aliases.length ? `Aliases: ${s.aliases.join(', ')}` : undefined}>
                    {s.name}
                  </div>
                  <DescriptionCell skill={s} onSave={handleSaveDescription} />
                </td>
                <td className="px-4 py-2.5 text-ink-soft">{s.category || '—'}</td>
                <td className="px-4 py-2.5 text-ink-soft">{s.times_seen}</td>
                <td className="px-4 py-2.5 text-ink-soft">{timeAgo(s.last_seen_at)}</td>
              </tr>
            ))}
            {skills && filtered.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-ink-soft">
                  No skills match these filters.
                </td>
              </tr>
            )}
            {!skills && !error && (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-ink-soft">
                  Loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <PaginationControls
          page={page}
          pageCount={pageCount}
          pageSize={pageSize}
          totalCount={filtered.length}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </div>
    </div>
  )
}
