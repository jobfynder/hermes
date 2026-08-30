import type { DraftObject, DraftObjectType } from '../types'

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

function parsedRecords(draft: DraftObject): Record<string, unknown>[] {
  const structuredData = draft.payload?.structured_data as Record<string, unknown> | undefined
  const emailParsing = structuredData?.email_parsing as Record<string, unknown> | undefined
  const records = emailParsing?.records

  return Array.isArray(records) ? (records as Record<string, unknown>[]) : []
}

/** The list/detail pages' actual title -- read live from the parsed
 * record rather than the stored `title` column. The stored column is a
 * one-time snapshot taken at intake (or a reclassify); if a reviewer
 * later edits the job_title/candidate_name field, that column doesn't
 * follow along, so reading straight from the parsed data is both more
 * accurate and self-heals any draft whose stored title predates this
 * fix (every draft created before it still says the generic "Draft Job
 * Requirement"/"Draft Hotlist").
 */
export function draftDisplayTitle(draft: DraftObject): string {
  const records = parsedRecords(draft)

  if (draft.draft_type === 'draft_job_requirement') {
    const jobTitle = records[0]?.job_title
    if (typeof jobTitle === 'string' && jobTitle.trim()) return jobTitle
  }

  if (draft.draft_type === 'draft_hotlist') {
    if (records.length === 1) {
      const candidateName = records[0]?.candidate_name
      if (typeof candidateName === 'string' && candidateName.trim()) return candidateName
    } else if (records.length > 1) {
      return `Hotlist — ${records.length} consultants`
    }
  }

  return draft.title || '(untitled)'
}
