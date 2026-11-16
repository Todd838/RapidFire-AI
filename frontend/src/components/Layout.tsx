import { useState } from 'react'
import { apiPost } from '../api/client'
import { MarketTicker } from './MarketTicker'
import { ErrorBoundary } from './ErrorBoundary'
import { CoachPanel } from './CoachPanel'
import { SignalFeed } from './SignalFeed'
import { DiscoverPanel } from './DiscoverPanel'
import { Portfolio } from './Portfolio'
import { LearnPanel } from './LearnPanel'
import { PerformanceDashboard } from './PerformanceDashboard'
import { Journal } from './Journal'

export type TabId =
  | 'coach'
  | 'signals'
  | 'discover'
  | 'portfolio'
  | 'learn'
  | 'performance'
  | 'journal'

const TABS: { id: TabId; label: string }[] = [
  { id: 'coach', label: 'Coach' },
  { id: 'signals', label: 'Signals' },
  { id: 'discover', label: 'Discover' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'learn', label: 'Learn' },
  { id: 'performance', label: 'Performance' },
  { id: 'journal', label: 'Journal' },
]

export function Layout() {
  const [tab, setTab] = useState<TabId>('coach')
  const [emergencyBusy, setEmergencyBusy] = useState(false)
  const [emergencyMsg, setEmergencyMsg] = useState<string | null>(null)

  async function emergencyCloseAll() {
    if (
      !window.confirm(
        'Emergency Close All will flatten open positions and pause auto-trading. Continue?',
      )
    ) {
      return
    }
    setEmergencyBusy(true)
    setEmergencyMsg(null)
    try {
      const res = await apiPost<{ message?: string; closed?: number }>('/api/auto-trader/emergency-close')
      setEmergencyMsg(
        typeof res === 'object' && res && 'message' in res
          ? String((res as { message?: string }).message ?? 'Emergency close sent.')
          : 'Emergency close sent.',
      )
    } catch (e) {
      setEmergencyMsg(e instanceof Error ? e.message : 'Emergency close failed')
    } finally {
      setEmergencyBusy(false)
    }
  }

  function renderTab() {
    switch (tab) {
      case 'coach':
        return <CoachPanel />
      case 'signals':
        return <SignalFeed />
      case 'discover':
        return <DiscoverPanel />
      case 'portfolio':
        return <Portfolio />
      case 'learn':
        return <LearnPanel />
      case 'performance':
        return <PerformanceDashboard />
      case 'journal':
        return <Journal />
      default:
        return null
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <h1 className="neon-text text-lg font-semibold tracking-tight">RapidFire AI</h1>
            <p className="text-xs text-[var(--color-muted)]">Educational paper-first trading coach</p>
          </div>
          <button
            type="button"
            onClick={() => void emergencyCloseAll()}
            disabled={emergencyBusy}
            className="rounded-md bg-[var(--color-danger)] px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-red-700 disabled:opacity-60"
          >
            {emergencyBusy ? 'Closing…' : 'Emergency Close All'}
          </button>
        </div>
        {emergencyMsg ? (
          <p className="mx-auto max-w-7xl px-4 pb-2 text-xs text-[var(--color-muted)]">{emergencyMsg}</p>
        ) : null}
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-2 scrollbar-thin">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`shrink-0 rounded-md px-3 py-2 text-sm transition ${
                tab === t.id
                  ? 'neon-border border bg-[var(--color-surface-raised)] text-[var(--color-neon)]'
                  : 'text-[var(--color-muted)] hover:bg-[var(--color-surface-raised)]/60 hover:text-[var(--color-neon)]'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <MarketTicker />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <ErrorBoundary label={tab}>
          <div key={tab}>{renderTab()}</div>
        </ErrorBoundary>
      </main>

      <footer className="border-t border-[var(--color-border)] px-4 py-3 text-center text-xs text-[var(--color-muted)]">
        Not financial advice. Live trading is gated and off by default.
      </footer>
    </div>
  )
}