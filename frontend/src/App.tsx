import { useState } from 'react'
import { clearToken } from './api/client'
import { TokenGate } from './components/TokenGate'
import { AccuracyPage } from './pages/AccuracyPage'
import { DraftDetailPage } from './pages/DraftDetailPage'
import { DraftListPage } from './pages/DraftListPage'
import { ModerationPage } from './pages/ModerationPage'

type View =
  | { name: 'list' }
  | { name: 'detail'; draftId: string }
  | { name: 'moderation' }
  | { name: 'accuracy' }

function AppShell() {
  const [view, setView] = useState<View>({ name: 'list' })

  return (
    <div className="min-h-screen bg-paper">
      <nav className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <button onClick={() => setView({ name: 'list' })} className="text-sm font-semibold text-ink">
            Hermes Email Review
          </button>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setView({ name: 'accuracy' })}
              className={`text-xs font-medium transition ${
                view.name === 'accuracy' ? 'text-accent' : 'text-ink-soft hover:text-ink'
              }`}
            >
              Accuracy
            </button>
            <button
              onClick={() => setView({ name: 'moderation' })}
              className={`text-xs font-medium transition ${
                view.name === 'moderation' ? 'text-accent' : 'text-ink-soft hover:text-ink'
              }`}
            >
              Blocklist &amp; taxonomy
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
        </div>
      </nav>

      {view.name === 'detail' && (
        <DraftDetailPage draftId={view.draftId} onBack={() => setView({ name: 'list' })} />
      )}
      {view.name === 'moderation' && <ModerationPage onBack={() => setView({ name: 'list' })} />}
      {view.name === 'accuracy' && <AccuracyPage onBack={() => setView({ name: 'list' })} />}
      {view.name === 'list' && <DraftListPage onSelect={(id) => setView({ name: 'detail', draftId: id })} />}
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
