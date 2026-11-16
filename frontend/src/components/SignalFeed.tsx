import { useState, type ReactNode } from 'react'
import { apiGet, apiPost } from '../api/client'
import type { SignalResponse } from '../types/api'
import { Skeleton } from './Skeleton'

function actionColor(action: string): string {
  const a = action.toUpperCase()
  if (a === 'BUY') return 'text-[var(--color-positive)]'
  if (a === 'AVOID') return 'text-[var(--color-negative)]'
  return 'text-[var(--color-muted)]'
}

export function SignalFeed() {
  const [ticker, setTicker] = useState('SPY')
  const [signal, setSignal] = useState<SignalResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<string | null>(null)
  const [analyzing, setAnalyzing] = useState(false)

  async function scan() {
    const t = ticker.trim().toUpperCase()
    if (!t) return
    setLoading(true)
    setError(null)
    setAnalysis(null)
    try {
      const res = await apiGet<SignalResponse>(`/api/signals/${encodeURIComponent(t)}`)
      setSignal(res)
      if (res.error) setError(res.error)
    } catch (e) {
      setSignal(null)
      setError(e instanceof Error ? e.message : 'Scan failed')
    } finally {
      setLoading(false)
    }
  }

  async function analyze() {
    if (!signal) return
    setAnalyzing(true)
    setAnalysis(null)
    try {
      const res = await apiPost<{ answer?: string; message?: string; content?: string }>(
        '/api/coach/analyze-signal',
        { ticker: signal.ticker, signal },
      )
      setAnalysis(res.answer ?? res.message ?? res.content ?? JSON.stringify(res))
    } catch (e) {
      setAnalysis(
        e instanceof Error
          ? `Analysis unavailable (${e.message}). Expected POST /api/coach/analyze-signal.`
          : 'Analysis unavailable.',
      )
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold">Signals</h2>
        <p className="text-xs text-[var(--color-muted)]">Technical scan per ticker · educational only</p>
      </div>

      <ScanForm
        ticker={ticker}
        setTicker={setTicker}
        onScan={() => void scan()}
        loading={loading}
      />

      {loading ? (
        <InfoBox>
          <Skeleton className="mb-3 h-6 w-32" />
          <SkeletonLinesWrap />
        </InfoBox>
      ) : null}

      {error && !loading ? (
        <p className="text-sm text-[var(--color-negative)]">{error}</p>
      ) : null}

      {signal && !loading ? (
        <InfoBox>
          <button
            type="button"
            onClick={() => void analyze()}
            disabled={analyzing}
            className="w-full text-left transition hover:bg-[var(--color-surface)]/40 rounded-md -m-2 p-2"
          >
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-lg">{signal.ticker}</span>
              <span className={`font-semibold ${actionColor(signal.action)}`}>{signal.action}</span>
              <span className="text-sm text-[var(--color-muted)]">
                Confidence {(signal.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-[var(--color-muted)]">{signal.reasoning}</p>
            <dl className="mt-4 grid grid-cols-3 gap-2 font-mono text-xs">
              <StatDt label="Entry" value={signal.entry_zone} />
              <StatDt label="Stop" value={signal.stop_price} />
              <StatDt label="Target" value={signal.target_price} />
            </dl>
            <p className="mt-3 text-xs text-[var(--color-accent)]">
              {analyzing ? 'Asking coach…' : 'Click card for coach analysis'}
            </p>
          </button>
          {analysis ? (
            <div className="mt-4 border-t border-[var(--color-border)] pt-4 text-sm leading-relaxed">
              {analysis}
            </div>
          ) : null}
        </InfoBox>
      ) : null}
    </section>
  )
}

function ScanForm({
  ticker,
  setTicker,
  onScan,
  loading,
}: {
  ticker: string
  setTicker: (v: string) => void
  onScan: () => void
  loading: boolean
}) {
  return (
    <form
      className="flex flex-wrap gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        onScan()
      }}
    >
      <input
        type="text"
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        className="w-32 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 py-2 font-mono text-sm uppercase"
        placeholder="Ticker"
      />
      <button
        type="submit"
        disabled={loading}
        className="rounded-md bg-[var(--color-border)] px-4 py-2 text-sm font-medium hover:bg-[var(--color-border)]/80 disabled:opacity-50"
      >
        {loading ? 'Scanning…' : 'Scan'}
      </button>
    </form>
  )
}

function InfoBox({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
      {children}
    </div>
  )
}

function StatDt({ label, value }: { label: string; value?: number | null }) {
  return (
    <div>
      <dt className="text-[var(--color-muted)]">{label}</dt>
      <dd>{value != null ? value.toFixed(2) : '—'}</dd>
    </div>
  )
}

function SkeletonLinesWrap() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
    </div>
  )
}