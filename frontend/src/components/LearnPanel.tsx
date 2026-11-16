import { useState } from 'react'
import { coachAsk } from '../api/client'

const CONCEPTS = [
  {
    title: 'Risk per trade',
    body: 'Size so a stop-out costs a fixed fraction of equity — not your conviction level.',
  },
  {
    title: 'Trend vs range',
    body: 'Indicators mean different things when price is trending versus chopping sideways.',
  },
  {
    title: 'Liquidity',
    body: 'Wide spreads and thin volume amplify slippage; paper fills lie about real execution.',
  },
  {
    title: 'Position sizing',
    body: 'Shares = risk dollars ÷ (entry − stop). Never invert that math after you like the ticker.',
  },
  {
    title: 'Drawdowns',
    body: 'Recovery math is brutal: a 50% loss needs a 100% gain. Defense first.',
  },
  {
    title: 'Process over outcome',
    body: 'One trade proves nothing. Journal whether you followed your rules.',
  },
]

export function LearnPanel() {
  const [topic, setTopic] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function askTopic() {
    const t = topic.trim()
    if (!t) return
    setLoading(true)
    setAnswer('')
    try {
      await coachAsk(t, (chunk) => setAnswer((prev) => (prev ?? '') + chunk))
    } catch (e) {
      setAnswer(e instanceof Error ? e.message : 'Coach unavailable')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-base font-semibold">Learn</h2>
        <p className="text-xs text-[var(--color-muted)]">Core concepts · ask anything custom below</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {CONCEPTS.map((c) => (
          <article
            key={c.title}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
          >
            <h3 className="text-sm font-semibold">{c.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-[var(--color-muted)]">{c.body}</p>
          </article>
        ))}
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
        <h3 className="text-sm font-medium">Custom topic</h3>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="Explain VIX term structure like I'm new"
            className="min-w-0 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
          />
          <button
            type="button"
            disabled={loading}
            onClick={() => void askTopic()}
            className="neon-btn rounded-md px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {loading ? 'Asking…' : 'Ask coach'}
          </button>
        </div>
        {answer !== null ? (
          <p className="mt-4 text-sm leading-relaxed whitespace-pre-wrap">{answer}</p>
        ) : null}
      </div>
    </section>
  )
}