import type { DraftStatus } from '../types'

const STYLES: Record<DraftStatus, string> = {
  draft: 'bg-blocked-soft text-blocked',
  needs_review: 'bg-warn-soft text-warn',
  published: 'bg-pass-soft text-pass',
  rejected: 'bg-fail-soft text-fail',
  spam: 'bg-fail-soft text-fail',
}

const LABELS: Record<DraftStatus, string> = {
  draft: 'Draft',
  needs_review: 'Needs review',
  published: 'Published',
  rejected: 'Rejected',
  spam: 'Spam',
}

export function StatusBadge({ status }: { status: DraftStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${STYLES[status]}`}
    >
      {LABELS[status]}
    </span>
  )
}
