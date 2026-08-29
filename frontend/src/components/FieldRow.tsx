import type { FieldProvenanceEntry } from '../types'
import { ProvenanceChip } from './ProvenanceChip'

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
  return String(value)
}

export function FieldRow({
  label,
  value,
  provenance,
}: {
  label: string
  value: unknown
  provenance?: FieldProvenanceEntry
}) {
  const isEmpty = value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)

  return (
    <div className="flex items-start justify-between gap-4 border-b border-line py-2.5 last:border-0">
      <span className="w-40 shrink-0 text-sm text-ink-soft">{label}</span>
      <span className={`flex-1 text-sm ${isEmpty ? 'text-ink-soft italic' : 'text-ink'}`}>{formatValue(value)}</span>
      <ProvenanceChip entry={provenance} />
    </div>
  )
}
