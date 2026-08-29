function tone(confidence: number): { bar: string; text: string } {
  if (confidence >= 0.9) return { bar: 'bg-pass', text: 'text-pass' }
  if (confidence >= 0.7) return { bar: 'bg-accent', text: 'text-accent' }
  if (confidence >= 0.4) return { bar: 'bg-warn', text: 'text-warn' }
  return { bar: 'bg-fail', text: 'text-fail' }
}

export function ConfidenceMeter({ value, compact = false }: { value: number; compact?: boolean }) {
  const pct = Math.round(value * 100)
  const { bar, text } = tone(value)

  if (compact) {
    return (
      <span className={`mono text-xs font-medium tabular-nums ${text}`}>{pct}%</span>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`mono text-xs font-medium tabular-nums ${text}`}>{pct}%</span>
    </div>
  )
}
