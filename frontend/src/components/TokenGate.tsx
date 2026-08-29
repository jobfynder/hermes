import { useState, type FormEvent, type ReactNode } from 'react'
import { getToken, setToken } from '../api/client'

export function TokenGate({ children }: { children: ReactNode }) {
  const [token, setLocalToken] = useState(() => getToken())
  const [draft, setDraft] = useState('')

  if (token) {
    return <>{children}</>
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!draft.trim()) return
    setToken(draft.trim())
    setLocalToken(draft.trim())
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-xl border border-line bg-surface p-6 shadow-sm"
      >
        <h1 className="text-lg font-semibold text-ink">Hermes Email Review</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Enter your Hermes access token to continue. It's stored only in this browser.
        </p>
        <input
          type="password"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Access token"
          className="mono mt-4 w-full rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        />
        <button
          type="submit"
          className="mt-3 w-full rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:opacity-90"
        >
          Continue
        </button>
      </form>
    </div>
  )
}
