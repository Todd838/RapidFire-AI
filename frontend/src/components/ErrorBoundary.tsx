import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  label?: string
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`[ErrorBoundary${this.props.label ? `: ${this.props.label}` : ''}]`, error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-lg border border-[var(--color-danger)]/40 bg-[var(--color-surface-raised)] p-6">
          <p className="text-sm font-medium text-[var(--color-danger)]">Something went wrong</p>
          <p className="mt-2 font-mono text-xs text-[var(--color-muted)]">
            {this.state.error.message}
          </p>
          <button
            type="button"
            className="mt-4 text-sm text-[var(--color-accent)] hover:underline"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}