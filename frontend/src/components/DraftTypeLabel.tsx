import type { DraftObjectType } from '../types'

const LABELS: Record<DraftObjectType, string> = {
  draft_job_requirement: 'Job requirement',
  draft_hotlist: 'Hotlist',
  draft_consultant_profile: 'Consultant profile',
  draft_recruiter_profile: 'Recruiter profile',
  draft_bench_sales_profile: 'Bench sales profile',
  draft_vendor_list: 'Vendor list',
  draft_channel_note: 'Channel note',
}

export function draftTypeLabel(type: DraftObjectType): string {
  return LABELS[type] ?? type
}

export function DraftTypeLabel({ type }: { type: DraftObjectType }) {
  return <span className="text-sm text-ink-soft">{draftTypeLabel(type)}</span>
}
