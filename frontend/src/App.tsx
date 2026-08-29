import { useState } from 'react'
import { clearToken } from './api/client'
import { TokenGate } from './components/TokenGate'
import { DraftDetailPage } from './pages/DraftDetailPage'
import { DraftListPage } from './pages/DraftListPage'

function AppShell() {
  const [selected, setSelected] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-paper">
      <nav className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <button onClick={() => setSelected(null)} className="text-sm font-semibold text-ink">
            Hermes Email Review
          </button>
          <button
            onClick={() => {
              clearToken()
              window.location.reload()
            }}
            className="text-xs text-ink-soft hover:text-ink"
          >
            Sign out
          </button>
        </div>
      </nav>

      {selected ? (
        <DraftDetailPage draftId={selected} onBack={() => setSelected(null)} />
      ) : (
        <DraftListPage onSelect={setSelected} />
      )}
    </div>
  )
}

export default function App() {
  return (
    <TokenGate>
      <AppShell />
    </TokenGate>
  )
}
