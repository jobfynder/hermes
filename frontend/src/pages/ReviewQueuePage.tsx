import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { PaginationControls, usePagination } from '../components/Pagination'
import type { BlocklistEntry, TaxonomyCandidateEntry } from '../types'

type Tab = 'skill' | 'job_title' | 'boilerplate_line'
type Lens = 'decide' | 'approve' | 'reject' | 'all'
type SortKey = 'occurrence_count' | 'distinct_senders' | 'last_seen_at' | 'term'

const TABS: { id: Tab; label: string; help: string }[] = [
  {
    id: 'skill',
    label: 'Skills',
    help: 'Terms found in job emails that Hermes does not recognise yet. Add the real tools and technologies; reject phrases, headings and names.',
  },
  {
    id: 'job_title',
    label: 'Job titles',
    help: 'Job titles seen across several senders. Add proper role titles; reject fragments.',
  },
  {
    id: 'boilerplate_line',
    label: 'Repeated lines',
    help: 'Lines repeated across many senders. Approve only true footers or legal text (it is then removed from every job description). Reject anything that is real job content.',
  },
]

const WORDS: Record<Tab, { yes: string; no: string; noun: string; col: string }> = {
  skill: { yes: 'Add skill', no: 'Not a skill', noun: 'skills', col: 'Skill' },
  job_title: { yes: 'Add title', no: 'Not a title', noun: 'job titles', col: 'Job title' },
  boilerplate_line: { yes: 'Remove it', no: 'Keep it', noun: 'lines', col: 'Line' },
}

const LENSES: { id: Lens; label: string }[] = [
  { id: 'decide', label: 'Needs your decision' },
  { id: 'approve', label: 'Hermes suggests: yes' },
  { id: 'reject', label: 'Hermes suggests: no' },
  { id: 'all', label: 'Everything' },
]

function suggestionOf(c: TaxonomyCandidateEntry): 'approve' | 'reject' | 'review' {
  return c.suggestion === 'approve' || c.suggestion === 'reject' ? c.suggestion : 'review'
}

function inLens(c: TaxonomyCandidateEntry, lens: Lens): boolean {
  if (lens === 'all') return true
  const s = suggestionOf(c)
  return lens === 'decide' ? s === 'review' : s === lens
}

function Chip({ s }: { s: 'approve' | 'reject' | 'review' }) {
  const map = {
    approve: ['bg-pass-soft text-pass', 'Suggested: yes'],
    reject: ['bg-fail-soft text-fail', 'Suggested: no'],
    review: ['bg-warn-soft text-warn', 'Your call'],
  } as const
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${map[s][0]}`}>{map[s][1]}</span>
}

function chunks<T>(items: T[], size: number): T[][] {
  const out: T[][] = []
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size))
  return out
}

export function ReviewQueuePage() {
  const [candidates, setCandidates] = useState<TaxonomyCandidateEntry[] | null>(null)
  const [blocklist, setBlocklist] = useState<BlocklistEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState<Tab>('skill')
  const [lens, setLens] = useState<Lens>('decide')
  const [search, setSearch] = useState('')
  const [minSeen, setMinSeen] = useState(1)
  const [sortKey, setSortKey] = useState<SortKey>('occurrence_count')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')

  const [newType, setNewType] = useState<'domain' | 'email'>('domain')
  const [newValue, setNewValue] = useState('')
  const [newReason, setNewReason] = useState('')
  const [blockSearch, setBlockSearch] = useState('')
  const [blockFilter, setBlockFilter] = useState<'all' | 'auto' | 'manual'>('all')

  function load() {
    setError(null)
    api.listBlocklist().then(setBlocklist).catch((e) => setError(e.message))
    api
      .listTaxonomyCandidates('pending')
      .then((list) => {
        setCandidates(list)
        setSelected((prev) => {
          const live = new Set(list.map((c) => c.id))
          return new Set([...prev].filter((id) => live.has(id)))
        })
      })
      .catch((e) => setError(e.message))
  }
  useEffect(load, [])

  const byTab = useMemo(() => {
    const out: Record<Tab, TaxonomyCandidateEntry[]> = { skill: [], job_title: [], boilerplate_line: [] }
    for (const c of candidates ?? []) out[c.signal_type]?.push(c)
    return out
  }, [candidates])

  const needDecision = (t: Tab) => byTab[t].filter((c) => inLens(c, 'decide')).length
  const tabRows = byTab[tab]
  const lensCount = (l: Lens) => tabRows.filter((c) => inLens(c, l)).length

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const rows = tabRows.filter((c) => {
      if (!inLens(c, lens) || c.occurrence_count < minSeen) return false
      return !q || `${c.term} ${c.distinct_senders.join(' ')}`.toLowerCase().includes(q)
    })
    return rows.sort((a, b) => {
      if (sortKey === 'term') return a.term.localeCompare(b.term)
      if (sortKey === 'distinct_senders') return b.distinct_senders.length - a.distinct_senders.length
      if (sortKey === 'last_seen_at') return new Date(b.last_seen_at).getTime() - new Date(a.last_seen_at).getTime()
      return b.occurrence_count - a.occurrence_count
    })
  }, [tabRows, lens, search, minSeen, sortKey])

  const { pageItems, page, pageCount, pageSize, setPage, setPageSize } = usePagination(
    visible,
    `${tab}|${lens}|${search}|${minSeen}|${sortKey}`,
    25,
  )
  const pageIds = pageItems.map((c) => c.id)
  const selectedVisible = visible.filter((c) => selected.has(c.id)).map((c) => c.id)
  const words = WORDS[tab]

  async function run(label: (ok: number) => string, work: () => Promise<number>) {
    setBusy(true)
    setError(null)
    try {
      const ok = await work()
      setMessage(label(ok))
      setSelected(new Set())
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const approveIds = (ids: number[]) =>
    run(
      (n) => `Added ${n} ${words.noun}.`,
      async () => {
        let ok = 0
        for (const part of chunks(ids, 200)) ok += (await api.bulkApproveTaxonomyCandidates(part)).ok_count
        return ok
      },
    )
  const rejectIds = (ids: number[]) =>
    run(
      (n) => `Rejected ${n} ${words.noun}.`,
      async () => {
        let ok = 0
        for (const part of chunks(ids, 500)) ok += (await api.bulkRejectTaxonomyCandidates(part)).ok_count
        return ok
      },
    )

  async function applySuggestions() {
    const yes = tabRows.filter((c) => suggestionOf(c) === 'approve').map((c) => c.id)
    const no = tabRows.filter((c) => suggestionOf(c) === 'reject').map((c) => c.id)
    if (!yes.length && !no.length) return
    const ok = window.confirm(
      `Apply Hermes's suggestions to ${words.noun}?\n\n• Add ${yes.length}\n• Reject ${no.length}\n\nItems marked "Your call" are left alone. Hermes also does this by itself every 15 minutes.`,
    )
    if (!ok) return
    await run(
      (n) => `Applied suggestions to ${n} ${words.noun}.`,
      async () => {
        let done = 0
        for (const part of chunks(yes, 100)) done += (await api.bulkApproveTaxonomyCandidates(part)).ok_count
        for (const part of chunks(no, 500)) done += (await api.bulkRejectTaxonomyCandidates(part)).ok_count
        return done
      },
    )
  }

  async function saveEdit(id: number) {
    if (!editValue.trim()) return
    setBusy(true)
    try {
      await api.editTaxonomyCandidate(id, editValue.trim())
      setEditingId(null)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the change.')
    } finally {
      setBusy(false)
    }
  }

  async function addBlock() {
    if (!newValue.trim()) return
    setBusy(true)
    try {
      await api.addBlock(newType, newValue.trim(), newReason.trim() || undefined)
      setNewValue('')
      setNewReason('')
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not add the block.')
    } finally {
      setBusy(false)
    }
  }

  async function unblock(id: number) {
    setBusy(true)
    try {
      await api.removeBlock(id)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not unblock.')
    } finally {
      setBusy(false)
    }
  }

  const blocks = useMemo(() => {
    const q = blockSearch.trim().toLowerCase()
    return (blocklist ?? []).filter((b) => {
      const auto = (b.reason ?? '').startsWith('auto:')
      if (blockFilter === 'auto' && !auto) return false
      if (blockFilter === 'manual' && auto) return false
      return !q || `${b.value} ${b.reason ?? ''}`.toLowerCase().includes(q)
    })
  }, [blocklist, blockSearch, blockFilter])
  const blockPager = usePagination(blocks, `${blockSearch}|${blockFilter}`, 10)

  const suggestCount = lensCount('approve') + lensCount('reject')
  const selectCls = 'rounded-lg border border-line bg-paper px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent'

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-ink">Review queue</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Hermes decides the clear cases by itself every 15 minutes. What is left here is what it could not decide.
        </p>
      </header>

      {error && <div className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}
      {message && (
        <div className="mb-4 flex items-center justify-between rounded-lg bg-pass-soft px-4 py-3 text-sm text-pass">
          {message}
          <button onClick={() => setMessage(null)} className="text-xs underline">Dismiss</button>
        </div>
      )}

      {/* Tabs */}
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        {TABS.map((t) => {
          const open = needDecision(t.id)
          const on = tab === t.id
          return (
            <button
              key={t.id}
              onClick={() => {
                setTab(t.id)
                setLens('decide')
                setSelected(new Set())
              }}
              className={`rounded-2xl border px-4 py-3 text-left transition ${
                on ? 'border-accent bg-accent-soft' : 'border-line bg-surface hover:border-ink-soft'
              }`}
            >
              <div className="text-xs font-medium uppercase tracking-wide text-ink-soft">{t.label}</div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className={`text-2xl font-semibold ${open === 0 ? 'text-pass' : 'text-ink'}`}>{candidates ? (open === 0 ? '✓' : open.toLocaleString()) : '…'}</span>
                <span className="text-xs text-ink-soft">{open === 0 ? 'all clear' : 'need your decision'}</span>
              </div>
            </button>
          )
        })}
      </div>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <p className="mb-4 text-sm text-ink-soft">{TABS.find((t) => t.id === tab)?.help}</p>

        <div className="mb-3 flex flex-wrap gap-2">
          {LENSES.map((l) => (
            <button
              key={l.id}
              onClick={() => setLens(l.id)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                lens === l.id ? 'bg-accent text-white' : 'border border-line bg-paper text-ink-soft hover:text-ink'
              }`}
            >
              {l.label} ({lensCount(l.id).toLocaleString()})
            </button>
          ))}
        </div>

        {suggestCount > 0 && (
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-accent-soft px-4 py-3">
            <span className="text-sm text-ink">
              Hermes is confident about <b>{suggestCount.toLocaleString()}</b> of these and will apply them on its next run.
            </span>
            <button
              disabled={busy}
              onClick={applySuggestions}
              className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
            >
              Apply them now
            </button>
          </div>
        )}

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…"
            className="min-w-48 flex-1 rounded-lg border border-line bg-paper px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
          />
          <select value={minSeen} onChange={(e) => setMinSeen(Number(e.target.value))} className={selectCls}>
            {[1, 2, 5, 10, 25].map((v) => (
              <option key={v} value={v}>{v === 1 ? 'Any frequency' : `Seen ${v}+ times`}</option>
            ))}
          </select>
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)} className={selectCls}>
            <option value="occurrence_count">Most seen first</option>
            <option value="distinct_senders">Most senders first</option>
            <option value="last_seen_at">Most recent first</option>
            <option value="term">A to Z</option>
          </select>
        </div>

        <div className="mb-3 flex items-center justify-between rounded-lg border border-line bg-paper px-3 py-2">
          <span className="text-xs text-ink-soft">
            {selectedVisible.length ? `${selectedVisible.length} selected` : `${visible.length.toLocaleString()} shown. Tick rows to act on several at once.`}
          </span>
          <div className="flex gap-4">
            <button
              disabled={busy || !selectedVisible.length}
              onClick={() => approveIds(selectedVisible)}
              className="text-xs font-semibold text-accent hover:underline disabled:opacity-40"
            >
              {words.yes} (selected)
            </button>
            <button
              disabled={busy || !selectedVisible.length}
              onClick={() => rejectIds(selectedVisible)}
              className="text-xs font-semibold text-fail hover:underline disabled:opacity-40"
            >
              {words.no} (selected)
            </button>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-line">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line bg-paper text-xs uppercase tracking-wide text-ink-soft">
                <th className="w-8 px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select this page"
                    className="accent-accent"
                    checked={pageIds.length > 0 && pageIds.every((id) => selected.has(id))}
                    onChange={() =>
                      setSelected((prev) => {
                        const all = pageIds.every((id) => prev.has(id))
                        const next = new Set(prev)
                        pageIds.forEach((id) => (all ? next.delete(id) : next.add(id)))
                        return next
                      })
                    }
                  />
                </th>
                <th className="px-3 py-2 font-medium">{words.col}</th>
                <th className="px-3 py-2 font-medium">Seen</th>
                <th className="px-3 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((c) => (
                <tr key={c.id} className="border-b border-line align-top last:border-0">
                  <td className="px-3 py-3">
                    <input
                      type="checkbox"
                      className="accent-accent"
                      aria-label={`Select ${c.term}`}
                      checked={selected.has(c.id)}
                      onChange={() =>
                        setSelected((prev) => {
                          const next = new Set(prev)
                          if (next.has(c.id)) next.delete(c.id)
                          else next.add(c.id)
                          return next
                        })
                      }
                    />
                  </td>
                  <td className="max-w-xl px-3 py-3">
                    {editingId === c.id ? (
                      <input
                        autoFocus
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') saveEdit(c.id)
                          if (e.key === 'Escape') setEditingId(null)
                        }}
                        className="w-full rounded border border-accent bg-paper px-2 py-1 text-sm text-ink outline-none"
                      />
                    ) : (
                      <div className="group">
                        <span className="break-words font-medium text-ink">{c.term}</span>
                        {tab !== 'boilerplate_line' && (
                          <button
                            onClick={() => {
                              setEditingId(c.id)
                              setEditValue(c.term)
                            }}
                            className="ml-2 text-xs text-ink-soft opacity-0 hover:text-accent group-hover:opacity-100"
                          >
                            Edit
                          </button>
                        )}
                      </div>
                    )}
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <Chip s={suggestionOf(c)} />
                      {c.suggestion_reason && <span className="text-xs text-ink-soft">{c.suggestion_reason}</span>}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-xs text-ink-soft">
                    <div className="font-medium text-ink">{c.occurrence_count}×</div>
                    <div title={c.distinct_senders.join(', ')}>{c.distinct_senders.length} senders</div>
                    <div>{new Date(c.last_seen_at).toLocaleDateString()}</div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right">
                    {editingId === c.id ? (
                      <div className="flex justify-end gap-3">
                        <button disabled={busy || !editValue.trim()} onClick={() => saveEdit(c.id)} className="text-xs font-semibold text-accent hover:underline disabled:opacity-40">Save</button>
                        <button disabled={busy} onClick={() => setEditingId(null)} className="text-xs text-ink-soft hover:underline">Cancel</button>
                      </div>
                    ) : (
                      <div className="flex justify-end gap-2">
                        <button disabled={busy} onClick={() => approveIds([c.id])} className="rounded-lg border border-accent px-2.5 py-1 text-xs font-semibold text-accent transition hover:bg-accent-soft disabled:opacity-40">{words.yes}</button>
                        <button disabled={busy} onClick={() => rejectIds([c.id])} className="rounded-lg border border-line px-2.5 py-1 text-xs font-semibold text-ink-soft transition hover:border-fail hover:text-fail disabled:opacity-40">{words.no}</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {candidates && visible.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-10 text-center text-sm text-ink-soft">
                    {lens === 'decide' ? 'Nothing needs your decision here. 🎉' : 'Nothing matches this view.'}
                  </td>
                </tr>
              )}
              {!candidates && (
                <tr>
                  <td colSpan={4} className="px-3 py-10 text-center text-sm text-ink-soft">Loading…</td>
                </tr>
              )}
            </tbody>
          </table>
          <PaginationControls
            page={page}
            pageCount={pageCount}
            pageSize={pageSize}
            totalCount={visible.length}
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
          />
        </div>
      </section>

      {/* Sender blocklist lives at the bottom: it is a set-and-forget control, not daily work. */}
      <section className="mt-10 rounded-2xl border border-line bg-surface p-5">
        <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-ink">Blocked senders</h2>
          <span className="text-xs text-ink-soft">
            {blocklist ? `${blocklist.length.toLocaleString()} blocked` : ''}
            {blocklist ? ` · ${blocklist.filter((b) => (b.reason ?? '').startsWith('auto:')).length} added automatically` : ''}
          </span>
        </div>
        <p className="mb-4 text-xs text-ink-soft">
          Mail from a blocked domain or address is discarded before it becomes a draft. Hermes adds obvious spam senders by itself; you can undo any of them here.
        </p>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <select value={newType} onChange={(e) => setNewType(e.target.value as 'domain' | 'email')} className={selectCls}>
            <option value="domain">Whole domain</option>
            <option value="email">One email address</option>
          </select>
          <input
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            placeholder={newType === 'domain' ? 'spamvendor.com' : 'someone@spamvendor.com'}
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
            onClick={addBlock}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
          >
            Block
          </button>
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            value={blockSearch}
            onChange={(e) => setBlockSearch(e.target.value)}
            placeholder="Search blocked senders…"
            className="min-w-48 flex-1 rounded-lg border border-line bg-paper px-3 py-1.5 text-sm text-ink outline-none focus:border-accent"
          />
          <select value={blockFilter} onChange={(e) => setBlockFilter(e.target.value as 'all' | 'auto' | 'manual')} className={selectCls}>
            <option value="all">All</option>
            <option value="auto">Added by Hermes</option>
            <option value="manual">Added by people</option>
          </select>
        </div>

        <div className="overflow-hidden rounded-xl border border-line">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line bg-paper text-xs uppercase tracking-wide text-ink-soft">
                <th className="px-3 py-2 font-medium">Sender</th>
                <th className="px-3 py-2 font-medium">Why</th>
                <th className="px-3 py-2 font-medium">Blocked</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {blockPager.pageItems.map((b) => {
                const auto = (b.reason ?? '').startsWith('auto:')
                return (
                  <tr key={b.id} className="border-b border-line last:border-0">
                    <td className="px-3 py-2.5">
                      <div className="font-medium text-ink">{b.value}</div>
                      <div className="text-[11px] text-ink-soft">{b.match_type === 'domain' ? 'Whole domain' : 'One address'}</div>
                    </td>
                    <td className="px-3 py-2.5 text-xs text-ink-soft">
                      {auto && <span className="mr-1.5 rounded-full bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold text-accent">Hermes</span>}
                      {(b.reason ?? '—').replace(/^auto:\s*/, '')}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs text-ink-soft">{new Date(b.created_at).toLocaleDateString()}</td>
                    <td className="px-3 py-2.5 text-right">
                      <button disabled={busy} onClick={() => unblock(b.id)} className="text-xs font-medium text-fail hover:underline disabled:opacity-40">Unblock</button>
                    </td>
                  </tr>
                )
              })}
              {blocklist && blocks.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-8 text-center text-sm text-ink-soft">No blocked senders match.</td></tr>
              )}
            </tbody>
          </table>
          <PaginationControls
            page={blockPager.page}
            pageCount={blockPager.pageCount}
            pageSize={blockPager.pageSize}
            totalCount={blocks.length}
            onPageChange={blockPager.setPage}
            onPageSizeChange={blockPager.setPageSize}
          />
        </div>
      </section>
    </div>
  )
}
