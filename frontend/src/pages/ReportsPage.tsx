import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DashboardOverview, FieldAccuracyEntry, RankedCount, SenderIntelligenceEntry } from '../types'

type Tab = 'overview' | 'ingestion' | 'parser_quality' | 'ai_cost' | 'recruitment' | 'sender' | 'exceptions'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'ingestion', label: 'Ingestion' },
  { id: 'parser_quality', label: 'Parser Quality' },
  { id: 'ai_cost', label: 'AI Usage & Cost' },
  { id: 'recruitment', label: 'Recruitment Intelligence' },
  { id: 'sender', label: 'Sender Intelligence' },
  { id: 'exceptions', label: 'Exceptions' },
]

function StatCard({ label, value, sub, tone }: { label: string; value: string | number; sub?: string; tone?: 'warn' | 'fail' | 'pass' }) {
  const toneClass = tone === 'fail' ? 'text-fail' : tone === 'warn' ? 'text-warn' : tone === 'pass' ? 'text-pass' : 'text-ink'
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-ink-soft">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-soft">{sub}</div>}
    </div>
  )
}

function ageColor(days: number): string {
  if (days >= 3) return 'text-fail'
  if (days >= 1) return 'text-warn'
  return 'text-ink-soft'
}

function pctTone(pct: number | null, goodAbove = 90, warnAbove = 70): 'pass' | 'warn' | 'fail' | undefined {
  if (pct === null) return undefined
  if (pct >= goodAbove) return 'pass'
  if (pct >= warnAbove) return 'warn'
  return 'fail'
}

function BarChart({
  data,
  height = 80,
  barColor = '#4f46e5',
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

  return (
    <div className="flex items-end gap-px" style={{ height }}>
      {data.map((d, i) => (
        <div key={i} className="group relative flex-1" style={{ height: '100%' }} title={`${d.label}: ${formatValue ? formatValue(d.value) : d.value}`}>
          <div className="flex h-full items-end">
            <div
              className="w-full rounded-t transition group-hover:opacity-80"
              style={{ height: `${Math.max(2, (d.value / max) * 100)}%`, backgroundColor: barColor }}
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

function pct(v: number | null): string {
  return v === null ? '—' : `${v}%`
}

function FieldAccuracyTable({ fields, title, note }: { fields: FieldAccuracyEntry[]; title: string; note?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <h3 className="mb-1 text-sm font-semibold text-ink">{title}</h3>
      {note && <p className="mb-3 text-xs text-ink-soft">{note}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
              <th className="px-2 py-2 font-medium">Field</th>
              <th className="px-2 py-2 font-medium">Fill rate</th>
              <th className="px-2 py-2 font-medium">Precision</th>
              <th className="px-2 py-2 font-medium">False-positive rate</th>
              <th className="px-2 py-2 font-medium">Avg stated confidence</th>
              <th className="px-2 py-2 font-medium">Calibration gap</th>
              <th className="px-2 py-2 font-medium">Corrections</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => (
              <tr key={f.field} className={`border-b border-line last:border-0 ${f.needs_spot_check ? 'bg-fail-soft' : ''}`}>
                <td className="px-2 py-2 font-medium text-ink">
                  {f.field.replace(/_/g, ' ')}
                  {f.needs_spot_check && (
                    <span className="ml-1.5 rounded-full bg-fail px-1.5 py-0.5 text-[10px] font-semibold text-white" title="High volume, low confidence, zero corrections recorded — worth a manual spot-check">
                      spot-check
                    </span>
                  )}
                </td>
                <td className="px-2 py-2 text-ink-soft">{pct(f.fill_rate)}</td>
                <td className="px-2 py-2">
                  <span className={pctTone(f.precision, 95, 85) === 'fail' ? 'font-semibold text-fail' : pctTone(f.precision, 95, 85) === 'warn' ? 'font-semibold text-warn' : 'text-ink'}>
                    {pct(f.precision)}
                  </span>
                  {!f.reliable && <span className="ml-1 text-[10px] text-ink-soft">(low sample)</span>}
                </td>
                <td className="px-2 py-2 text-ink-soft">{pct(f.false_positive_rate)}</td>
                <td className="px-2 py-2 text-ink-soft">{pct(f.avg_stated_confidence)}</td>
                <td className="px-2 py-2 text-ink-soft">
                  {f.calibration_gap === null ? '—' : f.calibration_gap > 5 ? (
                    <span className="text-fail">+{f.calibration_gap} (overconfident)</span>
                  ) : f.calibration_gap < -5 ? (
                    <span className="text-ink-soft">{f.calibration_gap} (underconfident)</span>
                  ) : (
                    `${f.calibration_gap}`
                  )}
                </td>
                <td className="px-2 py-2 whitespace-nowrap text-ink-soft">
                  {f.corrected_wrong_count > 0 && <span>{f.corrected_wrong_count} fixed</span>}
                  {f.corrected_wrong_count > 0 && f.corrected_missing_count > 0 && ', '}
                  {f.corrected_missing_count > 0 && <span>{f.corrected_missing_count} filled in</span>}
                  {f.corrected_wrong_count === 0 && f.corrected_missing_count === 0 && '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RankedList({
  title,
  items,
  emptyLabel = 'No data in this window.',
}: {
  title: string
  items: { label: string; count: number }[]
  emptyLabel?: string
}) {
  const max = Math.max(...items.map((i) => i.count), 1)
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <h3 className="mb-3 text-sm font-semibold text-ink">{title}</h3>
      {items.length === 0 ? (
        <div className="py-4 text-center text-xs text-ink-soft">{emptyLabel}</div>
      ) : (
        <ul className="space-y-2">
          {items.map((item, i) => (
            <li key={item.label + i} className="flex items-center gap-3">
              <span className="w-5 shrink-0 text-right text-xs tabular-nums text-ink-soft">{i + 1}</span>
              <span className="w-40 shrink-0 truncate text-sm text-ink" title={item.label}>{item.label}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-line/60">
                <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(4, (item.count / max) * 100)}%` }} />
              </div>
              <span className="w-14 shrink-0 text-right text-xs font-medium tabular-nums text-ink">{item.count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function rankedCountsToItems(counts: RankedCount[]): { label: string; count: number }[] {
  return counts.map((c) => ({ label: c.value, count: c.count }))
}

function SenderTable({ title, entries, idKey }: { title: string; entries: SenderIntelligenceEntry[]; idKey: 'sender_email' | 'domain' }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <h3 className="mb-3 text-sm font-semibold text-ink">{title}</h3>
      {entries.length === 0 ? (
        <div className="py-4 text-center text-xs text-ink-soft">No senders in this window.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
                <th className="px-2 py-2 font-medium">{idKey === 'domain' ? 'Domain' : 'Sender'}</th>
                <th className="px-2 py-2 font-medium">Total</th>
                <th className="px-2 py-2 font-medium">Jobs</th>
                <th className="px-2 py-2 font-medium">Hotlists</th>
                <th className="px-2 py-2 font-medium">Avg confidence</th>
                <th className="px-2 py-2 font-medium">Duplicates</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => (
                <tr key={(e[idKey] ?? '') + i} className="border-b border-line last:border-0">
                  <td className="px-2 py-2 font-medium text-ink">{e[idKey]}</td>
                  <td className="px-2 py-2 text-ink-soft">{e.total_drafts}</td>
                  <td className="px-2 py-2 text-ink-soft">{e.jobs}</td>
                  <td className="px-2 py-2 text-ink-soft">{e.hotlists}</td>
                  <td className="px-2 py-2 text-ink-soft">{e.avg_confidence === null ? '—' : pct(Math.round(e.avg_confidence * 100))}</td>
                  <td className="px-2 py-2 text-ink-soft">
                    {e.duplicate_count === 0 ? '—' : `${e.duplicate_count} (${pct(e.duplicate_pct)})`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function ComingSoon({ title }: { title: string }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface p-8 text-center">
      <p className="text-sm font-medium text-ink">{title} isn't built yet</p>
      <p className="mt-1 text-xs text-ink-soft">
        This was flagged as a P1 report — let me know if you want it built next.
      </p>
    </div>
  )
}

export function ReportsPage({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<DashboardOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<Tab>('overview')

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
      <header className="mb-4 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Reports</h1>
          <p className="mt-1 text-sm text-ink-soft">Hermes Email Intelligence dashboard.</p>
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

      <div className="mb-6 flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-t-lg px-3 py-2 text-xs font-medium transition ${
              tab === t.id ? 'border-b-2 border-accent text-accent' : 'text-ink-soft hover:text-ink'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}
      {!data && !error && <div className="py-10 text-center text-sm text-ink-soft">Loading…</div>}

      {data && (
        <div className="space-y-8">
          {tab === 'overview' && (
            <>
              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">Today</h2>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <StatCard label="Emails" value={data.today.emails_received} />
                  <StatCard label="Jobs" value={data.today.jobs} />
                  <StatCard label="Hotlists" value={data.today.hotlists} />
                  <StatCard label="Other / unknown" value={data.today.other} />
                  <StatCard label="Processed" value={pct(data.today.processing_rate_pct)} tone={pctTone(data.today.processing_rate_pct)} />
                  <StatCard label="Needs review" value={pct(data.today.needs_review_pct)} tone={pctTone(100 - (data.today.needs_review_pct ?? 0))} />
                  <StatCard label="Avg confidence" value={data.today.avg_confidence === null ? '—' : pct(Math.round(data.today.avg_confidence * 100))} tone={pctTone(data.today.avg_confidence === null ? null : data.today.avg_confidence * 100)} />
                  <StatCard label="Parser-only" value={pct(data.today.parser_only_pct)} sub={`AI-assisted: ${pct(data.today.ai_assisted_pct)}`} />
                </div>
              </section>

              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">Taxonomy</h2>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <StatCard label="Canonical skills" value={data.taxonomy.total_skills} />
                  <StatCard label="Canonical job titles" value={data.taxonomy.total_job_titles} />
                  <StatCard label="Skills added" value={`+${data.taxonomy.skills_added_7d}`} sub={`last 7 days (+${data.taxonomy.skills_added_30d} in 30)`} />
                  <StatCard label="Titles added" value={`+${data.taxonomy.job_titles_added_7d}`} sub={`last 7 days (+${data.taxonomy.job_titles_added_30d} in 30)`} />
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
                          {entry.pending_count === 0 ? 'queue clear' : `oldest pending: ${entry.oldest_pending_days}d`}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>

              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">Triage activity (last 14 days)</h2>
                <div className="rounded-xl border border-line bg-surface p-4">
                  <BarChart
                    data={data.triage_activity.map((d) => ({
                      label: fmtDate(d.date),
                      value: d.approved_automated + d.approved_human + d.rejected_automated + d.rejected_human,
                    }))}
                  />
                  <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-soft">
                    <span>Automated approved: <span className="font-medium text-ink">{data.triage_activity.reduce((s, d) => s + d.approved_automated, 0)}</span></span>
                    <span>Human approved: <span className="font-medium text-ink">{data.triage_activity.reduce((s, d) => s + d.approved_human, 0)}</span></span>
                    <span>Automated rejected: <span className="font-medium text-ink">{data.triage_activity.reduce((s, d) => s + d.rejected_automated, 0)}</span></span>
                    <span>Human rejected: <span className="font-medium text-ink">{data.triage_activity.reduce((s, d) => s + d.rejected_human, 0)}</span></span>
                  </div>
                </div>
              </section>

              <p className="text-right text-xs text-ink-soft">Updated {new Date(data.generated_at).toLocaleTimeString()}</p>
            </>
          )}

          {tab === 'ingestion' && (
            <>
              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">Ingestion health (last {data.ingestion_health.days} days)</h2>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <StatCard label="Received" value={data.ingestion_health.received} />
                  <StatCard label="Parsed" value={data.ingestion_health.parsed} />
                  <StatCard label="Duplicates" value={data.ingestion_health.duplicate} />
                  <StatCard label="Unaccounted" value={data.ingestion_health.unaccounted} tone={data.ingestion_health.unaccounted > 0 ? 'warn' : 'pass'} sub="received minus parsed minus duplicate" />
                  <StatCard label="Processing rate" value={pct(data.ingestion_health.processing_rate_pct)} tone={pctTone(data.ingestion_health.processing_rate_pct)} />
                  <StatCard label="Received / hour" value={data.ingestion_health.received_per_hour} />
                </div>
              </section>
              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">By channel</h2>
                <div className="rounded-xl border border-line bg-surface p-4">
                  {Object.entries(data.ingestion_health.by_channel).map(([channel, count]) => (
                    <div key={channel} className="flex items-center justify-between border-b border-line py-2 text-sm last:border-0">
                      <span className="text-ink">{channel}</span>
                      <span className="font-medium text-ink">{count}</span>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}

          {tab === 'parser_quality' && (
            <>
              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">Classification (last {data.classification.days} days)</h2>
                <div className="rounded-xl border border-line bg-surface p-4">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
                        <th className="px-2 py-2 font-medium">Draft type</th>
                        <th className="px-2 py-2 font-medium">Count</th>
                        <th className="px-2 py-2 font-medium">% of total</th>
                        <th className="px-2 py-2 font-medium">Avg confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.classification.by_type.map((t) => (
                        <tr key={t.draft_type} className="border-b border-line last:border-0">
                          <td className="px-2 py-2 font-medium text-ink">{t.draft_type.replace('draft_', '').replace(/_/g, ' ')}</td>
                          <td className="px-2 py-2 text-ink-soft">{t.count}</td>
                          <td className="px-2 py-2 text-ink-soft">{pct(t.pct_of_total)}</td>
                          <td className="px-2 py-2 text-ink-soft">{t.avg_confidence === null ? '—' : pct(Math.round(t.avg_confidence * 100))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">Review queue reasons (last {data.review_queue.days} days)</h2>
                <div className="rounded-xl border border-line bg-surface p-4">
                  <div className="mb-3 flex flex-wrap gap-3 text-xs text-ink-soft">
                    {Object.entries(data.review_queue.by_status).map(([status, count]) => (
                      <span key={status}>
                        {status.replace('_', ' ')}: <span className="font-medium text-ink">{count}</span>
                      </span>
                    ))}
                  </div>
                  {data.review_queue.review_reasons.length === 0 ? (
                    <div className="py-4 text-center text-xs text-ink-soft">No review reasons recorded in this window.</div>
                  ) : (
                    <table className="w-full text-left text-sm">
                      <thead>
                        <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
                          <th className="px-2 py-2 font-medium">Reason</th>
                          <th className="px-2 py-2 font-medium">Count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.review_queue.review_reasons.map((r) => (
                          <tr key={r.reason} className="border-b border-line last:border-0">
                            <td className="px-2 py-2 text-ink">{r.reason.replace(/_/g, ' ')}</td>
                            <td className="px-2 py-2 text-ink-soft">{r.count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </section>

              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">Signature parser quality (last {data.signature_quality.days} days)</h2>
                <FieldAccuracyTable
                  fields={data.signature_quality.fields}
                  title="Sender name, company, contact fields"
                  note="Precision comes from real reviewer corrections, not stated confidence. A field with zero corrections and low confidence is flagged for a manual spot-check — zero corrections can mean genuinely accurate, or simply unreviewed."
                />
              </section>
            </>
          )}

          {tab === 'ai_cost' && (
            <>
              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">AI dependency (last {data.ai_dependency.days} days)</h2>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <StatCard label="Parser-only" value={pct(data.ai_dependency.parser_only_pct)} sub={`${data.ai_dependency.parser_only_count} drafts`} tone="pass" />
                  <StatCard label="AI-assisted" value={pct(data.ai_dependency.ai_assisted_pct)} sub={`${data.ai_dependency.ai_assisted_count} drafts`} />
                  <StatCard label="LLM cost (window)" value={data.ai_dependency.llm_cost.available ? fmtMoney(data.ai_dependency.llm_cost.total_cost ?? 0) : '—'} />
                  <StatCard label="Cost / 1,000 drafts" value={data.ai_dependency.cost_per_1000_drafts === null ? '—' : fmtMoney(data.ai_dependency.cost_per_1000_drafts)} />
                </div>
              </section>

              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">LLM cost trend (last 30 days)</h2>
                <div className="rounded-xl border border-line bg-surface p-4">
                  {!data.llm_cost.available ? (
                    <div className="py-6 text-center text-xs text-ink-soft">Cost data unavailable right now.</div>
                  ) : (
                    <>
                      <BarChart data={data.llm_cost.days.map((d) => ({ label: fmtDate(d.date), value: d.cost }))} barColor="#059669" formatValue={fmtMoney} />
                      <div className="mt-3 text-xs text-ink-soft">
                        Total this window: <span className="font-medium text-ink">{fmtMoney(data.llm_cost.total_cost ?? 0)}</span>
                      </div>
                    </>
                  )}
                </div>
              </section>
            </>
          )}

          {tab === 'recruitment' && (
            <>
              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">Recruitment intelligence (last {data.recruitment_intelligence.days} days, top skills all-time)</h2>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <StatCard label="Job records" value={data.recruitment_intelligence.total_job_records} />
                  <StatCard label="Rate/salary specified" value={pct(data.recruitment_intelligence.rate_specified_pct)} sub={`${data.recruitment_intelligence.rate_specified_count} of ${data.recruitment_intelligence.total_job_records}`} />
                  <StatCard label="Top skills tracked" value={data.recruitment_intelligence.top_skills.length} sub="excludes taxonomy noise" />
                  <StatCard label="Top job titles" value={data.recruitment_intelligence.top_job_titles.length} />
                </div>
              </section>

              <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <RankedList
                  title="Top skills requested (all-time)"
                  items={data.recruitment_intelligence.top_skills.map((s) => ({ label: s.skill, count: s.times_seen }))}
                />
                <RankedList
                  title="Top job titles"
                  items={data.recruitment_intelligence.top_job_titles.map((t) => ({ label: t.title, count: t.count }))}
                />
              </section>

              <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <RankedList title="Top locations" items={rankedCountsToItems(data.recruitment_intelligence.top_locations)} />
                <RankedList title="Employment types" items={rankedCountsToItems(data.recruitment_intelligence.top_employment_types)} />
                <RankedList title="Work authorization" items={rankedCountsToItems(data.recruitment_intelligence.top_work_authorizations)} />
              </section>
            </>
          )}

          {tab === 'sender' && (
            <>
              <section>
                <h2 className="mb-3 text-sm font-semibold text-ink">Sender intelligence (last {data.sender_intelligence.days} days)</h2>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <StatCard label="Distinct senders" value={data.sender_intelligence.total_senders} />
                  <StatCard label="Distinct domains" value={data.sender_intelligence.total_domains} />
                </div>
              </section>
              <section>
                <SenderTable title="Top senders" entries={data.sender_intelligence.top_senders} idKey="sender_email" />
              </section>
              <section>
                <SenderTable title="Top domains" entries={data.sender_intelligence.top_domains} idKey="domain" />
              </section>
            </>
          )}

          {tab === 'exceptions' && <ComingSoon title="Data Quality Exceptions" />}
        </div>
      )}
    </div>
  )
}
