import type { FieldProvenanceEntry } from '../types'

const METHOD_STYLES: Record<string, string> = {
  deterministic: 'bg-accent-soft text-accent',
  llm_fallback: 'bg-warn-soft text-warn',
  recruiter_correction: 'bg-pass-soft text-pass',
}

const METHOD_LABELS: Record<string, string> = {
  deterministic: 'Parsed',
  llm_fallback: 'AI-assisted',
  recruiter_correction: 'Confirmed by recruiter',
}

export function ProvenanceChip({ entry }: { entry: FieldProvenanceEntry | undefined }) {
  if (!entry) return null

  const pct = Math.round(entry.confidence * 100)

  return (
    <span
      title={`${entry.extractor} · ${pct}% confidence`}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
        METHOD_STYLES[entry.extraction_method] ?? 'bg-blocked-soft text-blocked'
      }`}
    >
      {METHOD_LABELS[entry.extraction_method] ?? entry.extraction_method}
      <span className="mono opacity-70">{pct}%</span>
    </span>
  )
}
