export type DraftObjectType =
  | 'draft_consultant_profile'
  | 'draft_job_requirement'
  | 'draft_recruiter_profile'
  | 'draft_bench_sales_profile'
  | 'draft_hotlist'
  | 'draft_vendor_list'
  | 'draft_channel_note'

export type DraftStatus = 'draft' | 'needs_review' | 'published' | 'rejected'

export interface DraftObject {
  draft_id: string
  draft_type: DraftObjectType
  status: DraftStatus
  source: string
  source_ref: string | null
  channel: string | null
  source_message_id: string | null
  title: string | null
  summary: string | null
  payload: Record<string, unknown>
  normalized_skills: string[]
  normalized_job_titles: string[]
  taxonomy_signals: Record<string, unknown>
  confidence: number
  requires_review: boolean
  errors: string[]
  metadata: DraftMetadata
  created_at: string | null
  updated_at: string | null
}

export interface DraftMetadata {
  duplicate_key?: string
  content_type?: string
  sender?: { sender_id?: string | null; sender_name?: string | null; email?: string | null }
  original_sender_candidate?: {
    email: string | null
    name: string | null
    extraction_method: string | null
    confidence: number | null
  } | null
  exact_content_duplicate_of?: string | null
  duplicate_group_id?: string
  claimed_fields?: Record<string, unknown>
  claim_id?: string
  rejection_reason?: string
  core_push?: {
    status: 'pushed' | 'skipped' | 'failed'
    core_job_id?: string
    core_job_url?: string
    reason?: string
    unmatched_fields?: unknown
  }
  [key: string]: unknown
}

export interface JobRequirementRecord {
  record_type: 'job_requirement'
  job_title: string | null
  job_description: string | null
  required_skills: string[]
  preferred_skills: string[]
  years_of_experience: number | null
  location: string | null
  work_authorization: string | null
  employment_type: string | null
  rate_or_salary: string | null
  parse_confidence: number
  requires_review: boolean
  warnings: string[]
}

export interface HotlistConsultantRecord {
  record_type: 'consultant_hotlist'
  candidate_name: string | null
  candidate_email: string | null
  candidate_phone: string | null
  primary_job_title: string | null
  primary_skills: string[]
  years_of_experience: number | null
  current_location: string | null
  work_authorization: string | null
  availability: string | null
  expected_rate: string | null
  parse_confidence: number
  requires_review: boolean
  warnings: string[]
}

export interface EmailParsingResult {
  parser: { name: string; version: string; uses_llm: boolean }
  document_kind: string
  records: (JobRequirementRecord | HotlistConsultantRecord)[]
  record_count: number
  confidence: number
  requires_review: boolean
  warnings: string[]
  llm_fallback?: { used: boolean; prompt_id: string | null; reason?: string | null }
  llm_filled_fields?: string[]
}

export interface SignatureField {
  raw: string
  value: string
  confidence: number
  method: string
  source: string
}

export interface SignatureResult {
  detected: boolean
  contact: Record<string, SignatureField>
  parser?: { name: string; version: string; uses_llm: boolean }
}

export interface FieldProvenanceEntry {
  field_path: string
  raw_value: unknown
  normalized_value: unknown
  source_region: string | null
  extractor: string
  extraction_method: 'deterministic' | 'llm_fallback' | 'recruiter_correction'
  confidence: number
  value_kind: 'EXTRACTED' | 'EXTRACTED_NORMALIZED' | 'DERIVED' | 'UNKNOWN' | 'LLM_EXTRACTED'
  recorded_at: string
}

export type ClaimStatus = 'PENDING_CLAIM' | 'CLAIMED' | 'PUBLISHED' | 'EXPIRED'

export interface EmailClaim {
  claim_id: string
  draft_id: string
  token: string
  status: ClaimStatus
  recruiter_email: string
  recruiter_name: string | null
  resolution_method: string
  resolution_confidence: number
  prefilled_fields: Record<string, unknown>
  correction_diff: Record<string, { before: unknown; after: unknown }> | null
  created_at: string
  sent_at: string | null
  claimed_at: string | null
  published_at: string | null
  expires_at: string
}

export interface DraftPublishResult {
  status: string
  draft_id: string
  draft_type: DraftObjectType
  published_payload: Record<string, unknown>
  errors: string[]
}
