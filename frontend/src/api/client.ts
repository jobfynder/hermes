import type {
  AccuracySummary,
  BlocklistEntry,
  CanonicalSkillEntry,
  ClaimPrepareResult,
  DeleteDraftResult,
  DraftObject,
  DraftObjectType,
  DraftPublishResult,
  DraftSummaryEntry,
  EmailClaim,
  FieldProvenanceEntry,
  JobTitleEntry,
  TaxonomyCandidateEntry,
} from '../types'

const TOKEN_STORAGE_KEY = 'hermes_review_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()

  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      Authorization: `Bearer ${token ?? ''}`,
      ...init?.headers,
    },
  })

  if (response.status === 401) {
    clearToken()
    throw new ApiError(401, 'Access token was rejected. Please re-enter it.')
  }

  if (!response.ok) {
    const body = await response.text()
    throw new ApiError(response.status, body || response.statusText)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export const api = {
  listDrafts: () => request<DraftObject[]>('/drafts'),
  listDraftSummaries: (includeDuplicates = false) =>
    request<DraftSummaryEntry[]>(`/drafts/summary?include_duplicates=${includeDuplicates}`),
  getDraft: (id: string) => request<DraftObject>(`/drafts/${id}`),
  getProvenance: (id: string) => request<FieldProvenanceEntry[]>(`/drafts/${id}/provenance`),
  getClaim: (id: string) => request<EmailClaim | null>(`/drafts/${id}/claim`).catch((err) => {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }),
  publishDraft: (id: string) => request<DraftPublishResult>(`/drafts/${id}/publish`, { method: 'POST' }),
  rejectDraft: (id: string, reason?: string) =>
    request<DraftPublishResult>(`/drafts/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  reclassifyDraft: (id: string, correctedDraftType: DraftObjectType) =>
    request<DraftObject>(`/drafts/${id}/reclassify`, {
      method: 'POST',
      body: JSON.stringify({ corrected_draft_type: correctedDraftType }),
    }),
  prepareClaim: (draftId: string) =>
    request<ClaimPrepareResult>('/claim/prepare', {
      method: 'POST',
      body: JSON.stringify({ draft_id: draftId }),
    }),
  markClaimSent: (claimId: string) =>
    request<EmailClaim>(`/claim/${claimId}/mark-sent`, { method: 'POST' }),
  deleteDraft: (id: string) => request<DeleteDraftResult>(`/drafts/${id}`, { method: 'DELETE' }),
  blockDraftSender: (id: string, matchType: 'domain' | 'email', reason?: string) =>
    request<{ blocked: boolean; match_type?: string; value?: string; reason?: string }>(
      `/drafts/${id}/block-sender`,
      { method: 'POST', body: JSON.stringify({ match_type: matchType, reason }) },
    ),
  listBlocklist: () => request<BlocklistEntry[]>('/blocklist'),
  addBlock: (matchType: 'domain' | 'email', value: string, reason?: string) =>
    request<BlocklistEntry>('/blocklist', {
      method: 'POST',
      body: JSON.stringify({ match_type: matchType, value, reason }),
    }),
  removeBlock: (id: number) => request<{ removed: boolean }>(`/blocklist/${id}`, { method: 'DELETE' }),
  listTaxonomyCandidates: (status = 'pending') =>
    request<TaxonomyCandidateEntry[]>(`/taxonomy-candidates?status=${status}`),
  approveTaxonomyCandidate: (id: number, category?: string, skillType?: string) =>
    request<{ ok: boolean; term?: string; reason?: string }>(`/taxonomy-candidates/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ category, skill_type: skillType }),
    }),
  rejectTaxonomyCandidate: (id: number) =>
    request<{ ok: boolean; term?: string; reason?: string }>(`/taxonomy-candidates/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  editTaxonomyCandidate: (id: number, term: string) =>
    request<{ ok: boolean; term?: string; reason?: string }>(`/taxonomy-candidates/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ term }),
    }),
  bulkApproveTaxonomyCandidates: (ids: number[]) =>
    request<{ ok_count: number; ok_terms: string[]; failed: { candidate_id: number; reason?: string }[] }>(
      '/taxonomy-candidates/bulk-approve',
      { method: 'POST', body: JSON.stringify({ candidate_ids: ids }) },
    ),
  bulkRejectTaxonomyCandidates: (ids: number[]) =>
    request<{ ok_count: number; ok_terms: string[]; failed: { candidate_id: number; reason?: string }[] }>(
      '/taxonomy-candidates/bulk-reject',
      { method: 'POST', body: JSON.stringify({ candidate_ids: ids }) },
    ),
  correctDraftFields: (
    id: string,
    recordType: 'job_requirement' | 'hotlist' | 'signature',
    recordIndex: number,
    corrections: Record<string, unknown>,
  ) =>
    request<DraftObject>(`/drafts/${id}/fields`, {
      method: 'PATCH',
      body: JSON.stringify({ record_type: recordType, record_index: recordIndex, corrections }),
    }),
  getAccuracySummary: (days = 30) => request<AccuracySummary>(`/accuracy/summary?days=${days}`),
  browseSkillsTaxonomy: () => request<CanonicalSkillEntry[]>('/understanding/taxonomy/skills/browse'),
  browseJobTitlesTaxonomy: () =>
    request<{ titles: JobTitleEntry[] }>('/understanding/taxonomy/job-titles').then((r) => r.titles),
  updateSkillDescription: (name: string, description: string) =>
    request<{ updated: boolean; reason?: string }>('/taxonomy/skills/description', {
      method: 'PATCH',
      body: JSON.stringify({ name, description }),
    }),
  updateJobTitle: (
    currentTitle: string,
    changes: { newTitle?: string; family?: string; seniority?: string },
  ) =>
    request<{ updated: boolean; title?: string; reason?: string }>('/taxonomy/job-titles', {
      method: 'PATCH',
      body: JSON.stringify({
        current_title: currentTitle,
        new_title: changes.newTitle,
        family: changes.family,
        seniority: changes.seniority,
      }),
    }),
  bulkSetJobTitleFamily: (titles: string[], family: string) =>
    request<{ updated_count: number; updated_titles: string[] }>('/taxonomy/job-titles/bulk-set-family', {
      method: 'POST',
      body: JSON.stringify({ titles, family }),
    }),
  suggestJobTitleFamily: (title: string) =>
    request<{ family: string; method: string }>('/taxonomy/job-titles/suggest-family', {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),
  autoClassifyJobTitles: () =>
    request<{
      checked_count: number
      classified_count: number
      still_unclassified_count: number
      results: { title: string; family: string; method: string }[]
    }>('/taxonomy/job-titles/auto-classify', { method: 'POST' }),
}
