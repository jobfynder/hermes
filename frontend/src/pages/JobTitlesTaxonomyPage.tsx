import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { PaginationControls, usePagination } from '../components/Pagination'
import type { JobTitleEntry } from '../types'

type SortKey = 'title' | 'family' | 'seniority'

const SENIORITY_OPTIONS = ['unspecified', 'junior', 'mid', 'senior', 'lead', 'principal', 'director']

function EditRow({
  entry,
  families,
  onSave,
  onCancel,
}: {
  entry: JobTitleEntry
  families: string[]
  onSave: (changes: { newTitle?: string; family?: string; seniority?: string }) => Promise<void>
  onCancel: () => void
}) {
  const [title, setTitle] = useState(entry.title)
  const [family, setFamily] = useState(entry.family || 'Unclassified')
  const [seniority, setSeniority] = useState(entry.seniority || 'unspecified')
  const [saving, setSaving] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // The full family list always includes whatever this row already has,
  // so "keep the current value" is never a missing <option> even if it's
  // a one-off family no other title uses.
  const familyOptions = Array.from(new Set([...families, family, 'Unclassified'])).sort()

  async function handleSuggest() {
    setSuggesting(true)
    setSaveError(null)
    try {
      const result = await api.suggestJobTitleFamily(title)
      setFamily(result.family)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Could not get a suggestion')
    } finally {
      setSuggesting(false)
    }
  }

  async function handleSave() {
    if (!title.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      await onSave({
        newTitle: title.trim() !== entry.title ? title.trim() : undefined,
        family: family !== (entry.family || 'Unclassified') ? family : undefined,
        seniority: seniority !== (entry.seniority || 'unspecified') ? seniority : undefined,
      })
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <tr className="border-b border-line bg-paper last:border-0 align-top">
      <td className="max-w-xs px-4 py-2.5">
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full rounded border border-accent bg-surface px-2 py-1 text-sm text-ink outline-none"
        />
        {saveError && <div className="mt-1 text-xs text-fail">{saveError}</div>}
      </td>
      <td className="px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <select
            value={family}
            onChange={(e) => setFamily(e.target.value)}
            className="w-full rounded border border-line bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-accent"
          >
            {familyOptions.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <button
            disabled={suggesting}
            onClick={handleSuggest}
            title="Suggest a family based on the title"
            className="shrink-0 text-xs font-medium text-accent hover:underline disabled:opacity-40"
          >
            {suggesting ? '…' : 'Suggest'}
          </button>
        </div>
      </td>
      <td className="px-4 py-2.5">
        <select
          value={seniority}
          onChange={(e) => setSeniority(e.target.value)}
          className="rounded border border-line bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-accent"
        >
          {SENIORITY_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </td>
      <td className="px-4 py-2.5 text-ink-soft">
        {entry.related_titles.length ? entry.related_titles.join(', ') : '—'}
      </td>
      <td className="px-4 py-2.5 text-right">
        <div className="flex justify-end gap-3">
          <button
            disabled={saving || !title.trim()}
            onClick={handleSave}
            className="text-xs font-medium text-accent hover:underline disabled:opacity-40"
          >
            Save
          </button>
          <button
            disabled={saving}
            onClick={onCancel}
            className="text-xs font-medium text-ink-soft hover:underline disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
      </td>
    </tr>
  )
}

export function JobTitlesTaxonomyPage({ onBack }: { onBack: () => void }) {
  const [titles, setTitles] = useState<JobTitleEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [family, setFamily] = useState('all')
  const [sortKey, setSortKey] = useState<SortKey>('title')
  const [editingTitle, setEditingTitle] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkFamily, setBulkFamily] = useState('')
  const [busy, setBusy] = useState(false)

  function load() {
    api
      .browseJobTitlesTaxonomy()
      .then((list) => {
        setTitles(list)
        setSelected((prev) => {
          const stillPresent = new Set(list.map((t) => t.title))
          return new Set([...prev].filter((t) => stillPresent.has(t)))
        })
      })
      .catch((err) => setError(err.message))
  }

  useEffect(load, [])

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

  const { pageItems, page, pageCount, pageSize, setPage, setPageSize } = usePagination(
    filtered,
    `${search}|${family}|${sortKey}`,
  )

  function toggleSelected(title: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(title)) next.delete(title)
      else next.add(title)
      return next
    })
  }

  function toggleSelectAll() {
    const ids = filtered.map((t) => t.title)
    setSelected((prev) => (ids.every((id) => prev.has(id)) ? new Set() : new Set(ids)))
  }

  async function handleEditSave(
    entry: JobTitleEntry,
    changes: { newTitle?: string; family?: string; seniority?: string },
  ) {
    if (!changes.newTitle && !changes.family && !changes.seniority) {
      setEditingTitle(null)
      return
    }
    const result = await api.updateJobTitle(entry.title, changes)
    if (!result.updated) {
      throw new Error(
        result.reason === 'duplicate_title'
          ? 'That title already exists — pick a different name.'
          : result.reason || 'Update failed',
      )
    }
    setEditingTitle(null)
    load()
  }

  async function handleBulkSetFamily() {
    if (selected.size === 0 || !bulkFamily.trim()) return
    setBusy(true)
    try {
      const result = await api.bulkSetJobTitleFamily([...selected], bulkFamily.trim())
      setActionMessage(`Set family to "${bulkFamily.trim()}" for ${result.updated_count} titles.`)
      setSelected(new Set())
      setBulkFamily('')
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk update failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleAutoClassify() {
    setBusy(true)
    try {
      const result = await api.autoClassifyJobTitles()
      setActionMessage(
        `Classified ${result.classified_count} of ${result.checked_count} unclassified titles` +
          (result.still_unclassified_count > 0 ? ` — ${result.still_unclassified_count} still need a human.` : '.'),
      )
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Auto-classify failed')
    } finally {
      setBusy(false)
    }
  }

  const unclassifiedCount = titles?.filter((t) => (t.family || 'Unclassified') === 'Unclassified').length ?? 0

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <datalist id="job-title-families">
        {families.map((f) => (
          <option key={f} value={f} />
        ))}
      </datalist>

      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Job titles taxonomy</h1>
          <p className="mt-1 text-sm text-ink-soft">
            {titles ? `${titles.length} canonical job titles` : 'Loading…'} — kept completely separate from Skills;
            new titles are approved from <span className="font-medium">Blocklist &amp; taxonomy</span>. Renaming
            keeps the old wording as an alias, so postings that still use it are still recognized.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {unclassifiedCount > 0 && (
            <button
              disabled={busy}
              onClick={handleAutoClassify}
              title="Classifies each unclassified title by keyword rules first, LLM only if no rule matches"
              className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
            >
              {busy ? 'Classifying…' : `Auto-classify ${unclassifiedCount} unclassified`}
            </button>
          )}
          <button
            onClick={onBack}
            className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-soft transition hover:text-ink"
          >
            Back to drafts
          </button>
        </div>
      </header>

      {error && <div className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}
      {actionMessage && (
        <div className="mb-4 rounded-lg border border-line bg-paper px-4 py-3 text-sm text-ink-soft">
          {actionMessage}
        </div>
      )}

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

      {titles && titles.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-paper px-3 py-2">
          <span className="text-xs text-ink-soft">
            {selected.size > 0 ? `${selected.size} selected` : `Showing ${filtered.length} of ${titles.length}`}
          </span>
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <input
                list="job-title-families"
                value={bulkFamily}
                onChange={(e) => setBulkFamily(e.target.value)}
                placeholder="Set family to…"
                className="min-w-40 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent"
              />
              <button
                disabled={busy || !bulkFamily.trim()}
                onClick={handleBulkSetFamily}
                className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
              >
                Apply to selected
              </button>
            </div>
          )}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
              <th className="w-8 px-4 py-3">
                {filtered.length > 0 && (
                  <input
                    type="checkbox"
                    checked={filtered.length > 0 && filtered.every((t) => selected.has(t.title))}
                    onChange={toggleSelectAll}
                    className="accent-accent"
                    aria-label="Select all"
                  />
                )}
              </th>
              <th className="px-4 py-3 font-medium">Title</th>
              <th className="px-4 py-3 font-medium">Family</th>
              <th className="px-4 py-3 font-medium">Seniority</th>
              <th className="px-4 py-3 font-medium">Related titles</th>
              <th className="px-4 py-3 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((t) =>
              editingTitle === t.title ? (
                <EditRow
                  key={t.title}
                  entry={t}
                  families={families}
                  onSave={(changes) => handleEditSave(t, changes)}
                  onCancel={() => setEditingTitle(null)}
                />
              ) : (
                <tr key={t.title} className="border-b border-line last:border-0 align-top">
                  <td className="px-4 py-2.5">
                    <input
                      type="checkbox"
                      checked={selected.has(t.title)}
                      onChange={() => toggleSelected(t.title)}
                      className="accent-accent"
                      aria-label={`Select ${t.title}`}
                    />
                  </td>
                  <td className="max-w-xs px-4 py-2.5">
                    <span className="group inline-flex items-center gap-2">
                      <span className="font-medium text-ink" title={t.aliases.length ? `Aliases: ${t.aliases.join(', ')}` : undefined}>
                        {t.title}
                      </span>
                      <button
                        onClick={() => setEditingTitle(t.title)}
                        className="text-xs font-normal text-ink-soft opacity-0 transition group-hover:opacity-100 hover:text-accent hover:underline"
                      >
                        Edit
                      </button>
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-ink-soft">{t.family || '—'}</td>
                  <td className="px-4 py-2.5 text-ink-soft">{t.seniority || '—'}</td>
                  <td className="max-w-xs truncate px-4 py-2.5 text-ink-soft">
                    {t.related_titles.length ? t.related_titles.join(', ') : '—'}
                  </td>
                  <td></td>
                </tr>
              ),
            )}
            {titles && filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-ink-soft">
                  No job titles match these filters.
                </td>
              </tr>
            )}
            {!titles && !error && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-ink-soft">
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
