import type { ReactNode } from 'react'
import type { TodayHealthCheck, TodayOverview } from '../types'

export type TodayTarget = 'drafts' | 'taxonomy' | 'reports' | 'skills'

const n = (v: number | null | undefined) => (v ?? 0).toLocaleString()

function ago(mins: number | null | undefined): string {
  if (mins === null || mins === undefined) return 'never'
  if (mins < 1) return 'just now'
  if (mins < 60) return `${Math.round(mins)} min ago`
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`
  return `${Math.round(mins / 1440)} d ago`
}

function minutesSince(iso: string | null | undefined): number | null {
  if (!iso) return null
  return (Date.now() - new Date(iso).getTime()) / 60000
}

const DOT: Record<TodayHealthCheck['status'], string> = {
  ok: 'bg-pass',
  warn: 'bg-warn',
  fail: 'bg-fail',
}

function Card({ title, hint, children, className = '' }: { title: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl border border-line bg-surface p-5 ${className}`}>
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-ink-soft">{hint}</p>}
      </div>
      {children}
    </section>
  )
}

function InboxRow({
  label,
  count,
  detail,
  cta,
  onClick,
}: {
  label: string
  count: number | null | undefined
  detail: string
  cta: string
  onClick: () => void
}) {
  const clear = (count ?? 0) === 0
  return (
    <div className="flex items-center gap-4 rounded-xl border border-line bg-paper px-4 py-3">
      <div
        className={`flex h-11 min-w-11 items-center justify-center rounded-xl px-2 text-base font-semibold ${
          clear ? 'bg-pass-soft text-pass' : 'bg-warn-soft text-warn'
        }`}
      >
        {clear ? '✓' : n(count)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-ink">{label}</div>
        <div className="truncate text-xs text-ink-soft">{clear ? 'Nothing waiting. All clear.' : detail}</div>
      </div>
      <button
        onClick={onClick}
        className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
          clear ? 'border border-line text-ink-soft hover:text-ink' : 'bg-accent text-white hover:opacity-90'
        }`}
      >
        {clear ? 'Open' : cta}
      </button>
    </div>
  )
}

function Step({ label, value, sub, last }: { label: string; value: string; sub?: string; last?: boolean }) {
  return (
    <div className="flex flex-1 items-stretch">
      <div className="flex-1 rounded-xl bg-paper px-4 py-3">
        <div className="text-[11px] font-medium uppercase tracking-wide text-ink-soft">{label}</div>
        <div className="mt-1 text-xl font-semibold text-ink">{value}</div>
        {sub && <div className="mt-0.5 text-xs text-ink-soft">{sub}</div>}
      </div>
      {!last && <div className="flex items-center px-1.5 text-ink-soft">›</div>}
    </div>
  )
}

function Bar({ label, pct }: { label: string; pct: number }) {
  const tone = pct >= 80 ? 'bg-pass' : pct >= 50 ? 'bg-warn' : 'bg-fail'
  return (
    <div className="flex items-center gap-3 text-xs">
      <div className="w-28 shrink-0 text-ink-soft">{label}</div>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-line">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.max(2, Math.min(100, pct))}%` }} />
      </div>
      <div className="w-12 shrink-0 text-right font-medium text-ink">{pct}%</div>
    </div>
  )
}

const FILL_LABELS: [string, string][] = [
  ['job_title', 'Job title'],
  ['location', 'Location'],
  ['required_skills', 'Skills'],
  ['recruiter_email', 'Recruiter email'],
  ['employment_type', 'Employment type'],
  ['work_mode', 'Work mode'],
  ['rate', 'Pay rate'],
  ['duration', 'Duration'],
]

export function TodayPage({
  data,
  error,
  loading,
  onRefresh,
  onGo,
}: {
  data: TodayOverview | null
  error: string | null
  loading: boolean
  onRefresh: () => void
  onGo: (target: TodayTarget) => void
}) {
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'

  const problems = data?.health.filter((c) => c.status !== 'ok') ?? []
  const failing = problems.some((c) => c.status === 'fail')
  const drafts = data?.inbox.drafts
  const pipeline = data?.pipeline
  const auto = data?.automation
  const active = data?.jobs?.active

  const humanTotal = (data?.inbox.skills ?? 0) + (data?.inbox.job_titles ?? 0) + (data?.inbox.boilerplate ?? 0) + (drafts?.needs_review ?? 0)
  const oldestDays = drafts?.oldest_needs_review_at ? Math.floor((minutesSince(drafts.oldest_needs_review_at) ?? 0) / 1440) : null
  const expiresIn = drafts?.expires_after_days !== undefined && oldestDays !== null ? Math.max(0, drafts.expires_after_days - oldestDays) : null

  const sent = pipeline?.core_pushes?.pushed ?? pipeline?.core_pushes?.success ?? 0
  const waiting = Object.entries(pipeline?.outbox?.states ?? {})
    .filter(([k]) => k !== 'pushed')
    .reduce((s, [, v]) => s + v, 0)

  const triage = auto?.triage
  const tAppr = (triage?.skills?.approved ?? 0) + (triage?.titles?.approved ?? 0) + (triage?.boilerplate?.approved ?? 0)
  const tRej = (triage?.skills?.rejected ?? 0) + (triage?.titles?.rejected ?? 0) + (triage?.boilerplate?.rejected ?? 0)

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ink">{greeting}</h1>
          <p className="mt-1 text-sm text-ink-soft">
            {data ? (humanTotal === 0 ? 'Nothing needs you right now.' : `${n(humanTotal)} items are waiting for a human decision.`) : 'Loading today’s summary…'}
          </p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-soft transition hover:text-ink disabled:opacity-50"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      {error && <div className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}

      {data && (
        <>
          {/* 1. Is everything running? */}
          <div
            className={`mb-6 rounded-2xl border px-5 py-4 ${
              failing ? 'border-fail bg-fail-soft' : problems.length ? 'border-warn bg-warn-soft' : 'border-pass bg-pass-soft'
            }`}
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <span className={`inline-block h-2.5 w-2.5 rounded-full ${failing ? 'bg-fail' : problems.length ? 'bg-warn' : 'bg-pass'}`} />
              {failing ? 'Something needs attention' : problems.length ? 'Running, with a few things to watch' : 'Everything is running normally'}
            </div>
            <ul className="mt-3 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {data.health.map((c) => (
                <li key={c.id} className="flex items-start gap-2 text-xs">
                  <span className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${DOT[c.status]}`} />
                  <span className="text-ink">
                    <span className="font-medium">{c.label}.</span> <span className="text-ink-soft">{c.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="grid gap-6 lg:grid-cols-5">
            {/* 2. What needs me? */}
            <Card title="Needs you today" hint="Only things Hermes cannot decide on its own." className="lg:col-span-3">
              <div className="space-y-2.5">
                <InboxRow
                  label="Job emails to check"
                  count={drafts?.needs_review}
                  detail={
                    expiresIn !== null
                      ? `Oldest has ${expiresIn} day${expiresIn === 1 ? '' : 's'} left before it is removed automatically.`
                      : 'Parsed emails that are missing key details.'
                  }
                  cta="Review emails"
                  onClick={() => onGo('drafts')}
                />
                <InboxRow
                  label="New skills to decide"
                  count={data.inbox.skills}
                  detail="Hermes is unsure if these are real tools or technologies."
                  cta="Decide skills"
                  onClick={() => onGo('taxonomy')}
                />
                <InboxRow
                  label="New job titles to decide"
                  count={data.inbox.job_titles}
                  detail="Titles seen across several senders that need a yes or no."
                  cta="Decide titles"
                  onClick={() => onGo('taxonomy')}
                />
                <InboxRow
                  label="Repeated text lines to decide"
                  count={data.inbox.boilerplate}
                  detail="Lines seen across many senders. Approve to strip footers, reject to keep job content."
                  cta="Review lines"
                  onClick={() => onGo('taxonomy')}
                />
              </div>
            </Card>

            {/* 3. What did Hermes do? */}
            <Card title="Hermes did this for you" hint="No action needed." className="lg:col-span-2">
              <dl className="space-y-3 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-ink-soft">Last automatic review</dt>
                  <dd className="text-right font-medium text-ink">{ago(triage?.minutes_ago)}</dd>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-ink-soft">Decided in that run</dt>
                  <dd className="text-right font-medium text-ink">
                    {n(tAppr)} approved · {n(tRej)} rejected
                  </dd>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-ink-soft">Old emails removed (24 h)</dt>
                  <dd className="text-right font-medium text-ink">{n(auto?.expiry?.removed_last_24h)}</dd>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-ink-soft">Senders blocked automatically</dt>
                  <dd className="text-right font-medium text-ink">{n(auto?.daily_cleanup?.auto_blocks_active)}</dd>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-ink-soft">Daily clean-up</dt>
                  <dd className="text-right font-medium text-ink">
                    {ago(minutesSince(auto?.daily_cleanup?.last_run?.ran_at))}
                  </dd>
                </div>
              </dl>
              {active && (
                <div className="mt-5 rounded-xl bg-paper px-4 py-3">
                  <div className="mb-1.5 flex justify-between text-xs">
                    <span className="font-medium text-ink">Re-processing old emails</span>
                    <span className="text-ink-soft">{active.percent}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-line">
                    <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(2, active.percent)}%` }} />
                  </div>
                  <div className="mt-1.5 text-xs text-ink-soft">
                    {n(active.processed)} of {n(active.total)}
                    {active.failed ? ` · ${n(active.failed)} failed` : ''}
                  </div>
                </div>
              )}
            </Card>
          </div>

          {/* 4. Is the job pipeline healthy? */}
          <Card
            title="From email to Jobfynder job"
            hint={`Last ${pipeline?.window_days ?? 14} days. This is what ends up as job postings in Jobfynder.`}
            className="mt-6"
          >
            {pipeline && !pipeline.error ? (
              <>
                <div className="flex flex-col gap-2 md:flex-row">
                  <Step label="Job emails" value={n(pipeline.live_posts)} sub="parsed and live" />
                  <Step label="Complete enough" value={n(pipeline.ready)} sub={`${pipeline.ready_pct}% of them`} />
                  <Step label="Distinct roles" value={n(pipeline.distinct_roles)} sub={`${n(pipeline.roles_with_duplicates)} reposted by several vendors`} />
                  <Step label="Queued for Core" value={n(waiting)} sub={pipeline.outbox?.dispatch_enabled ? 'sending on' : 'sending is off'} />
                  <Step label="Sent to Core" value={n(sent)} last />
                </div>
                {(pipeline.only_employment_type_missing ?? 0) > 0 && (
                  <p className="mt-4 rounded-lg bg-warn-soft px-4 py-2.5 text-xs text-ink">
                    <span className="font-semibold">Biggest gap:</span> {n(pipeline.only_employment_type_missing)} emails are complete except for
                    the employment type (contract, full-time…). They cannot go to Core until that is filled in.
                  </p>
                )}
                <div className="mt-5 grid gap-x-10 gap-y-2.5 md:grid-cols-2">
                  {FILL_LABELS.map(([key, label]) => (
                    <Bar key={key} label={label} pct={pipeline.fill_rates_pct?.[key] ?? 0} />
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-ink-soft">Pipeline figures are not available right now. They will return on the next refresh.</p>
            )}
          </Card>

          <div className="mt-6 flex flex-wrap gap-3 text-xs text-ink-soft">
            <button onClick={() => onGo('reports')} className="underline-offset-2 hover:text-ink hover:underline">
              Open detailed reports
            </button>
            <span>·</span>
            <button onClick={() => onGo('skills')} className="underline-offset-2 hover:text-ink hover:underline">
              Browse the skills library
            </button>
            <span className="ml-auto">Updated {new Date(data.generated_at).toLocaleTimeString()}</span>
          </div>
        </>
      )}
    </div>
  )
}
