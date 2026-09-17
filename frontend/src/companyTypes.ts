export interface CompanyEntry {
  company_id: string
  identity_domain: string
  canonical_name: string
  verification_status: string
  claim_status: string
  source_count: number
  contact_count: number
  last_seen: string
  avg_confidence?: number
}
export interface CompanySource {
  draft_id: string
  company_label: string
  contact_email: string | null
  website: string | null
  phone: string | null
  location: string | null
  confidence: number
  method: string
  channel: string
  observed_at: string
  jobs: { key: string; title: string; location: string; named_client: string; requires_review: boolean }[]
}
export interface CompanyDetail extends CompanyEntry {
  observed_names: { company_label: string; sources: number }[]
  contacts: { email: string; name: string | null; source_count: number; last_seen: string }[]
  sources: CompanySource[]
  job_requirements: number
  activity: { score: number; recent_unique_requirements: number; recent_contacts: number; recent_sources: number; window_days: number; version: string }
}
export interface CompanyPage {
  items: CompanyEntry[]
  total_count: number
  page: number
  page_size: number
  sync: { processed: number; linked: number; total: number; last_synced: string | null }
}
