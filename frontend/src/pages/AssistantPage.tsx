import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  toolUsed?: string | null
}

const STARTER_QUESTIONS = [
  'How many skills and job titles are in the taxonomy?',
  "What's pending review right now?",
  'How much did we spend on LLM calls this week?',
  'How is the automated daily triage doing?',
  'How is email parsing quality looking this week?',
]

export function AssistantPage({ onBack }: { onBack: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content:
        "Ask me anything about the taxonomy, the review queue, daily triage activity, LLM cost, or parsing quality.",
    },
  ])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send(question: string) {
    const trimmed = question.trim()
    if (!trimmed || sending) return

    setError(null)
    const nextMessages: ChatMessage[] = [...messages, { role: 'user', content: trimmed }]
    setMessages(nextMessages)
    setInput('')
    setSending(true)

    try {
      const history = nextMessages.slice(-8).map((m) => ({ role: m.role, content: m.content }))
      const result = await api.assistantQuery(trimmed, history)
      setMessages((prev) => [...prev, { role: 'assistant', content: result.answer, toolUsed: result.tool_used }])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The assistant failed to respond')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-0px)] max-w-3xl flex-col px-6 py-8">
      <header className="mb-4 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Assistant</h1>
          <p className="mt-1 text-sm text-ink-soft">Ask questions about your data in plain English.</p>
        </div>
        <button
          onClick={onBack}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-soft transition hover:text-ink"
        >
          Back to drafts
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto rounded-xl border border-line bg-surface p-4">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
                m.role === 'user' ? 'bg-accent text-white' : 'bg-paper text-ink'
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-xl bg-paper px-3.5 py-2.5 text-sm text-ink-soft">Thinking…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && <div className="mt-3 rounded-lg bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}

      {messages.length <= 1 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {STARTER_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => send(q)}
              className="rounded-full border border-line bg-surface px-3 py-1.5 text-xs text-ink-soft transition hover:text-ink"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
        className="mt-3 flex items-center gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question…"
          disabled={sending}
          className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  )
}
