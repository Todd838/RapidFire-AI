export interface QuoteResponse {
  ticker: string
  price: number
  change_pct?: number | null
  volume?: number | null
  currency?: string
  source?: string
  as_of: string
  error?: string | null
}

export interface SignalResponse {
  ticker: string
  action: string
  confidence: number
  entry_zone?: number | null
  stop_price?: number | null
  target_price?: number | null
  reasoning: string
  indicators?: Record<string, unknown>
  error?: string | null
}

export interface MoverItem {
  ticker: string
  price?: number | null
  change_pct?: number | null
  volume?: number | null
}

export interface MarketMoversResponse {
  gainers: MoverItem[]
  losers: MoverItem[]
  source?: string
  error?: string | null
}

export interface IpoItem {
  ticker: string
  name?: string | null
  exchange?: string | null
  ipo_date?: string | null
  notes?: string | null
}

export interface IpoListResponse {
  items: IpoItem[]
  source?: string
  error?: string | null
}

export interface PaperTrade {
  id: number
  ticker: string
  asset_type: string
  side: string
  quantity: number
  entry_price: number
  stop_price?: number | null
  target_price?: number | null
  exit_price?: number | null
  status: string
  rationale?: string | null
  opened_at: string
  closed_at?: string | null
  realized_pnl?: number | null
  is_live?: boolean
}

export interface PortfolioStats {
  open_positions: number
  closed_trades: number
  /** Backend field */
  realized_pnl?: number
  /** Legacy alias some UI used */
  total_realized_pnl?: number
  open_pnl?: number | null
  unrealized_pnl?: number | null
  /** Percent 0–100 from backend */
  win_rate?: number | null
  account_value?: number
  daily_pnl?: number
}

export interface AutoTraderStatus {
  dry_run: boolean
  live_trading_enabled_env: boolean
  live_session_active: boolean
  note: string
}

export interface AutoTradeLogEntry {
  id: number
  ticker?: string | null
  action: string
  reason: string
  created_at: string
}

export interface PerformanceSummary {
  account_value?: number
  daily_pnl?: number
  win_rate?: number | null
  profit_factor?: number | null
  sharpe?: number | null
  max_drawdown?: number | null
  closed_trades_total?: number
}

export interface EquityPoint {
  date: string
  account_value: number
  daily_pnl?: number
}

export interface ReadinessCheck {
  name: string
  passed: boolean
  detail?: string
}

export interface ReadinessResponse {
  ready: boolean
  checks: ReadinessCheck[]
}

export interface LessonLog {
  id: number
  topic: string
  content: string
  source?: string
  related_trade_id?: number | null
  created_at: string
}

export interface CoachJsonResponse {
  answer?: string
  message?: string
  content?: string
  error?: string
}