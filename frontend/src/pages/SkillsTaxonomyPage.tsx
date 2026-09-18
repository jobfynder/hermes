import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PaginationControls } from '../components/Pagination'
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

function EditRow({
  entry,
  categories,
  onSave,
  onCancel,
  onDelete,
}: {
  entry: CanonicalSkillEntry
  categories: string[]
  onSave: (changes: { newName?: string; category?: string }) => Promise<void>
  onCancel: () => void
  onDelete: () => void
}) {
  // Must render the same number of <td>s, in the same order, as the
  // header row and the non-editing row -- see the equivalent note on
  // JobTitlesTaxonomyPage's EditRow, where a missing cell here once
  // shifted every field one column left.
  const [name, setName] = useState(entry.name)
  const [categoryValue, setCategoryValue] = useState(entry.category || 'Uncategorized')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const categoryOptions = Array.from(new Set([...categories, categoryValue, 'Uncategorized'])).sort()

  async function handleSave() {
    if (!name.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      await onSave({
        newName: name.trim() !== entry.name ? name.trim() : undefined,
        category: categoryValue !== (entry.category || 'Uncategorized') ? categoryValue : undefined,
      })
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <tr className="border-b border-line bg-paper last:border-0 align-top">
      <td className="px-4 py-2.5"></td>
      <td className="max-w-xl px-4 py-2.5">
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded border border-accent bg-surface px-2 py-1 text-sm text-ink outline-none"
        />
        {saveError && <div className="mt-1 text-xs text-fail">{saveError}</div>}
      </td>
      <td className="px-4 py-2.5">
        <select
          value={categoryValue}
          onChange={(e) => setCategoryValue(e.target.value)}
          className="w-full rounded border border-line bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-accent"
        >
          {categoryOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </td>
      <td className="px-4 py-2.5 text-ink-soft">{entry.times_seen}</td>
      <td className="px-4 py-2.5 text-ink-soft">{timeAgo(entry.last_seen_at)}</td>
      <td className="px-4 py-2.5 text-right">
        <div className="flex justify-end gap-3">
          <button
            disabled={saving || !name.trim()}
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
          <button
            disabled={saving}
            onClick={onDelete}
            className="text-xs font-medium text-fail hover:underline disabled:opacity-40"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  )
}

export function SkillsTaxonomyPage({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<CanonicalSkillEntry[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [taxonomyCount, setTaxonomyCount] = useState(0)
  const [categories, setCategories] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [sortKey, setSortKey] = useState<SortKey>('times_seen')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [editingName, setEditingName] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkCategory, setBulkCategory] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const pageCount = Math.max(1, Math.ceil(totalCount / pageSize))

  useEffect(() => { const timer=window.setTimeout(()=>{setSearch(searchInput.trim());setPage(1)},300); return()=>window.clearTimeout(timer) }, [searchInput])
  useEffect(() => { setSelected(new Set()); setEditingName(null) }, [search,category,sortKey,page,pageSize])
  useEffect(() => {
    const controller=new AbortController();setLoading(true);setError(null)
    const params=new URLSearchParams({q:search,category,sort:sortKey,page:String(page),page_size:String(pageSize)})
    api.browseSkillsTaxonomyPage(params,controller.signal).then(result=>{if(controller.signal.aborted)return;setItems(result.items);setTotalCount(result.total_count);setTaxonomyCount(result.taxonomy_count);setCategories(result.categories);if(result.page!==page)setPage(result.page)}).catch(err=>{if(!controller.signal.aborted)setError(err.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[search,category,sortKey,page,pageSize,revision])
  const reload=()=>setRevision(v=>v+1)
  async function handleSaveDescription(name:string,description:string){const r=await api.updateSkillDescription(name,description);if(!r.updated)throw new Error(r.reason||'Update failed');setItems(prev=>prev.map(s=>s.name===name?{...s,description,description_source:'human_edited'}:s))}
  async function handleEditSave(entry:CanonicalSkillEntry,changes:{newName?:string;category?:string}){if(!changes.newName&&!changes.category){setEditingName(null);return}const r=await api.updateSkill(entry.name,changes);if(!r.updated)throw new Error(r.reason==='duplicate_skill'?'That skill already exists.':r.reason||'Update failed');setEditingName(null);reload()}
  async function handleDelete(name:string){if(!window.confirm(`Delete "${name}" from the skills taxonomy? This can't be undone.`))return;setBusy(true);try{const r=await api.deleteSkill(name);if(!r.deleted)throw new Error(r.reason||'Delete failed');setSelected(new Set());reload()}catch(err){setError(err instanceof Error?err.message:'Delete failed')}finally{setBusy(false)}}
  function toggleSelected(name:string){setSelected(prev=>{const next=new Set(prev);next.has(name)?next.delete(name):next.add(name);return next})}
  function togglePage(){setSelected(items.length>0&&items.every(s=>selected.has(s.name))?new Set():new Set(items.map(s=>s.name)))}
  async function handleBulkSetCategory(){if(!selected.size||!bulkCategory.trim())return;setBusy(true);try{const r=await api.bulkSetSkillCategory([...selected],bulkCategory.trim());setActionMessage(`Updated ${r.updated_count} selected skills.`);setSelected(new Set());setBulkCategory('');reload()}catch(err){setError(err instanceof Error?err.message:'Bulk update failed')}finally{setBusy(false)}}
  async function handleBulkDelete(){if(!selected.size)return;if(!window.confirm(`Delete ${selected.size} skills selected on this page? This can't be undone.`))return;setBusy(true);try{const r=await api.bulkDeleteSkills([...selected]);setActionMessage(`Deleted ${r.deleted_count} skills.`);setSelected(new Set());reload()}catch(err){setError(err instanceof Error?err.message:'Bulk delete failed')}finally{setBusy(false)}}
  const pageAllSelected=items.length>0&&items.every(s=>selected.has(s.name))
  return <div className="mx-auto max-w-6xl px-6 py-8">
    <header className="mb-6 flex flex-wrap items-baseline justify-between gap-3"><div><h1 className="text-xl font-semibold text-ink">Skills taxonomy</h1><p className="mt-1 text-sm text-ink-soft">{taxonomyCount?`${taxonomyCount.toLocaleString()} canonical skills`:'Loading…'} · server-side search and page-level selection</p></div><button onClick={onBack} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink-soft">Back to drafts</button></header>
    {error&&<div role="alert" className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}{actionMessage&&<div className="mb-4 rounded-lg border border-line bg-paper px-4 py-3 text-sm text-ink-soft">{actionMessage}</div>}
    <div className="mb-4 flex flex-wrap gap-3"><input aria-label="Search skills" value={searchInput} onChange={e=>setSearchInput(e.target.value)} placeholder="Search skill or alias…" className="min-w-56 flex-1 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"/><select aria-label="Skill category" value={category} onChange={e=>{setCategory(e.target.value);setPage(1)}} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"><option value="all">All categories</option>{categories.map(c=><option key={c}>{c}</option>)}</select><select aria-label="Skill sort" value={sortKey} onChange={e=>{setSortKey(e.target.value as SortKey);setPage(1)}} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"><option value="times_seen">Most used</option><option value="last_seen_at">Recently seen</option><option value="name">Name</option></select></div>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-paper px-3 py-2"><span className="text-xs text-ink-soft">{selected.size?`${selected.size} selected on this page`:`${totalCount.toLocaleString()} matching skills`}</span>{selected.size>0&&<div className="flex flex-wrap items-center gap-2"><button onClick={()=>setSelected(new Set())} className="text-xs text-ink-soft hover:underline">Clear selection</button><input list="skill-categories" value={bulkCategory} onChange={e=>setBulkCategory(e.target.value)} placeholder="Set category to…" className="min-w-40 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm"/><datalist id="skill-categories">{categories.map(c=><option key={c} value={c}/>)}</datalist><button disabled={busy||!bulkCategory.trim()} onClick={handleBulkSetCategory} className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">Apply to selected</button><button disabled={busy} onClick={handleBulkDelete} className="rounded-lg border border-fail px-3 py-1.5 text-xs font-semibold text-fail disabled:opacity-40">Delete selected</button></div>}</div>
    <div className="overflow-hidden rounded-xl border border-line bg-surface"><table className="w-full text-left text-sm"><thead><tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft"><th className="w-8 px-4 py-3"><input type="checkbox" checked={pageAllSelected} onChange={togglePage} disabled={!items.length||loading} aria-label="Select this page" title={`Select the ${items.length} skills on this page only`} className="accent-accent"/></th><th className="px-4 py-3">Skill</th><th className="px-4 py-3">Category</th><th className="px-4 py-3">Times seen</th><th className="px-4 py-3">Last seen</th><th></th></tr></thead><tbody>
      {items.map(s=>editingName===s.name?<EditRow key={s.name} entry={s} categories={categories} onSave={changes=>handleEditSave(s,changes)} onCancel={()=>setEditingName(null)} onDelete={()=>handleDelete(s.name)}/>:<tr key={s.name} className="border-b border-line last:border-0 align-top"><td className="px-4 py-2.5"><input type="checkbox" checked={selected.has(s.name)} onChange={()=>toggleSelected(s.name)} aria-label={`Select ${s.name}`} className="accent-accent"/></td><td className="max-w-xl px-4 py-2.5"><div className="group flex items-center gap-2"><span className="font-medium text-ink" title={s.aliases.length?`Aliases: ${s.aliases.join(', ')}`:undefined}>{s.name}</span><button onClick={()=>setEditingName(s.name)} className="text-xs text-ink-soft opacity-0 group-hover:opacity-100">Edit</button></div><DescriptionCell skill={s} onSave={handleSaveDescription}/></td><td className="px-4 py-2.5 text-ink-soft">{s.category||'—'}</td><td className="px-4 py-2.5 text-ink-soft">{s.times_seen}</td><td className="px-4 py-2.5 text-ink-soft">{timeAgo(s.last_seen_at)}</td><td className="px-4 py-2.5 text-right"><button onClick={()=>handleDelete(s.name)} className="text-xs font-medium text-fail">Delete</button></td></tr>)}
      {!loading&&!items.length&&<tr><td colSpan={6} className="px-4 py-10 text-center text-ink-soft">No skills match these filters.</td></tr>}{loading&&!items.length&&<tr><td colSpan={6} className="px-4 py-10 text-center text-ink-soft">Loading…</td></tr>}
    </tbody></table><PaginationControls page={page} pageCount={pageCount} pageSize={pageSize} totalCount={totalCount} onPageChange={setPage} onPageSizeChange={size=>{setPageSize(Math.min(100,size));setPage(1)}}/></div>
  </div>
}
