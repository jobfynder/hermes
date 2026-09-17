import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { CompanyDetail, CompanyPage } from '../companyTypes'

const date = (value: string | null) => value ? new Date(value).toLocaleString() : '—'
const card = 'rounded-xl border border-line bg-surface p-4'

export function CompaniesPage({ onSelectDraft }: { onSelectDraft: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<CompanyPage | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<CompanyDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(null)
    if (selected) {
      setDetail(null)
      api.getCompany(selected, controller.signal).then(setDetail).catch(err => {
        if (!controller.signal.aborted) setError(err.message)
      }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    } else {
      api.listCompanies(search, page, controller.signal).then(setData).catch(err => {
        if (!controller.signal.aborted) setError(err.message)
      }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }
    return () => controller.abort()
  }, [selected, search, page, revision])

  return <main className="mx-auto max-w-6xl px-6 py-8">
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        {selected && <button className="mb-3 text-sm text-accent" onClick={() => setSelected(null)}>← All companies</button>}
        <h1 className="text-2xl font-semibold text-ink">{selected && detail ? detail.canonical_name : 'Companies'}</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-soft">Company discovery from Hermes email evidence. Observed relationships are unverified until reviewed.</p>
      </div>
      <button disabled={loading} onClick={() => setRevision(value => value + 1)} className="rounded-lg border border-line bg-surface px-4 py-2 text-sm disabled:opacity-40">{loading ? 'Loading…' : 'Refresh'}</button>
    </header>
    {error && <div role="alert" className="mb-4 rounded-lg bg-fail-soft p-4 text-fail">{error}</div>}
    {!selected && <>
      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <div className={card}><p className="text-xs uppercase text-ink-soft">Discovered companies</p><p className="mt-1 text-2xl font-semibold">{data?.total_count.toLocaleString() ?? '—'}</p><p className="text-xs text-ink-soft">{search ? 'Matching your search' : 'Grouped by observed corporate domain'}</p></div>
        <div className={card}><p className="text-xs uppercase text-ink-soft">Sources linked</p><p className="mt-1 text-2xl font-semibold">{data?.sync.linked.toLocaleString() ?? '—'}</p><p className="text-xs text-ink-soft">Duplicate and ambiguous sources excluded</p></div>
        <div className={card}><p className="text-xs uppercase text-ink-soft">Automatic discovery</p><p className="mt-1 text-lg font-semibold">{data ? `${data.sync.processed.toLocaleString()} / ${data.sync.total.toLocaleString()} checked` : 'Checking…'}</p><p className="text-xs text-ink-soft">Deterministic · updated {date(data?.sync.last_synced ?? null)}</p></div>
      </div>
      <form className="mb-4 flex gap-2" onSubmit={event => { event.preventDefault(); setSearch(query.trim()); setPage(1) }}>
        <input aria-label="Search companies" placeholder="Search company name or domain" value={query} onChange={event => setQuery(event.target.value)} maxLength={120} className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm" />
        <button className="rounded-lg bg-accent px-4 py-2 text-sm text-white">Search</button>
      </form>
      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full text-left text-sm"><thead className="border-b border-line text-xs uppercase text-ink-soft"><tr>{['Company', 'Domain', 'Contacts observed', 'Source emails', 'Last seen', 'Verification'].map(label => <th key={label} className="p-3">{label}</th>)}</tr></thead>
          <tbody>{data?.items.map(company => <tr key={company.company_id} className="border-b border-line last:border-0">
            <td className="p-3"><button onClick={() => setSelected(company.company_id)} className="text-left font-medium text-accent hover:underline">{company.canonical_name}</button></td>
            <td className="p-3 text-ink-soft">{company.identity_domain}</td><td className="p-3">{company.contact_count}</td><td className="p-3">{company.source_count}</td><td className="p-3 text-ink-soft">{date(company.last_seen)}</td><td className="p-3"><span className="rounded-full bg-paper px-2 py-1 text-xs">{company.verification_status}</span></td>
          </tr>)}</tbody>
        </table>
        {!loading && !data?.items.length && <p className="p-8 text-center text-sm text-ink-soft">{search ? 'No companies match this search.' : 'Company discovery is running. Records with a company name and corporate signature email will appear here.'}</p>}
      </div>
      <div className="mt-4 flex items-center justify-between text-sm text-ink-soft"><span>Page {page} of {Math.max(1, Math.ceil((data?.total_count ?? 0) / 25))}</span><div className="flex gap-3"><button disabled={page <= 1 || loading} onClick={() => setPage(value => value - 1)} className="disabled:opacity-40">Previous</button><button disabled={loading || page * 25 >= (data?.total_count ?? 0)} onClick={() => setPage(value => value + 1)} className="disabled:opacity-40">Next</button></div></div>
      <p className="mt-5 text-xs text-ink-soft">Name-only mentions, shared email providers, and relay senders remain in the source review workflow. Discovery does not publish companies or jobs to CORE.</p>
    </>}
    {selected && detail && <>
      <div className="mb-5 flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-surface px-3 py-1">{detail.identity_domain}</span><span className="rounded-full bg-surface px-3 py-1">{detail.verification_status}</span><span className="rounded-full bg-surface px-3 py-1">{detail.claim_status}</span></div>
      <div className="mb-5 grid gap-3 sm:grid-cols-3"><div className={card}><p className="text-sm text-ink-soft">Unique observed requirements</p><p className="text-2xl font-semibold">{detail.job_requirements}</p><p className="text-xs text-ink-soft">Not confirmed open jobs</p></div><div className={card}><p className="text-sm text-ink-soft">Contacts observed</p><p className="text-2xl font-semibold">{detail.contact_count}</p><p className="text-xs text-ink-soft">Company affiliation not yet verified</p></div><div className={card}><p className="text-sm text-ink-soft">Activity score · last 30 days</p><p className="text-2xl font-semibold">{detail.activity.score} / 100</p><p className="text-xs text-ink-soft">Activity is not a trust or verification score</p></div></div>
      <details className={`${card} mb-5`}><summary className="cursor-pointer text-sm font-medium">How activity is calculated</summary><p className="mt-2 text-sm text-ink-soft">3 points per unique requirement (up to 60), 5 per observed contact (up to 25), and 15 for recent source activity. Current evidence: {detail.activity.recent_unique_requirements} requirements, {detail.activity.recent_contacts} contacts, {detail.activity.recent_sources} source emails.</p></details>
      <section className={`${card} mb-5`}><h2 className="mb-2 font-semibold">Names observed in signatures</h2><p className="text-sm text-ink-soft">{detail.observed_names.map(item => `${item.company_label} (${item.sources})`).join(' · ')}</p><p className="mt-2 text-xs text-ink-soft">Shared domain evidence groups these observations; the legal company identity still requires verification.</p></section>
      <section className={`${card} mb-5`}><h2 className="mb-3 font-semibold">Observed contacts</h2><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="text-ink-soft"><th className="py-2">Name</th><th>Email</th><th>Sources</th><th>Last seen</th></tr></thead><tbody>{detail.contacts.map(contact => <tr key={contact.email} className="border-t border-line"><td className="py-2">{contact.name || '—'}</td><td>{contact.email}</td><td>{contact.source_count}</td><td>{date(contact.last_seen)}</td></tr>)}</tbody></table></div><p className="mt-2 text-xs text-ink-soft">Showing up to 100 recently observed contacts.</p></section>
      <section><h2 className="mb-3 font-semibold">Source evidence and requirements</h2><p className="mb-3 text-xs text-ink-soft">Latest 50 of {detail.source_count} source emails. Open the original draft to review or correct an extraction.</p><div className="space-y-3">{detail.sources.map(source => <article key={source.draft_id} className={card}><div className="flex flex-wrap justify-between gap-2"><p className="text-sm font-medium">{source.company_label} · {source.contact_email}</p><button className="text-sm text-accent hover:underline" onClick={() => onSelectDraft(source.draft_id)}>Open source draft</button></div><p className="mt-1 text-xs text-ink-soft">{source.channel} · {date(source.observed_at)} · company-name extraction confidence {Math.round(source.confidence * 100)}%</p><p className="mt-1 text-xs text-ink-soft">{[source.website, source.phone, source.location].filter(Boolean).join(' · ')}</p>{source.jobs.length > 0 && <ul className="mt-3 space-y-1 text-sm">{source.jobs.map((job, index) => <li key={`${job.key}-${index}`}>{job.title}{job.location ? ` · ${job.location}` : ''}{job.requires_review ? ' · Needs review' : ''}</li>)}</ul>}</article>)}</div></section>
    </>}
  </main>
}
