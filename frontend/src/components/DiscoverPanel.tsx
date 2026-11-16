import { useCallback, useState, type ReactNode } from 'react'
import { apiGet, apiPost } from '../api/client'
import type { IpoListResponse, MarketMoversResponse, QuoteResponse } from '../types/api'
import { usePolling } from '../hooks/usePolling'
import { Skeleton, SkeletonLines } from './Skeleton'

const CRYPTO = ['BTC', 'ETH', 'SOL']

export function DiscoverPanel() {
  const fetchMovers = useCallback(
    (signal: AbortSignal) => apiGet<MarketMoversResponse>('/api/market/movers', signal),
    [],
  )
  const { data: movers, loading: moversLoading, error: moversError } = usePolling(fetchMovers, 60_000)

  const fetchCrypto = useCallback(async (signal: AbortSignal) => {
    return Promise.all(
      CRYPTO.map((t) =>
        apiGet<QuoteResponse>(`/api/market/crypto/${t}`, signal).catch(() => null),
      ),
    )
  }, [])
  const { data: crypto, loading: cryptoLoading } = usePolling(fetchCrypto, 60_000)

  const [ipos, setIpos] = useState<IpoListResponse | null>(null)
  const [ipoLoading, setIpoLoading] = useState(false)
  const [ipoError, setIpoError] = useState<string | null>(null)

  const [discoverPrompt, setDiscoverPrompt] = useState('')
  const [discoverAnswer, setDiscoverAnswer] = useState<string | null>(null)
  const [discoverBusy, setDiscoverBusy] = useState(false)

  async function loadIpos() {
    setIpoLoading(true)
    setIpoError(null)
    try {
      const res = await apiGet<IpoListResponse>('/api/market/ipos')
      setIpos(res)
      if (res.error) setIpoError(res.error)
    } catch (e) {
      setIpoError(e instanceof Error ? e.message : 'IPO fetch failed')
    } finally {
      setIpoLoading(false)
    }
  }

  async function askDiscover() {
    const q = discoverPrompt.trim()
    if (!q) return
    setDiscoverBusy(true)
    setDiscoverAnswer(null)
    try {
      const res = await apiPost<{ answer?: string; message?: string; content?: string }>(
        '/api/coach/discover',
        { question: q },
      )
      setDiscoverAnswer(res.answer ?? res.message ?? res.content ?? 'No response')
    } catch (e) {
      setDiscoverAnswer(
        e instanceof Error ? e.message : 'Coach discover endpoint not available yet',
      )
    } finally {
      setDiscoverBusy(false)
    }
  }

  return (
    <section className="space-y-6">
      <SectionHeader title="Discover" subtitle="Movers, IPOs, crypto — then ask the coach" />

      <TwoColumnGrid>
        <PanelCard title="Gainers">
          {moversLoading && !movers ? (
            <SkeletonLines />
          ) : (
            <MoverList items={movers?.gainers ?? []} />
          )}
        </PanelCard>
        <PanelCard title="Losers">
          {moversLoading && !movers ? (
            <SkeletonLines />
          ) : (
            <MoverList items={movers?.losers ?? []} />
          )}
        </PanelCard>
      </TwoColumnGrid>
      {moversError ? <p className="text-xs text-[var(--color-muted)]">{moversError}</p> : null}

      <PanelCard title="Crypto quotes">
        {cryptoLoading && !crypto ? (
          <div className="flex gap-4">
            {CRYPTO.map((c) => (
              <Skeleton key={c} className="h-12 w-24" />
            ))}
          </div>
        ) : (
          <div className="flex flex-wrap gap-4 font-mono text-sm">
            {(crypto ?? []).map((q) =>
              q ? (
                <div key={q.ticker} className="rounded border border-[var(--color-border)] px-3 py-2">
                  <div className="text-[var(--color-muted)]">{q.ticker}</div>
                  <div>{q.price.toLocaleString()}</div>
                  <div
                    className={
                      (q.change_pct ?? 0) >= 0
                        ? 'text-[var(--color-positive)]'
                        : 'text-[var(--color-negative)]'
                    }
                  >
                    {q.change_pct != null ? `${q.change_pct >= 0 ? '+' : ''}${q.change_pct.toFixed(2)}%` : '—'}
                  </div>
                </div>
              ) : null,
            )}
          </div>
        )}
      </PanelCard>

      <PanelCard title="IPOs">
        <button
          type="button"
          onClick={() => void loadIpos()}
          disabled={ipoLoading}
          className="mb-3 rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs hover:bg-[var(--color-surface)]"
        >
          {ipoLoading ? 'Loading…' : 'Load IPO calendar'}
        </button>
        {ipoError ? <p className="text-xs text-[var(--color-muted)]">{ipoError}</p> : null}
        {ipos?.items.length ? (
          <ul className="space-y-2 text-sm">
            {ipos.items.map((item) => (
              <li key={item.ticker} className="flex justify-between gap-2 border-b border-[var(--color-border)]/50 py-2">
                <span className="font-mono">{item.ticker}</span>
                <span className="text-[var(--color-muted)]">{item.name ?? item.ipo_date ?? '—'}</span>
              </li>
            ))}
          </ul>
        ) : ipos && !ipoLoading ? (
          <p className="text-sm text-[var(--color-muted)]">No IPO rows returned.</p>
        ) : null}
      </PanelCard>

      <PanelCard title="Ask coach to explore">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            type="text"
            value={discoverPrompt}
            onChange={(e) => setDiscoverPrompt(e.target.value)}
            placeholder="e.g. What sectors are rotating this week?"
            className="min-w-0 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
          />
          <button
            type="button"
            disabled={discoverBusy}
            onClick={() => void askDiscover()}
            className="neon-btn rounded-md px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {discoverBusy ? 'Thinking…' : 'Discover'}
          </button>
        </div>
        {discoverAnswer ? (
          <p className="mt-3 text-sm leading-relaxed text-[var(--color-muted)]">{discoverAnswer}</p>
        ) : null}
      </PanelCard>
    </section>
  )
}

function MoverList({ items }: { items: MarketMoversResponse['gainers'] }) {
  if (!items.length) return <p className="text-sm text-[var(--color-muted)]">No data</p>
  return (
    <ul className="space-y-1 font-mono text-sm">
      {items.slice(0, 8).map((m) => (
        <li key={m.ticker} className="flex justify-between">
          <span>{m.ticker}</span>
          <span
            className={
              (m.change_pct ?? 0) >= 0
                ? 'text-[var(--color-positive)]'
                : 'text-[var(--color-negative)]'
            }
          >
            {m.change_pct != null ? `${m.change_pct.toFixed(2)}%` : '—'}
          </span>
        </li>
      ))}
    </ul>
  )
}

function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="text-xs text-[var(--color-muted)]">{subtitle}</p>
    </div>
  )
}

function TwoColumnGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 md:grid-cols-2">{children}</div>
}

function PanelCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
      <h3 className="mb-3 text-sm font-medium">{title}</h3>
      {children}
    </div>
  )
}