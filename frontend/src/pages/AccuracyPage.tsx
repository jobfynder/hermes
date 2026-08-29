import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AccuracySummary, FieldAccuracyStat } from '../types'

const RANGES = [7, 30, 90]

function pctColor(pct: number | null, reliable: boolean): string {
  if (pct === null || !reliable) return 'text-ink-soft'
  if (pct >= 90) return 'text-pass'
  if (pct >= 70) return 'text-warn'
  return 'text-fail'
}

function pctBar(pct: number | null): string {
  if (pct === null) return 'bg-line'
  if (pct >= 90) return 'bg-pass'
  if (pct >= 70) return 'bg-warn'
  return 'bg-fail'
}

function FieldTable({ rows }: { rows: FieldAccuracyStat[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
            <th className="px-3 py-2 font-medium">Field</th>
            <th className="px-3 py-2 font-medium">Fill rate</th>
            <th className="px-3 py-2 font-medium">Precision</th>
            <th className="px-3 py-2 font-medium">Corrections</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.field} className="border-b border-line last:border-0">
              <td className="px-3 py-2.5 font-medium text-ink">{row.field.replace(/_/g, ' ')}</td>
              <td className="px-3 py-2.5 text-ink-soft">
                {row.fill_rate === null ? (
                  '—'
                ) : (
                  <span className="whitespace-nowrap">
                    {row.fill_rate}% <span className="text-xs">({row.filled_count}/{row.total_drafts})</span>
                  </span>
                )}
              </td>
              <td className="px-3 py-2.5">
                {row.precision === null ? (
                  <span className="text-ink-soft">no data yet</span>
                ) : (
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
                      <div
                        className={`h-full ${pctBar(row.precision)}`}
                        style={{ width: `${row.precision}%` }}
                      />
                    </div>
                    <span className={`font-semibold ${pctColor(row.precision, row.reliable)}`}>
                      {row.precision}%
                    </span>
                    {!row.reliable && (
                      <span className="text-xs text-ink-soft" title="Fewer than 10 samples — not statistically reliable yet">
                        (low sample)
                      </span>
                    )}
                  </div>
                )}
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap text-ink-soft">
                {row.corrected_wrong_count > 0 && <span>{row.corrected_wrong_count} fixed</span>}
                {row.corrected_wrong_count > 0 && row.corrected_missing_count > 0 && ', '}
                {row.corrected_missing_count > 0 && <span>{row.corrected_missing_count} filled in</span>}
                {row.corrected_wrong_count === 0 && row.corrected_missing_count === 0 && '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function AccuracyPage({ onBack }: { onBack: () => void }) {
  const [summary, setSummary] = useState<AccuracySummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(30)

  function load(range: number) {
    setError(null)
    api.getAccuracySummary(range).then(setSummary).catch((err) => setError(err.message))
  }

  useEffect(() => load(days), [days])

  const worstJob = summary?.job_requirement_fields.find((f) => f.reliable && f.precision !== null && f.precision < 80)
  const worstHotlist = summary?.hotlist_fields.find((f) => f.reliable && f.precision !== null && f.precision < 80)

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Parsing accuracy</h1>
          <p className="mt-1 text-sm text-ink-soft">
            Computed from real corrections — reviewer edits and recruiter claim corrections — not a hand-graded test set.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 rounded-lg border border-line bg-surface p-1">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setDays(r)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  days === r ? 'bg-accent text-white' : 'text-ink-soft hover:text-ink'
                }`}
              >
                {r}d
              </button>
            ))}
          </div>
          <button
            onClick={onBack}
            className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-soft transition hover:text-ink"
          >
            Back to drafts
          </button>
        </div>
      </header>

      {error && <div className="mb-4 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}

      {(worstJob || worstHotlist) && (
        <div className="mb-6 rounded-lg bg-warn-soft px-4 py-3 text-sm text-warn">
          {worstJob && (
            <div>
              Worst job-requirement field: <strong>{worstJob.field.replace(/_/g, ' ')}</strong> at{' '}
              {worstJob.precision}% precision.
            </div>
          )}
          {worstHotlist && (
            <div>
              Worst hotlist field: <strong>{worstHotlist.field.replace(/_/g, ' ')}</strong> at{' '}
              {worstHotlist.precision}% precision.
            </div>
          )}
        </div>
      )}

      <div className="space-y-8">
        <section>
          <h2 className="mb-3 text-sm font-semibold text-ink">Job requirement fields</h2>
          {summary ? (
            <FieldTable rows={summary.job_requirement_fields} />
          ) : (
            <div className="rounded-lg border border-line bg-surface px-4 py-8 text-center text-sm text-ink-soft">Loading…</div>
          )}
        </section>

        <section>
          <h2 className="mb-3 text-sm font-semibold text-ink">Hotlist fields</h2>
          {summary ? (
            <FieldTable rows={summary.hotlist_fields} />
          ) : (
            <div className="rounded-lg border border-line bg-surface px-4 py-8 text-center text-sm text-ink-soft">Loading…</div>
          )}
        </section>
      </div>

      <p className="mt-6 text-xs text-ink-soft">
        Fill rate: of everything Hermes saw, how often it produced a value for this field at all. Precision: of the
        values it produced, how often a human left it untouched. "Fixed" means a wrong value got corrected;
        "filled in" means a blank field got a value added by a reviewer or recruiter — that's a fill-rate gap, not a
        precision miss. Fields with fewer than 10 samples are marked low-sample and shouldn't be trusted yet.
      </p>
    </div>
  )
}
