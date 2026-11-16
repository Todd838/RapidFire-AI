import { useCallback, useState, type ReactNode } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiGet, apiPost } from '../api/client'
import type {
  AutoTradeLogEntry,
  AutoTraderStatus,
  EquityPoint,
  PerformanceSummary,
  ReadinessResponse,
} from '../types/api'
import { usePolling } from '../hooks/usePolling'
import { Skeleton, SkeletonLines } from './Skeleton'

interface TradeLogResponse {
  items?: AutoTradeLogEntry[]
  logs?: AutoTradeLogEntry[]
}

export function PerformanceDashboard() {
  const fetchStatus = useCallback(
    (signal: AbortSignal) => apiGet<AutoTraderStatus>('/api/auto-trader/status', signal),
    [],
  )
  const { data: status } = usePolling(fetchStatus, 60_000)

  const fetchPerf = useCallback(async (signal: AbortSignal) => {
    const [summary, equity, logs, policy] = await Promise.all([
      apiGet<PerformanceSummary>('/api/performance/summary', signal).catch(
        (): PerformanceSummary => ({}),
      ),
      apiGet<EquityPoint[] | { points: EquityPoint[] }>('/api/performance/equity', signal).catch(
        () => [],
      ),
      apiGet<TradeLogResponse | AutoTradeLogEntry[]>('/api/performance/trade-log', signal).catch(
        () => [],
      ),
      apiGet<{
        weights: Record<string, number>
        min_confidence: number
        version: number
        trades_learned: number
        last_lesson?: string | null
        note?: string
      }>('/api/agent/policy', signal).catch(() => null),
    ])
    const points = Array.isArray(equity) ? equity : (equity.points ?? [])
    const logItems = Array.isArray(logs) ? logs : (logs.items ?? logs.logs ?? [])
    return { summary, points, logItems, policy }
  }, [])

  const { data: perf, loading: perfLoading, refresh: refreshPerf } = usePolling(fetchPerf, 60_000)

  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null)
  const [readinessLoading, setReadinessLoading] = useState(false)
  const [reportMsg, setReportMsg] = useState<string | null>(null)
  const [scanBusy, setScanBusy] = useState(false)

  async function loadReadiness() {
    setReadinessLoading(true)
    try {
      const res = await apiGet<ReadinessResponse & { passed?: boolean; verdict?: string }>(
        '/api/performance/readiness',
      )
      setReadiness({
        ready: res.ready ?? res.passed ?? false,
        checks: res.checks ?? [],
      })
      if (res.verdict) setReportMsg(res.verdict)
    } catch {
      setReadiness({
        ready: false,
        checks: [
          { name: 'API route', passed: false, detail: 'GET /api/performance/readiness not available' },
        ],
      })
    } finally {
      setReadinessLoading(false)
    }
  }

  async function monthlyReport() {
    setReportMsg(null)
    try {
      const res = await apiPost<{ message?: string; report?: string; content?: string; topic?: string }>(
        '/api/performance/monthly-report',
      )
      setReportMsg(res.content ?? res.report ?? res.message ?? res.topic ?? 'Report saved')
    } catch (e) {
      setReportMsg(e instanceof Error ? e.message : 'Monthly report failed')
    }
  }

  async function runScan() {
    setScanBusy(true)
    try {
      await apiPost('/api/auto-trader/scan')
    } finally {
      setScanBusy(false)
    }
  }

  async function runAdapt() {
    setScanBusy(true)
    try {
      await apiPost('/api/agent/adapt')
      refreshPerf()
    } finally {
      setScanBusy(false)
    }
  }

  const modeLabel = status?.live_session_active ? 'LIVE' : 'PAPER'
  const summary: PerformanceSummary = perf?.summary ?? {}

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Performance</h2>
          <p className="text-xs text-[var(--color-muted)]">Equity, logs, auto-trader · educational metrics</p>
        </div>
        <span
          className={
            status?.live_session_active
              ? 'rounded border border-[var(--color-accent)] bg-[var(--color-accent)]/10 px-2 py-0.5 font-mono text-xs font-semibold text-[var(--color-accent)]'
              : 'rounded border border-[var(--color-border)] px-2 py-0.5 font-mono text-xs font-semibold text-[var(--color-muted)]'
          }
        >
          {modeLabel}
        </span>
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-medium">Auto-trader</h3>
            <p className="text-xs text-[var(--color-muted)]">
              {status?.dry_run ? 'Dry-run ON — no broker orders' : 'Dry-run OFF'}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void runScan()}
              disabled={scanBusy}
              className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs"
            >
              {scanBusy ? 'Scanning…' : 'Run scan'}
            </button>
            <button
              type="button"
              onClick={() => void runAdapt()}
              disabled={scanBusy}
              className="neon-btn rounded-md px-3 py-1.5 text-xs text-white disabled:opacity-50"
            >
              Learn now
            </button>
          </div>
        </div>
        {status?.note ? (
          <p className="mt-2 text-xs text-[var(--color-muted)]">{status.note}</p>
        ) : null}
      </div>

      {perf?.policy ? (
        <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 neon-border border">
          <h3 className="text-sm font-medium text-[var(--color-neon)]">Adaptive agent</h3>
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            v{perf.policy.version} · learned from {perf.policy.trades_learned} closes · BUY gate{' '}
            {perf.policy.min_confidence.toFixed(0)}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 font-mono text-xs sm:grid-cols-3">
            {Object.entries(perf.policy.weights).map(([k, v]) => (
              <div key={k} className="rounded border border-[var(--color-border)] px-2 py-1">
                <span className="text-[var(--color-muted)]">{k}</span>
                <span className="float-right text-[var(--color-neon)]">{v.toFixed(2)}</span>
              </div>
            ))}
          </div>
          {perf.policy.last_lesson ? (
            <p className="mt-3 text-sm leading-relaxed text-[var(--color-muted)]">
              {perf.policy.last_lesson}
            </p>
          ) : null}
          <p className="mt-2 text-xs text-[var(--color-muted)]">
            {perf.policy.note ?? 'Weights reshape signals only — RiskManager still gates every order.'}
          </p>
        </div>
      ) : null}

      {perfLoading && !perf ? (
        <Skeleton className="h-16 w-full" />
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 font-mono text-sm">
          <MiniStat label="Account" value={fmt(summary.account_value)} />
          <MiniStat label="Daily P&amp;L" value={fmt(summary.daily_pnl)} />
          <MiniStat label="Win rate" value={pct(summary.win_rate)} />
          <MiniStat label="Max DD" value={pct(summary.max_drawdown)} />
        </div>
      )}

      <button
        type="button"
        onClick={() => void loadReadiness()}
        className="text-xs text-[var(--color-accent)] hover:underline"
      >
        {readinessLoading ? 'Loading readiness…' : 'Load go-live readiness checklist'}
      </button>

      {readiness ? (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--color-border)] text-xs text-[var(--color-muted)]">
              <tr>
                <th className="px-3 py-2">Check</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Detail</th>
              </tr>
            </thead>
            <tbody>
              {readiness.checks.map((c) => (
                <tr key={c.name} className="border-b border-[var(--color-border)]/40">
                  <td className="px-3 py-2">{c.name}</td>
                  <td className="px-3 py-2">{c.passed ? 'Pass' : 'Fail'}</td>
                  <td className="px-3 py-2 text-[var(--color-muted)]">{c.detail ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <PanelCard title="Equity curve">
        {perfLoading && !perf ? (
          <Skeleton className="h-48 w-full" />
        ) : perf?.points.length ? (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={perf.points}>
              <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fill: '#b49ad4', fontSize: 11 }} />
              <YAxis tick={{ fill: '#b49ad4', fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-surface-raised)',
                  border: '1px solid var(--color-border)',
                }}
              />
              <Line
                type="monotone"
                dataKey="account_value"
                stroke="var(--color-accent)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-[var(--color-muted)]">
            No equity snapshots yet (GET /api/performance/equity).
          </p>
        )}
      </PanelCard>

      <PanelCard title="Auto-trader log">
        {perfLoading && !perf ? (
          <SkeletonLines />
        ) : perf?.logItems.length ? (
          <ul className="max-h-64 space-y-2 overflow-y-auto text-sm scrollbar-thin">
            {perf.logItems.map((row) => (
              <li key={row.id} className="border-b border-[var(--color-border)]/40 pb-2">
                <span className="font-mono text-xs text-[var(--color-muted)]">
                  {new Date(row.created_at).toLocaleString()}
                </span>
                <span className="mx-2 font-mono">{row.ticker ?? '—'}</span>
                <span className="font-medium">{row.action}</span>
                <p className="mt-1 text-[var(--color-muted)]">{row.reason}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-[var(--color-muted)]">No log entries (backend AutoTradeLog).</p>
        )}
      </PanelCard>

      <button
        type="button"
        onClick={() => void monthlyReport()}
        className="rounded-md border border-[var(--color-border)] px-4 py-2 text-sm hover:bg-[var(--color-surface-raised)]"
      >
        Generate monthly report
      </button>
      {reportMsg ? <p className="text-sm text-[var(--color-muted)]">{reportMsg}</p> : null}
    </section>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 py-2">
      <div className="text-xs text-[var(--color-muted)]" dangerouslySetInnerHTML={{ __html: label }} />
      <div>{value}</div>
    </div>
  )
}

function PanelCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
      <h3 className="mb-3 text-sm font-medium">{title}</h3>
      {children}
    </div>
  )
}

function fmt(n?: number | null): string {
  if (n == null) return '—'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function pct(n?: number | null): string {
  // Backend already returns percent units (e.g. 52.0 = 52%, 12.0 = 12% DD).
  if (n == null) return '—'
  return `${Number(n).toFixed(1)}%`
}