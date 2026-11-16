import { useRef, useState } from 'react'
import { coachAsk } from '../api/client'

interface Message {
  role: 'user' | 'assistant'
  text: string
}

export function CoachPanel() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      text: 'Ask about setups, risk, or how to read a signal. I explain — I do not tell you what to buy.',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  async function send() {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', text: q }, { role: 'assistant', text: '' }])
    setLoading(true)
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac

    try {
      await coachAsk(
        q,
        (chunk) => {
          setMessages((prev) => {
            const copy = [...prev]
            const last = copy[copy.length - 1]
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = { ...last, text: last.text + chunk }
            }
            return copy
          })
        },
        ac.signal,
      )
    } catch (e) {
      setMessages((prev) => {
        const copy = [...prev]
        const last = copy[copy.length - 1]
        if (last?.role === 'assistant' && !last.text) {
          copy[copy.length - 1] = {
            role: 'assistant',
            text:
              e instanceof Error
                ? `Coach unavailable (${e.message}). Backend coach routes may not be wired yet.`
                : 'Coach unavailable.',
          }
        }
        return copy
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="flex h-[min(70vh,640px)] flex-col rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)]">
      <div className="border-b border-[var(--color-border)] px-4 py-3">
        <h2 className="text-base font-semibold">Coach</h2>
        <p className="text-xs text-[var(--color-muted)]">Streaming when SSE is available · POST /api/coach/ask</p>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4 scrollbar-thin">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`max-w-[90%] rounded-lg px-3 py-2 text-sm leading-relaxed ${
              m.role === 'user'
                ? 'ml-auto bg-[var(--color-border)]/50'
                : 'mr-auto border border-[var(--color-border)]/80 bg-[var(--color-surface)]'
            }`}
          >
            {m.text || (loading && i === messages.length - 1 ? '…' : '')}
          </div>
        ))}
      </div>
      <form
        className="flex gap-2 border-t border-[var(--color-border)] p-4"
        onSubmit={(e) => {
          e.preventDefault()
          void send()
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask the coach…"
          className="min-w-0 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm outline-none focus:border-[var(--color-accent)]"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="neon-btn rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </section>
  )
}