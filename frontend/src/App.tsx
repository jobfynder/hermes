import { useCallback, useEffect, useState } from 'react'
import { api, clearToken } from './api/client'
import { TokenGate } from './components/TokenGate'
import { AccuracyPage } from './pages/AccuracyPage'
import { AssistantPage } from './pages/AssistantPage'
import { CompaniesPage } from './pages/CompaniesPage'
import { DraftDetailPage } from './pages/DraftDetailPage'
import { DraftListPage } from './pages/DraftListPage'
import { JobTitlesTaxonomyPage } from './pages/JobTitlesTaxonomyPage'
import { ReportsPage } from './pages/ReportsPage'
import { ReviewQueuePage } from './pages/ReviewQueuePage'
import { SkillsTaxonomyPage } from './pages/SkillsTaxonomyPage'
import { TodayPage, type TodayTarget } from './pages/TodayPage'
import type { TodayOverview } from './types'

type View =
  | { name: 'today' }
  | { name: 'list' }
  | { name: 'detail'; draftId: string; returnToCompanies?: boolean }
  | { name: 'review' }
  | { name: 'accuracy' }
  | { name: 'skills' }
  | { name: 'job-titles' }
  | { name: 'reports' }
  | { name: 'companies' }
  | { name: 'assistant' }

type NavItem = { id: View['name']; label: string; badge?: number | null }

function NavButton({ item, active, onClick }: { item: NavItem; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center justify-between gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm transition ${
        active ? 'bg-accent-soft font-semibold text-accent' : 'text-ink-soft hover:bg-paper hover:text-ink'
      }`}
    >
      <span>{item.label}</span>
      {item.badge ? (
        <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn">
          {item.badge > 9999 ? '9999+' : item.badge.toLocaleString()}
        </span>
      ) : null}
    </button>
  )
}

function AppShell() {
  const [view, setView] = useState<View>(() => ({
    name: new URLSearchParams(window.location.search).get('view') === 'companies' ? 'companies' : 'today',
  }))
  const [today, setToday] = useState<TodayOverview | null>(null)
  const [todayError, setTodayError] = useState<string | null>(null)
  const [todayLoading, setTodayLoading] = useState(false)

  const loadToday = useCallback((refresh = false) => {
    setTodayLoading(true)
    api
      .getToday(refresh)
      .then((d) => {
        setToday(d)
        setTodayError(null)
      })
      .catch((e) => setTodayError(e instanceof Error ? e.message : 'Could not load the summary.'))
      .finally(() => setTodayLoading(false))
  }, [])

  useEffect(() => {
    loadToday()
    const timer = window.setInterval(() => loadToday(), 120000)
    return () => window.clearInterval(timer)
  }, [loadToday])

  const reviewBadge = (today?.inbox.skills ?? 0) + (today?.inbox.job_titles ?? 0) + (today?.inbox.boilerplate ?? 0)
  const attention = today?.health.filter((c) => c.status !== 'ok').length ?? 0

  const groups: { title: string | null; items: NavItem[] }[] = [
    { title: null, items: [{ id: 'today', label: 'Today', badge: attention || null }] },
    {
      title: 'Work queue',
      items: [
        { id: 'list', label: 'Job emails', badge: today?.inbox.drafts?.needs_review },
        { id: 'review', label: 'Review queue', badge: reviewBadge },
      ],
    },
    {
      title: 'Library',
      items: [
        { id: 'skills', label: 'Skills' },
        { id: 'job-titles', label: 'Job titles' },
        { id: 'companies', label: 'Companies' },
      ],
    },
    {
      title: 'Insights',
      items: [
        { id: 'reports', label: 'Reports' },
        { id: 'accuracy', label: 'Accuracy' },
        { id: 'assistant', label: 'Ask Hermes' },
      ],
    },
  ]

  const activeId = view.name === 'detail' ? (view.returnToCompanies ? 'companies' : 'list') : view.name
  const go = (name: View['name']) => setView({ name } as View)

  const goFromToday = (target: TodayTarget) => {
    if (target === 'drafts') go('list')
    else if (target === 'taxonomy') go('review')
    else if (target === 'reports') go('reports')
    else go('skills')
  }

  return (
    <div className="min-h-screen bg-paper md:flex">
      <aside className="border-b border-line bg-surface md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0 md:overflow-y-auto md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-5 py-4 md:block">
          <button onClick={() => go('today')} className="text-left">
            <div className="text-base font-semibold text-ink">Hermes</div>
            <div className="text-[11px] text-ink-soft">Job email intelligence</div>
          </button>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:block md:space-y-5 md:overflow-visible md:pb-6">
          {groups.map((g) => (
            <div key={g.title ?? 'top'} className="flex gap-1 md:block md:space-y-0.5">
              {g.title && (
                <div className="hidden px-3 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wider text-ink-soft md:block">
                  {g.title}
                </div>
              )}
              {g.items.map((item) => (
                <NavButton key={item.id} item={item} active={activeId === item.id} onClick={() => go(item.id)} />
              ))}
            </div>
          ))}
          <button
            onClick={() => {
              clearToken()
              window.location.reload()
            }}
            className="rounded-lg px-3 py-2 text-left text-sm text-ink-soft hover:bg-paper hover:text-ink md:mt-4 md:block md:w-full"
          >
            Sign out
          </button>
        </nav>
      </aside>

      <main className="min-w-0 flex-1">
        {view.name === 'today' && (
          <TodayPage data={today} error={todayError} loading={todayLoading} onRefresh={() => loadToday(true)} onGo={goFromToday} />
        )}
        {view.name === 'detail' && (
          <DraftDetailPage
            draftId={view.draftId}
            onBack={() => setView(view.returnToCompanies ? { name: 'companies' } : { name: 'list' })}
          />
        )}
        {view.name === 'review' && <ReviewQueuePage />}
        {view.name === 'accuracy' && <AccuracyPage onBack={() => go('today')} />}
        {view.name === 'skills' && <SkillsTaxonomyPage onBack={() => go('today')} />}
        {view.name === 'job-titles' && <JobTitlesTaxonomyPage onBack={() => go('today')} />}
        {view.name === 'companies' && (
          <CompaniesPage onSelectDraft={(id) => setView({ name: 'detail', draftId: id, returnToCompanies: true })} />
        )}
        {view.name === 'reports' && <ReportsPage onBack={() => go('today')} />}
        {view.name === 'assistant' && <AssistantPage onBack={() => go('today')} />}
        {view.name === 'list' && <DraftListPage onSelect={(id) => setView({ name: 'detail', draftId: id })} />}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <TokenGate>
      <AppShell />
    </TokenGate>
  )
}
