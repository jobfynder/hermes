import { useState } from 'react'
import type { FieldProvenanceEntry } from '../types'
import { ProvenanceChip } from './ProvenanceChip'

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
  return String(value)
}

function toEditText(value: unknown, isArray: boolean): string {
  if (value === null || value === undefined) return ''
  if (isArray && Array.isArray(value)) return value.join(', ')
  return String(value)
}

function fromEditText(text: string, isArray: boolean, isNumeric: boolean): unknown {
  const trimmed = text.trim()

  if (isArray) {
    return trimmed
      ? trimmed.split(',').map((s) => s.trim()).filter(Boolean)
      : []
  }

  if (isNumeric) {
    if (!trimmed) return null
    const n = Number(trimmed)
    return Number.isFinite(n) ? n : trimmed
  }

  return trimmed || null
}

export function FieldRow({
  label,
  value,
  provenance,
  editable,
  isArray,
  isNumeric,
  onSave,
}: {
  label: string
  value: unknown
  provenance?: FieldProvenanceEntry
  editable?: boolean
  isArray?: boolean
  isNumeric?: boolean
  onSave?: (newValue: unknown) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)

  const isEmpty = value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)

  function startEdit() {
    setDraft(toEditText(value, Boolean(isArray)))
    setEditing(true)
  }

  async function handleSave() {
    if (!onSave) return
    setSaving(true)
    try {
      await onSave(fromEditText(draft, Boolean(isArray), Boolean(isNumeric)))
      setEditing(false)
    } catch {
      // The caller already surfaces the failure (e.g. an actionMessage
      // banner) -- keep the row in edit mode with the attempted value so
      // the reviewer can retry without retyping.
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <div className="flex items-start justify-between gap-4 border-b border-line py-2.5 last:border-0">
        <span className="w-40 shrink-0 pt-1.5 text-sm text-ink-soft">{label}</span>
        <div className="flex-1">
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave()
              if (e.key === 'Escape') setEditing(false)
            }}
            placeholder={isArray ? 'Comma-separated' : undefined}
            className="w-full rounded-lg border border-accent bg-paper px-2.5 py-1 text-sm text-ink outline-none"
          />
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
      </div>
    )
  }

  return (
    <div className="group flex items-start justify-between gap-4 border-b border-line py-2.5 last:border-0">
      <span className="w-40 shrink-0 text-sm text-ink-soft">{label}</span>
      <span className={`flex-1 text-sm ${isEmpty ? 'text-ink-soft italic' : 'text-ink'}`}>{formatValue(value)}</span>
      <div className="flex items-center gap-2">
        <ProvenanceChip entry={provenance} />
        {editable && onSave && (
          <button
            onClick={startEdit}
            title={`Edit ${label}`}
            className="rounded-md px-1.5 py-0.5 text-xs text-ink-soft opacity-0 transition hover:bg-paper hover:text-ink group-hover:opacity-100"
          >
            Edit
          </button>
        )}
      </div>
    </div>
  )
}
