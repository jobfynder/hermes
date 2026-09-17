import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { PaginationControls } from '../components/Pagination'
import type { CompanyDetail, CompanyPage } from '../companyTypes'

const date = (value: string | null) => value ? new Date(value).toLocaleString() : '—'
const card = 'rounded-xl border border-line bg-surface p-4'
const select = 'rounded-lg border border-line bg-surface px-3 py-2 text-sm'

export function CompaniesPage({ onSelectDraft }: { onSelectDraft: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [verification, setVerification] = useState('all')
  const [origin, setOrigin] = useState('all')
  const [activity, setActivity] = useState('all')
  const [location, setLocation] = useState('')
  const [source, setSource] = useState('')
  const [sort, setSort] = useState('recent')
  const [data, setData] = useState<CompanyPage | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<CompanyDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const [csvText, setCsvText] = useState('company_name,domain,source,source_url,location,careers_url\n')
  const [importResult, setImportResult] = useState<string | null>(null)
  const pageCount = Math.max(1, Math.ceil((data?.total_count ?? 0) / pageSize))
  const params = useMemo(() => new URLSearchParams({ q: search, page: String(page), page_size: String(pageSize), verification, origin, activity, location, source, sort }), [search,page,pageSize,verification,origin,activity,location,source,sort])

  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null)
    const load = selected ? api.getCompany(selected, controller.signal).then(setDetail) : api.listCompanies(params, controller.signal).then(result => { setData(result); if (result.page !== page) setPage(result.page) })
    load.catch(err => { if (!controller.signal.aborted) setError(err.message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [selected, params, revision])
  const filter = (setter: (value:string)=>void) => (event: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) => { setter(event.target.value); setPage(1) }
  const runImport = async (dryRun:boolean) => {
    setImportResult(null)
    try { const r=await api.importCompanies(csvText,dryRun); setImportResult(`${dryRun?'Preview':'Imported'}: ${r.valid_rows} valid · ${r.new_companies} new · ${r.existing_companies} existing · ${r.errors.length} errors`); if(!dryRun)setRevision(v=>v+1) }
    catch(err){setImportResult(err instanceof Error?err.message:'Import failed')}
  }
  return <main className="mx-auto max-w-6xl px-6 py-8">
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4"><div>
      {selected && <button className="mb-3 text-sm text-accent" onClick={() => {setSelected(null);setDetail(null)}}>← All companies</button>}
      <h1 className="text-2xl font-semibold text-ink">{selected && detail ? detail.canonical_name : 'Companies'}</h1>
      <p className="mt-1 max-w-3xl text-sm text-ink-soft">Company master built from deterministic email evidence and traceable imports. Relationships remain unverified until reviewed.</p>
    </div><button disabled={loading} onClick={() => setRevision(v=>v+1)} className="rounded-lg border border-line bg-surface px-4 py-2 text-sm disabled:opacity-40">{loading?'Loading…':'Refresh'}</button></header>
    {error && <div role="alert" className="mb-4 rounded-lg bg-fail-soft p-4 text-fail">{error}</div>}
    {!selected && <>
      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <div className={card}><p className="text-xs uppercase text-ink-soft">Matching companies</p><p className="mt-1 text-2xl font-semibold">{data?.total_count.toLocaleString()??'—'}</p><p className="text-xs text-ink-soft">Canonical corporate domains</p></div>
        <div className={card}><p className="text-xs uppercase text-ink-soft">Email sources linked</p><p className="mt-1 text-2xl font-semibold">{data?.sync.linked.toLocaleString()??'—'}</p><p className="text-xs text-ink-soft">Duplicates excluded</p></div>
        <div className={card}><p className="text-xs uppercase text-ink-soft">Email coverage</p><p className="mt-1 text-lg font-semibold">{data?`${data.sync.processed.toLocaleString()} / ${data.sync.total.toLocaleString()} checked`:'Checking…'}</p><p className="text-xs text-ink-soft">Deterministic · {date(data?.sync.last_synced??null)}</p></div>
      </div>
      <form className="mb-3 flex gap-2" onSubmit={e=>{e.preventDefault();setSearch(query.trim());setPage(1)}}><input aria-label="Search companies" placeholder="Search company name or domain" value={query} onChange={e=>setQuery(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"/><button className="rounded-lg bg-accent px-4 py-2 text-sm text-white">Search</button></form>
      <div className="mb-4 grid gap-2 md:grid-cols-3 lg:grid-cols-6">
        <select aria-label="Verification" value={verification} onChange={filter(setVerification)} className={select}><option value="all">All verification</option><option value="unverified">Unverified</option><option value="verified">Verified</option></select>
        <select aria-label="Origin" value={origin} onChange={filter(setOrigin)} className={select}><option value="all">All origins</option><option value="email">Email observed</option><option value="import">Imported</option></select>
        <select aria-label="Activity" value={activity} onChange={filter(setActivity)} className={select}><option value="all">All activity</option><option value="active">Active in 30 days</option><option value="inactive">Older activity</option><option value="none">No observed activity</option></select>
        <input aria-label="Location filter" placeholder="Location" value={location} onChange={filter(setLocation)} className={select}/>
        <input aria-label="Source filter" placeholder="Source, e.g. Dice" value={source} onChange={filter(setSource)} className={select}/>
        <select aria-label="Sort" value={sort} onChange={filter(setSort)} className={select}><option value="recent">Most recent</option><option value="name">Company name</option><option value="contacts">Most contacts</option><option value="sources">Most sources</option></select>
      </div>
      <div className="overflow-x-auto rounded-xl border border-line bg-surface"><table className="w-full text-left text-sm"><thead className="border-b border-line text-xs uppercase text-ink-soft"><tr>{['Company','Domain','Contacts','Email sources','Last activity','Verification'].map(x=><th key={x} className="p-3">{x}</th>)}</tr></thead><tbody>{data?.items.map(c=><tr key={c.company_id} className="border-b border-line last:border-0"><td className="p-3"><button onClick={()=>setSelected(c.company_id)} className="font-medium text-accent hover:underline">{c.canonical_name}</button></td><td className="p-3 text-ink-soft">{c.identity_domain}</td><td className="p-3">{c.contact_count}</td><td className="p-3">{c.source_count}</td><td className="p-3 text-ink-soft">{date(c.last_seen)}</td><td className="p-3"><span className="rounded-full bg-paper px-2 py-1 text-xs">{c.verification_status}</span></td></tr>)}</tbody></table>{!loading&&!data?.items.length&&<p className="p-8 text-center text-sm text-ink-soft">No companies match these filters.</p>}
        <PaginationControls page={page} pageCount={pageCount} pageSize={pageSize} totalCount={data?.total_count??0} onPageChange={setPage} onPageSizeChange={size=>{setPageSize(size);setPage(1)}}/>
      </div>
      <details className={`${card} mt-5`}><summary className="cursor-pointer font-medium">Import companies from portals or lists</summary><p className="mt-2 text-sm text-ink-soft">Paste CSV with company_name and domain. Optional columns: source, source_url, location, careers_url. Use the staffing company's own domain—not dice.com or another portal domain. Imports add provenance; only observed jobs, contacts, and emails increase activity.</p><textarea aria-label="Company import CSV" value={csvText} onChange={e=>setCsvText(e.target.value)} className="mt-3 h-40 w-full rounded-lg border border-line bg-paper p-3 font-mono text-xs"/><div className="mt-3 flex gap-2"><button onClick={()=>runImport(true)} className="rounded-lg border border-line px-3 py-2 text-sm">Preview</button><button onClick={()=>runImport(false)} className="rounded-lg bg-accent px-3 py-2 text-sm text-white">Import valid rows</button></div>{importResult&&<p className="mt-2 text-sm text-ink-soft">{importResult}</p>}</details>
      <p className="mt-5 text-xs text-ink-soft">Name-only mentions, shared providers, and relay senders remain in review. Company discovery and imports do not publish to CORE.</p>
    </>}
    {selected&&detail&&<>
      <div className="mb-5 flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-surface px-3 py-1">{detail.identity_domain}</span><span className="rounded-full bg-surface px-3 py-1">{detail.verification_status}</span><span className="rounded-full bg-surface px-3 py-1">{detail.claim_status}</span></div>
      <div className="mb-5 grid gap-3 sm:grid-cols-3"><div className={card}><p className="text-sm text-ink-soft">Unique requirements</p><p className="text-2xl font-semibold">{detail.job_requirements}</p></div><div className={card}><p className="text-sm text-ink-soft">Observed contacts</p><p className="text-2xl font-semibold">{detail.contact_count}</p></div><div className={card}><p className="text-sm text-ink-soft">30-day activity</p><p className="text-2xl font-semibold">{detail.activity.score} / 100</p></div></div>
      {detail.imports.length>0&&<section className={`${card} mb-5`}><h2 className="mb-2 font-semibold">Import provenance</h2>{detail.imports.map((i,n)=><p key={`${i.source_url}-${n}`} className="text-sm text-ink-soft">{i.source} · {i.imported_name}{i.location?` · ${i.location}`:''} · {date(i.imported_at)}</p>)}</section>}
      <details className={`${card} mb-5`}><summary className="cursor-pointer text-sm font-medium">How activity is calculated</summary><p className="mt-2 text-sm text-ink-soft">3 points per unique requirement (up to 60), 5 per observed contact (up to 25), and 15 for recent source activity. Imports alone add zero activity.</p></details>
      <section className={`${card} mb-5`}><h2 className="mb-2 font-semibold">Names observed in signatures</h2><p className="text-sm text-ink-soft">{detail.observed_names.map(x=>`${x.company_label} (${x.sources})`).join(' · ')||'No email observations yet'}</p></section>
      <section className={`${card} mb-5`}><h2 className="mb-3 font-semibold">Observed contacts</h2>{detail.contacts.map(c=><p key={c.email} className="border-t border-line py-2 text-sm">{c.name||'—'} · {c.email} · {c.source_count} sources · {date(c.last_seen)}</p>)}</section>
      <section><h2 className="mb-3 font-semibold">Source evidence and requirements</h2><div className="space-y-3">{detail.sources.map(s=><article key={s.draft_id} className={card}><div className="flex justify-between gap-2"><p className="text-sm font-medium">{s.company_label} · {s.contact_email||'website evidence'}</p><button className="text-sm text-accent" onClick={()=>onSelectDraft(s.draft_id)}>Open source draft</button></div><p className="mt-1 text-xs text-ink-soft">{s.channel} · {date(s.observed_at)}</p>{s.jobs.map((j,n)=><p key={`${j.key}-${n}`} className="mt-2 text-sm">{j.title}{j.location?` · ${j.location}`:''}{j.requires_review?' · Needs review':''}</p>)}</article>)}</div></section>
    </>}
  </main>
}
