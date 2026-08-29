import type {
  DraftObject,
  DraftObjectType,
  DraftPublishResult,
  EmailClaim,
  FieldProvenanceEntry,
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
}
