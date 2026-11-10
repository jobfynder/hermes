export type DraftObjectType =
  | 'draft_consultant_profile'
  | 'draft_job_requirement'
  | 'draft_recruiter_profile'
  | 'draft_bench_sales_profile'
  | 'draft_hotlist'
  | 'draft_vendor_list'
  | 'draft_channel_note'

export type DraftStatus = 'draft' | 'needs_review' | 'published' | 'rejected' | 'spam'

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

// What the drafts list page actually renders per row -- see
// list_draft_summaries (app/drafts/service.py). Deliberately excludes
// `payload` (raw email text, full parsed records) since the list view
// never needs it -- display_title is computed server-side from the same
// fields draftDisplayTitle() used to read out of payload client-side.
export interface DraftSummaryEntry {
  draft_id: string
  draft_type: DraftObjectType
  status: DraftStatus
  confidence: number
  created_at: string | null
  metadata: DraftMetadata
  source_message_id: string | null
  display_title: string
  is_duplicate: boolean
  channel?: string | null
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
  spam_reasons?: string[]
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
  company: string | null
  linkedin_url: string | null
  job_description: string | null
  required_skills: string[]
  preferred_skills: string[]
  years_of_experience: number | null
  location: string | null
  work_authorization: string | null
  employment_type: string | null
  rate_or_salary: string | null
  work_mode?: string | null
  duration?: string | null
  start_date?: string | null
  requisition_id?: string | null
  employment_type_basis?: string | null
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

export interface ClaimPrepareResult {
  status: 'prepared' | 'already_prepared' | 'blocked'
  claim: EmailClaim | null
  email_subject: string | null
  email_body: string | null
  claim_url_path: string | null
  errors: string[]
}

export interface DraftPublishResult {
  status: string
  draft_id: string
  draft_type: DraftObjectType
  published_payload: Record<string, unknown>
  errors: string[]
}

export interface DeleteDraftResult {
  deleted: boolean
  reason: string | null
}

export interface BlocklistEntry {
  id: number
  match_type: 'domain' | 'email'
  value: string
  reason: string | null
  source_draft_id: string | null
  created_at: string
}

export interface TaxonomyCandidateEntry {
  id: number
  signal_type: 'skill' | 'job_title' | 'boilerplate_line'
  term: string
  normalized_term: string
  occurrence_count: number
  distinct_senders: string[]
  sample_draft_ids: string[]
  status: 'pending' | 'approved' | 'rejected'
  first_seen_at: string
  last_seen_at: string
  suggestion?: "approve" | "reject" | "review" | null
  suggestion_reason?: string | null
}

export interface FieldAccuracyStat {
  field: string
  total_drafts: number
  filled_count: number
  fill_rate: number | null
  corrected_wrong_count: number
  corrected_missing_count: number
  precision: number | null
  reliable: boolean
}

export interface AccuracySummary {
  days: number
  job_requirement_fields: FieldAccuracyStat[]
  hotlist_fields: FieldAccuracyStat[]
}

export interface CanonicalSkillEntry {
  name: string
  category: string | null
  skill_type: string | null
  aliases: string[]
  related_skills: string[]
  confidence: string | null
  source: string | null
  description: string | null
  description_source: 'ai_generated' | 'human_edited' | null
  description_edited_by: string | null
  description_edited_at: string | null
  times_seen: number
  last_seen_at: string | null
  added_at: string | null
}

export interface SkillsTaxonomyPageResult {
  items: CanonicalSkillEntry[]
  total_count: number
  taxonomy_count: number
  page: number
  page_size: number
  categories: string[]
  missing_description_count: number
}

export interface JobTitleEntry {
  title: string
  family: string | null
  seniority: string | null
  aliases: string[]
  related_titles: string[]
  confidence: string | null
  source: string | null
  added_at: string | null
}

export interface FilteredReportAnalysis {
  days: number
  filters: { draft_type: string | null; status: string | null; channel: string | null }
  total: number
  needs_review_count: number
  needs_review_pct: number | null
  avg_confidence: number | null
  duplicate_count: number
  duplicate_pct: number | null
  by_status: Record<string, number>
  by_type: Record<string, number>
  by_channel: Record<string, number>
  review_reasons: { reason: string; count: number }[]
  available_channels: string[]
}

export interface QueueHealthEntry {
  pending_count: number
  oldest_pending_days: number
}

export interface TodaySummary {
  emails_received: number
  jobs: number
  hotlists: number
  other: number
  processing_rate_pct: number | null
  needs_review_pct: number | null
  parser_only_pct: number | null
  ai_assisted_pct: number | null
  avg_confidence: number | null
}

export interface IngestionHealth {
  days: number
  received: number
  parsed: number
  duplicate: number
  unaccounted: number
  processing_rate_pct: number | null
  received_per_hour: number
  by_channel: Record<string, number>
}

export interface ClassificationReport {
  days: number
  total: number
  by_type: {
    draft_type: string
    count: number
    pct_of_total: number | null
    avg_confidence: number | null
  }[]
  daily: Record<string, string | number>[]
}

export interface AiDependencyReport {
  days: number
  total_drafts: number
  parser_only_count: number
  ai_assisted_count: number
  parser_only_pct: number | null
  ai_assisted_pct: number | null
  llm_cost: {
    available: boolean
    days: { date: string; cost: number; traces: number }[]
    total_cost?: number
  }
  cost_per_1000_drafts: number | null
}

export interface ReviewQueueReport {
  days: number
  by_status: Record<string, number>
  review_reasons: { reason: string; count: number }[]
}

export interface FieldAccuracyEntry {
  field: string
  total_drafts: number
  filled_count: number
  fill_rate: number | null
  corrected_wrong_count: number
  corrected_missing_count: number
  precision: number | null
  false_positive_rate: number | null
  avg_stated_confidence: number | null
  calibration_gap: number | null
  reliable: boolean
  needs_spot_check?: boolean
}

export interface SignatureQualityReport {
  days: number
  fields: FieldAccuracyEntry[]
}

export interface RankedCount {
  value: string
  count: number
}

export interface RecruitmentIntelligence {
  days: number
  top_skills: { skill: string; times_seen: number }[]
  top_skills_all_time: boolean
  top_job_titles: { title: string; count: number }[]
  top_locations: RankedCount[]
  top_employment_types: RankedCount[]
  top_work_authorizations: RankedCount[]
  total_job_records: number
  rate_specified_count: number
  rate_specified_pct: number | null
}

export interface SenderIntelligenceEntry {
  sender_email?: string
  domain?: string
  total_drafts: number
  jobs: number
  hotlists: number
  other: number
  avg_confidence: number | null
  duplicate_count: number
  duplicate_pct: number | null
}

export interface SenderIntelligence {
  days: number
  total_senders: number
  total_domains: number
  top_senders: SenderIntelligenceEntry[]
  top_domains: SenderIntelligenceEntry[]
}

export interface DashboardOverview {
  today: TodaySummary
  taxonomy: {
    total_skills: number
    total_job_titles: number
    skills_added_7d: number
    skills_added_30d: number
    job_titles_added_7d: number
    job_titles_added_30d: number
  }
  queue_health: {
    skill: QueueHealthEntry
    job_title: QueueHealthEntry
    boilerplate_line: QueueHealthEntry
  }
  triage_activity: {
    date: string
    approved_automated: number
    approved_human: number
    rejected_automated: number
    rejected_human: number
  }[]
  llm_cost: {
    available: boolean
    days: { date: string; cost: number; traces: number }[]
    total_cost?: number
  }
  parsing_quality: {
    total_drafts: number
    avg_confidence: number | null
    needs_review_pct: number | null
    by_type: Record<string, number>
  }
  ingestion_health: IngestionHealth
  classification: ClassificationReport
  ai_dependency: AiDependencyReport
  review_queue: ReviewQueueReport
  signature_quality: SignatureQualityReport
  recruitment_intelligence: RecruitmentIntelligence
  sender_intelligence: SenderIntelligence
  generated_at: string
}

export interface AssistantQueryResult {
  answer: string
  tool_used: string | null
  data: Record<string, unknown> | null
}

export interface TodayHealthCheck {
  id: string
  label: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
}

export interface TodayOverview {
  generated_at: string
  health: TodayHealthCheck[]
  inbox: {
    drafts?: {
      needs_review?: number
      oldest_needs_review_at?: string | null
      expires_after_days?: number
      due_to_expire_now?: number
      removed_last_24h?: number
      restorable?: number
      expiry_enabled?: boolean
    }
    skills: number | null | undefined
    job_titles: number | null | undefined
    boilerplate: number | null | undefined
  }
  pipeline: {
    error?: string
    window_days?: number
    live_posts?: number
    ready?: number
    ready_pct?: number
    only_employment_type_missing?: number
    fill_rates_pct?: Record<string, number>
    missing_by_blocker?: Record<string, number>
    distinct_roles?: number
    roles_with_duplicates?: number
    outbox?: { states?: Record<string, number>; dispatch_enabled?: boolean }
    core_pushes?: Record<string, number>
  }
  automation: {
    error?: string
    triage?: {
      last_run_at?: string | null
      minutes_ago?: number | null
      status?: string
      skills?: { processed?: number; approved?: number; rejected?: number; left_for_review?: number }
      titles?: { processed?: number; approved?: number; rejected?: number; left_for_review?: number }
      boilerplate?: { processed?: number; approved?: number; rejected?: number; left_for_review?: number }
    }
    daily_cleanup?: { enabled?: boolean; auto_blocks_active?: number; last_run?: { ran_at?: string; summary?: Record<string, unknown> } | null }
    expiry?: { enabled?: boolean; removed_last_24h?: number; ttl_days?: number }
  }
  jobs: {
    active?: { kind: string; status: string; processed: number; total: number; percent: number; failed: number } | null
  }
  intake: { last_email_minutes_ago?: number | null; emails_last_24h?: number; error?: string }
}

export interface SyncCheck {
  group: 'parsing' | 'twenty'
  id: string
  label: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
  action?: string
}

export interface SyncStatus {
  generated_at: string
  checks: SyncCheck[]
  overall: { parsing: 'ok' | 'warn' | 'fail'; twenty: 'ok' | 'warn' | 'fail' }
  parsing: {
    error?: string
    last_email_minutes_ago?: number | null
    parsed_1h?: number
    parsed_24h?: number
    ready_24h?: number
    needs_review_24h?: number
    spam_24h?: number
    intake_24h?: Record<string, number>
    latest_job?: { kind: string; status: string; processed: number; total: number; failed: number } | null
  }
  service: {
    error?: string
    last_success_minutes_ago?: number | null
    reconciliation?: { day?: string; status?: string; checked?: number; verified?: number; exceptions?: number; started_hours_ago?: number | null }
    worker_restarts?: { incidents: number; last_minutes_ago: number | null }
    source_poll?: { status?: string; completed_minutes_ago?: number | null }
  }
  capture: { error?: string; captured_24h?: number }
  outbox: {
    error?: string
    backlog?: number
    oldest_backlog_minutes?: number | null
    published_1h?: number
    published_24h?: number
    created_24h?: number
    retrying?: number
  }
  inbox_quarantine: {
    error?: string
    inbox?: Record<string, number>
    processing?: { count: number; older_than_24h: number }
    quarantine_open?: number
    quarantine_by_reason?: { reason: string; count: number; oldest_days: number }[]
  }
  alerts: { error?: string; active?: { code: string; label: string; count: number; last_seen_minutes_ago: number | null; since_days: number }[] }
}
