import { useCallback, useState } from 'react'
import { apiGet, apiPost } from '../api/client'
import type { PaperTrade, PortfolioStats, QuoteResponse } from '../types/api'
import { usePolling } from '../hooks/usePolling'
import { Skeleton } from './Skeleton'

interface TradeListResponse {
  items?: PaperTrade[]
  trades?: PaperTrade[]
}

function normalizeTrades(list: TradeListResponse | PaperTrade[] | { items: PaperTrade[] }): PaperTrade[] {
  if (Array.isArray(list)) return list
  if ('trades' in list && list.trades) return list.trades
  if ('items' in list && list.items) return list.items
  return []
}

export function Portfolio() {
  const fetchPortfolio = useCallback(async (signal: AbortSignal) => {
    const [list, stats] = await Promise.all([
      apiGet<TradeListResponse | PaperTrade[]>('/api/portfolio/trades', signal).catch(() => ({
        items: [] as PaperTrade[],
      })),
      apiGet<PortfolioStats>('/api/portfolio/stats', signal).catch(
        (): PortfolioStats => ({
          open_positions: 0,
          closed_trades: 0,
          realized_pnl: 0,
          open_pnl: 0,
        }),
      ),
    ])
    const trades = normalizeTrades(list)
    return { trades, stats }
  }, [])

  const { data, loading, error, refresh } = usePolling(fetchPortfolio, 60_000)

  const [ticker, setTicker] = useState('')
  const [qty, setQty] = useState('10')
  const [adding, setAdding] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const trades = data?.trades ?? []
  const stats = data?.stats

  async function addPaperTrade() {
    const t = ticker.trim().toUpperCase()
    const quantity = Number(qty)
    if (!t || !Number.isFinite(quantity) || quantity <= 0) return
    setAdding(true)
    setFormError(null)
    try {
      let entry = 0
      try {
        const q = await apiGet<QuoteResponse>(`/api/market/quote/${encodeURIComponent(t)}`)
        entry = q.price
      } catch {
        entry = 0
      }
      await apiPost('/api/portfolio/trades', {
        ticker: t,
        quantity,
        entry_price: entry || undefined,
        asset_type: 'equity',
        side: 'long',
      })
      setTicker('')
      refresh()
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Could not add trade')
    } finally {
      setAdding(false)
    }
  }

  async function closeTrade(id: number) {
    try {
      await apiPost(`/api/portfolio/trades/${id}/close`, {})
      refresh()
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Close failed')
    }
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold">Portfolio</h2>
        <p className="text-xs text-[var(--color-muted)]">Paper positions · /api/portfolio/*</p>
      </div>

      {loading && !data ? (
        <Skeleton className="h-20 w-full" />
      ) : stats ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 font-mono text-sm">
          <Stat label="Open" value={String(stats.open_positions)} />
          <Stat
            label="Realized P&amp;L"
            value={formatMoney(stats.realized_pnl ?? stats.total_realized_pnl ?? 0)}
            tone={pnlTone(stats.realized_pnl ?? stats.total_realized_pnl ?? 0)}
          />
          <Stat
            label="Unrealized"
            value={
              (stats.open_pnl ?? stats.unrealized_pnl) != null
                ? formatMoney(stats.open_pnl ?? stats.unrealized_pnl ?? 0)
                : '—'
            }
            tone={
              (stats.open_pnl ?? stats.unrealized_pnl) != null
                ? pnlTone(stats.open_pnl ?? stats.unrealized_pnl ?? 0)
                : undefined
            }
          />
          <Stat
            label="Win rate"
            value={stats.win_rate != null ? `${Number(stats.win_rate).toFixed(0)}%` : '—'}
          />
        </div>
      ) : null}

      {error ? <p className="text-sm text-[var(--color-muted)]">{error}</p> : null}
      {formError ? <p className="text-sm text-[var(--color-negative)]">{formError}</p> : null}

      <form
        className="flex flex-wrap items-end gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
        onSubmit={(e) => {
          e.preventDefault()
          void addPaperTrade()
        }}
      >
        <label className="text-xs text-[var(--color-muted)]">
          Ticker
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            className="mt-1 block w-28 rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 font-mono uppercase text-sm"
          />
        </label>
        <label className="text-xs text-[var(--color-muted)]">
          Qty
          <input
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            className="mt-1 block w-20 rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 font-mono text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={adding}
          className="rounded-md bg-[var(--color-border)] px-4 py-2 text-sm disabled:opacity-50"
        >
          {adding ? 'Adding…' : 'Add paper trade'}
        </button>
      </form>

      <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead className="border-b border-[var(--color-border)] bg-[var(--color-surface-raised)] text-xs text-[var(--color-muted)]">
            <tr>
              <th className="px-3 py-2">Ticker</th>
              <th className="px-3 py-2">Qty</th>
              <th className="px-3 py-2">Entry</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">P&amp;L</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-[var(--color-muted)]">
                  No trades yet
                </td>
              </tr>
            ) : (
              trades.map((tr) => (
                <tr key={tr.id} className="border-b border-[var(--color-border)]/40">
                  <td className="px-3 py-2 font-mono">{tr.ticker}</td>
                  <td className="px-3 py-2 font-mono">{tr.quantity}</td>
                  <td className="px-3 py-2 font-mono">{tr.entry_price.toFixed(2)}</td>
                  <td className="px-3 py-2">{tr.status}</td>
                  <td
                    className={`px-3 py-2 font-mono ${
                      tr.realized_pnl != null ? pnlTone(tr.realized_pnl) : 'text-[var(--color-muted)]'
                    }`}
                  >
                    {tr.realized_pnl != null ? formatMoney(tr.realized_pnl) : '—'}
                  </td>
                  <td className="px-3 py-2">
                    {tr.status === 'open' ? (
                      <button
                        type="button"
                        onClick={() => void closeTrade(tr.id)}
                        className="text-xs text-[var(--color-accent)] hover:underline"
                      >
                        Close
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: string
}) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 py-2">
      <div className="text-xs text-[var(--color-muted)]" dangerouslySetInnerHTML={{ __html: label }} />
      <div className={tone ?? ''}>{value}</div>
    </div>
  )
}

function formatMoney(n: number): string {
  const sign = n >= 0 ? '+' : ''
  return `${sign}$${n.toFixed(2)}`
}

function pnlTone(n: number): string {
  if (n > 0) return 'text-[var(--color-positive)]'
  if (n < 0) return 'text-[var(--color-negative)]'
  return 'text-[var(--color-muted)]'
}