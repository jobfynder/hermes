import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { SyncCheck, SyncStatus } from '../types'

const n = (v: number | null | undefined) => (v ?? 0).toLocaleString()

function ago(mins: number | null | undefined): string {
  if (mins === null || mins === undefined) return 'never'
  if (mins < 1) return 'just now'
  if (mins < 60) return `${Math.round(mins)} min ago`
  if (mins < 1440) return `${(mins / 60).toFixed(1)} h ago`
  return `${(mins / 1440).toFixed(1)} days ago`
}

const DOT = { ok: 'bg-pass', warn: 'bg-warn', fail: 'bg-fail' } as const
const BANNER = {
  ok: ['border-pass bg-pass-soft', 'Working normally'],
  warn: ['border-warn bg-warn-soft', 'Working, with things to watch'],
  fail: ['border-fail bg-fail-soft', 'Needs attention'],
} as const

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-paper px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wide text-ink-soft">{label}</div>
      <div className="mt-1 text-xl font-semibold text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-soft">{sub}</div>}
    </div>
  )
}

function Panel({
  title,
  subtitle,
  overall,
  checks,
  children,
}: {
  title: string
  subtitle: string
  overall: 'ok' | 'warn' | 'fail'
  checks: SyncCheck[]
  children?: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <p className="mt-0.5 text-xs text-ink-soft">{subtitle}</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-semibold text-ink ${BANNER[overall][0]}`}>
          <span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${DOT[overall]}`} />
          {BANNER[overall][1]}
        </span>
      </div>
      <ul className="space-y-2.5">
        {checks.map((c) => (
          <li key={c.id} className="rounded-xl border border-line px-4 py-2.5">
            <div className="flex items-start gap-2.5">
              <span className={`mt-1.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full ${DOT[c.status]}`} />
              <div className="min-w-0">
                <div className="text-sm font-medium text-ink">{c.label}</div>
                <div className="text-xs text-ink-soft">{c.detail}</div>
                {c.action && <div className="mt-1 text-xs font-medium text-warn">{c.action}</div>}
              </div>
            </div>
          </li>
        ))}
        {checks.length === 0 && <li className="text-sm text-ink-soft">No data yet.</li>}
      </ul>
      {children}
    </section>
  )
}

export function SyncStatusPage() {
  const [data, setData] = useState<SyncStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback((refresh = false) => {
    setLoading(true)
    api
      .getSyncStatus(refresh)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load sync status.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const t = window.setInterval(() => load(), 60000)
    return () => window.clearInterval(t)
  }, [load])

  const parsing = data?.parsing
  const ob = data?.outbox
  const iq = data?.inbox_quarantine
  const svc = data?.service
  const rec = svc?.reconciliation

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Sync status</h1>
          <p className="mt-1 text-sm text-ink-soft">Is email parsing flowing, and is Hermes in step with Twenty CRM? Refreshes every minute.</p>
        </div>
        <button
          onClick={() => load(true)}
          disabled={loading}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-soft transition hover:text-ink disabled:opacity-50"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      {error && <div className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}
      {!data && !error && <div className="text-sm text-ink-soft">Loading…</div>}

      {data && (
        <div className="space-y-6">
          <Panel
            title="Email parsing"
            subtitle="Email arrives, is parsed, then waits for review or goes on to Core."
            overall={data.overall.parsing}
            checks={data.checks.filter((c) => c.group === 'parsing')}
          >
            {parsing && !parsing.error && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Tile label="Last email" value={ago(parsing.last_email_minutes_ago)} />
                <Tile label="Parsed (24 h)" value={n(parsing.parsed_24h)} sub={`${n(parsing.parsed_1h)} in the last hour`} />
                <Tile label="Ready / need review" value={`${n(parsing.ready_24h)} / ${n(parsing.needs_review_24h)}`} sub="today" />
                <Tile label="Spam filtered" value={n(parsing.spam_24h)} sub="today" />
              </div>
            )}
            {parsing?.intake_24h && Object.keys(parsing.intake_24h).length > 0 && (
              <p className="mt-3 text-xs text-ink-soft">
                Intake outcomes, last 24 h:{' '}
                {Object.entries(parsing.intake_24h)
                  .map(([k, v]) => `${k.replace(/_/g, ' ')} ${n(v)}`)
                  .join(' · ')}
              </p>
            )}
          </Panel>

          <Panel
            title="Twenty CRM sync"
            subtitle="Companies, hiring signals and recruiters flowing from Hermes into Twenty."
            overall={data.overall.twenty}
            checks={data.checks.filter((c) => c.group === 'twenty')}
          >
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Tile label="Last delivery" value={ago(svc?.last_success_minutes_ago)} />
              <Tile label="Sent (last hour)" value={n(ob?.published_1h)} sub={`${n(ob?.published_24h)} in 24 h`} />
              <Tile label="Waiting to send" value={n(ob?.backlog)} sub={ob?.oldest_backlog_minutes ? `oldest ${ago(ob.oldest_backlog_minutes)}` : 'none waiting'} />
              <Tile label="In quarantine" value={n(iq?.quarantine_open)} sub="need a person" />
            </div>

            {rec && (
              <div className="mt-4 rounded-xl border border-line px-4 py-3 text-xs text-ink-soft">
                <span className="font-semibold text-ink">Nightly reconciliation:</span> {rec.status ?? 'unknown'} for {rec.day ?? '—'} ·{' '}
                {n(rec.checked)} checked · {n(rec.verified)} verified · {n(rec.exceptions)} exceptions
              </div>
            )}

            {data.alerts.active && data.alerts.active.length > 0 && (
              <div className="mt-4">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Active alerts from the sync</h3>
                <div className="overflow-hidden rounded-xl border border-line">
                  <table className="w-full text-left text-sm">
                    <tbody>
                      {data.alerts.active.map((a) => (
                        <tr key={a.code} className="border-b border-line last:border-0">
                          <td className="px-3 py-2 text-ink">{a.label}</td>
                          <td className="whitespace-nowrap px-3 py-2 text-xs text-ink-soft">
                            {a.count}× · open {a.since_days} days · last {ago(a.last_seen_minutes_ago)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {iq?.quarantine_by_reason && iq.quarantine_by_reason.length > 0 && (
              <div className="mt-4">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Quarantine, by reason</h3>
                <div className="overflow-hidden rounded-xl border border-line">
                  <table className="w-full text-left text-sm">
                    <tbody>
                      {iq.quarantine_by_reason.map((q) => (
                        <tr key={q.reason} className="border-b border-line last:border-0">
                          <td className="px-3 py-2 text-ink">{q.reason.replace(/_/g, ' ').toLowerCase()}</td>
                          <td className="px-3 py-2 text-right font-medium text-ink">{n(q.count)}</td>
                          <td className="whitespace-nowrap px-3 py-2 text-right text-xs text-ink-soft">oldest {q.oldest_days} days</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </Panel>

          <p className="text-xs text-ink-soft">Updated {new Date(data.generated_at).toLocaleTimeString()}. This page only reads the sync’s records; it never changes the sync.</p>
        </div>
      )}
    </div>
  )
}
