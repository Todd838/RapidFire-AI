import { useCallback, useMemo } from 'react'
import { apiGet } from '../api/client'
import type { QuoteResponse } from '../types/api'
import { usePolling } from '../hooks/usePolling'
import { Skeleton } from './Skeleton'

const WATCH = ['SPY', 'QQQ', 'AAPL', 'NVDA', 'BTC']

function formatPct(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(pct)) return '—'
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

export function MarketTicker() {
  const fetchQuotes = useCallback(async (signal: AbortSignal) => {
    const results = await Promise.all(
      WATCH.map(async (ticker) => {
        const path =
          ticker === 'BTC'
            ? '/api/market/crypto/BTC'
            : `/api/market/quote/${encodeURIComponent(ticker)}`
        try {
          return await apiGet<QuoteResponse>(path, signal)
        } catch {
          return { ticker, price: 0, as_of: new Date().toISOString(), error: 'unavailable' }
        }
      }),
    )
    return results
  }, [])

  const { data, loading, error } = usePolling(fetchQuotes, 60_000)

  const items = useMemo(() => data ?? [], [data])

  return (
    <div className="border-b border-[var(--color-border)] bg-[var(--color-surface-raised)]">
      <div className="mx-auto flex max-w-7xl items-center gap-4 overflow-x-auto px-4 py-2 scrollbar-thin">
        <span className="shrink-0 text-xs font-medium uppercase tracking-wider text-[var(--color-muted)]">
          Market
        </span>
        {loading && items.length === 0 ? (
          <div className="flex gap-6">
            {WATCH.map((t) => (
              <Skeleton key={t} className="h-5 w-24" />
            ))}
          </div>
        ) : (
          items.map((q) => {
            const up = (q.change_pct ?? 0) >= 0
            const label = q.ticker === 'BTC' ? 'BTC' : q.ticker
            return (
              <div key={label} className="flex shrink-0 items-baseline gap-2 font-mono text-sm">
                <span className="text-[var(--color-muted)]">{label}</span>
                <span>{q.error ? '—' : q.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                <span
                  className={
                    q.error
                      ? 'text-[var(--color-muted)]'
                      : up
                        ? 'text-[var(--color-positive)]'
                        : 'text-[var(--color-negative)]'
                  }
                >
                  {formatPct(q.change_pct)}
                </span>
              </div>
            )
          })
        )}
        {error ? (
          <span className="ml-auto text-xs text-[var(--color-muted)]">Ticker stale — {error}</span>
        ) : null}
      </div>
    </div>
  )
}