import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DashboardOverview } from '../types'

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-ink-soft">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-soft">{sub}</div>}
    </div>
  )
}

function ageColor(days: number): string {
  if (days >= 3) return 'text-fail'
  if (days >= 1) return 'text-warn'
  return 'text-ink-soft'
}

/** A minimal inline-SVG bar chart -- no charting library dependency.
 * Renders one bar per data point, scaled to the max value, with a
 * hover title showing the exact number. */
function BarChart({
  data,
  height = 80,
  barColor = 'var(--color-accent, #4f46e5)',
  formatValue,
}: {
  data: { label: string; value: number }[]
  height?: number
  barColor?: string
  formatValue?: (v: number) => string
}) {
  if (data.length === 0) {
    return <div className="flex h-20 items-center justify-center text-xs text-ink-soft">No data yet</div>
  }
  const max = Math.max(...data.map((d) => d.value), 0.0001)
  const barWidth = 100 / data.length

  return (
    <div className="flex items-end gap-px" style={{ height }}>
      {data.map((d, i) => (
        <div
          key={i}
          className="group relative flex-1"
          style={{ height: '100%' }}
          title={`${d.label}: ${formatValue ? formatValue(d.value) : d.value}`}
        >
          <div className="flex h-full items-end">
            <div
              className="w-full rounded-t transition group-hover:opacity-80"
              style={{
                height: `${Math.max(2, (d.value / max) * 100)}%`,
                backgroundColor: barColor,
                minWidth: `${barWidth}%`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function fmtMoney(n: number): string {
  return `$${n.toFixed(n < 1 ? 4 : 2)}`
}

function fmtDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function ReportsPage({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<DashboardOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function load() {
    setLoading(true)
    setError(null)
    api
      .getDashboardOverview()
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Reports</h1>
          <p className="mt-1 text-sm text-ink-soft">
            Taxonomy growth, review-queue health, automated triage activity, LLM cost, and parsing quality.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            disabled={loading}
            onClick={load}
            className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-soft transition hover:text-ink disabled:opacity-40"
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
          <button
            onClick={onBack}
            className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-soft transition hover:text-ink"
          >
            Back to drafts
          </button>
        </div>
      </header>

      {error && <div className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}

      {!data && !error && <div className="py-10 text-center text-sm text-ink-soft">Loading…</div>}

      {data && (
        <div className="space-y-8">
          <section>
            <h2 className="mb-3 text-sm font-semibold text-ink">Taxonomy</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard label="Canonical skills" value={data.taxonomy.total_skills} />
              <StatCard label="Canonical job titles" value={data.taxonomy.total_job_titles} />
              <StatCard
                label="Skills added"
                value={`+${data.taxonomy.skills_added_7d}`}
                sub={`last 7 days (+${data.taxonomy.skills_added_30d} in 30)`}
              />
              <StatCard
                label="Titles added"
                value={`+${data.taxonomy.job_titles_added_7d}`}
                sub={`last 7 days (+${data.taxonomy.job_titles_added_30d} in 30)`}
              />
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-ink">Review queue health</h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {(
                [
                  ['skill', 'Skills'],
                  ['job_title', 'Job titles'],
                  ['boilerplate_line', 'Boilerplate lines'],
                ] as const
              ).map(([key, label]) => {
                const entry = data.queue_health[key]
                return (
                  <div key={key} className="rounded-xl border border-line bg-surface p-4">
                    <div className="text-xs font-medium uppercase tracking-wide text-ink-soft">{label}</div>
                    <div className="mt-1 text-2xl font-semibold text-ink">{entry.pending_count}</div>
                    <div className={`mt-0.5 text-xs ${ageColor(entry.oldest_pending_days)}`}>
                      {entry.pending_count === 0
                        ? 'queue clear'
                        : `oldest pending: ${entry.oldest_pending_days}d`}
                    </div>
                  </div>
                )
              })}
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-ink">Triage activity (last 14 days)</h2>
            <div className="rounded-xl border border-line bg-surface p-4">
              {data.triage_activity.length === 0 ? (
                <div className="py-6 text-center text-xs text-ink-soft">No review activity in this window.</div>
              ) : (
                <BarChart
                  data={data.triage_activity.map((d) => ({
                    label: fmtDate(d.date),
                    value: d.approved_automated + d.approved_human + d.rejected_automated + d.rejected_human,
                  }))}
                  barColor="#4f46e5"
                />
              )}
              <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-soft">
                <span>
                  Automated approved:{' '}
                  <span className="font-medium text-ink">
                    {data.triage_activity.reduce((s, d) => s + d.approved_automated, 0)}
                  </span>
                </span>
                <span>
                  Human approved:{' '}
                  <span className="font-medium text-ink">
                    {data.triage_activity.reduce((s, d) => s + d.approved_human, 0)}
                  </span>
                </span>
                <span>
                  Automated rejected:{' '}
                  <span className="font-medium text-ink">
                    {data.triage_activity.reduce((s, d) => s + d.rejected_automated, 0)}
                  </span>
                </span>
                <span>
                  Human rejected:{' '}
                  <span className="font-medium text-ink">
                    {data.triage_activity.reduce((s, d) => s + d.rejected_human, 0)}
                  </span>
                </span>
              </div>
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-ink">LLM cost (last 30 days)</h2>
            <div className="rounded-xl border border-line bg-surface p-4">
              {!data.llm_cost.available ? (
                <div className="py-6 text-center text-xs text-ink-soft">Cost data unavailable right now.</div>
              ) : (
                <>
                  <BarChart
                    data={data.llm_cost.days.map((d) => ({ label: fmtDate(d.date), value: d.cost }))}
                    barColor="#059669"
                    formatValue={fmtMoney}
                  />
                  <div className="mt-3 text-xs text-ink-soft">
                    Total this window:{' '}
                    <span className="font-medium text-ink">{fmtMoney(data.llm_cost.total_cost ?? 0)}</span>
                  </div>
                </>
              )}
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-ink">Parsing quality (last 7 days)</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard label="Drafts parsed" value={data.parsing_quality.total_drafts} />
              <StatCard
                label="Avg confidence"
                value={
                  data.parsing_quality.avg_confidence === null
                    ? '—'
                    : `${Math.round(data.parsing_quality.avg_confidence * 100)}%`
                }
              />
              <StatCard
                label="Needs review"
                value={
                  data.parsing_quality.needs_review_pct === null
                    ? '—'
                    : `${data.parsing_quality.needs_review_pct}%`
                }
              />
              <StatCard
                label="Draft types"
                value={Object.keys(data.parsing_quality.by_type).length}
                sub={Object.entries(data.parsing_quality.by_type)
                  .map(([k, v]) => `${k.replace('draft_', '')}: ${v}`)
                  .join(', ')}
              />
            </div>
          </section>

          <p className="text-right text-xs text-ink-soft">
            Updated {new Date(data.generated_at).toLocaleTimeString()}
          </p>
        </div>
      )}
    </div>
  )
}
