import { useCallback, useState } from 'react'
import { apiGet } from '../api/client'
import type { LessonLog } from '../types/api'
import { usePolling } from '../hooks/usePolling'
import { Skeleton, SkeletonLines } from './Skeleton'

interface JournalArticle {
  title: string
  url: string
  source: string
  summary: string
  kind: 'curated' | 'live' | string
}

interface JournalCategory {
  id: string
  label: string
  blurb: string
  curated: JournalArticle[]
  live: JournalArticle[]
}

interface ArticlesResponse {
  categories: JournalCategory[]
  disclaimer?: string
  feed_errors?: string[]
}

async function fetchLessons(signal: AbortSignal): Promise<LessonLog[]> {
  try {
    const res = await apiGet<LessonLog[] | { items?: LessonLog[] }>('/api/journal/lessons', signal)
    if (Array.isArray(res)) return res
    return res.items ?? []
  } catch {
    try {
      const res = await apiGet<LessonLog[]>('/api/portfolio/lessons', signal)
      return Array.isArray(res) ? res : []
    } catch {
      return []
    }
  }
}

export function Journal() {
  const fetchArticles = useCallback(
    (signal: AbortSignal) => apiGet<ArticlesResponse>('/api/journal/articles', signal),
    [],
  )
  const { data: articles, loading: articlesLoading, error: articlesError, refresh } =
    usePolling(fetchArticles, 5 * 60_000)

  const { data: lessons, loading: lessonsLoading } = usePolling(fetchLessons, 60_000)
  const [tab, setTab] = useState<string>('stock_market')

  const categories = articles?.categories ?? []
  const active = categories.find((c) => c.id === tab) ?? categories[0]

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Journal</h2>
          <p className="text-xs text-[var(--color-muted)]">
            Learn the market, AI in finance, and AI agents — curated guides + live headlines
          </p>
        </div>
        <button
          type="button"
          onClick={() => refresh()}
          className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs hover:text-[var(--color-neon)]"
        >
          Refresh feeds
        </button>
      </div>

      {articles?.disclaimer ? (
        <p className="text-xs text-[var(--color-muted)]">{articles.disclaimer}</p>
      ) : null}

      {articlesLoading && !articles ? <Skeleton className="h-40 w-full" /> : null}
      {articlesError ? (
        <p className="text-sm text-[var(--color-negative)]">Could not load articles: {articlesError}</p>
      ) : null}

      {categories.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {categories.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setTab(c.id)}
              className={`rounded-md px-3 py-2 text-sm transition ${
                (active?.id ?? tab) === c.id
                  ? 'neon-border border bg-[var(--color-surface-raised)] text-[var(--color-neon)]'
                  : 'border border-transparent text-[var(--color-muted)] hover:text-[var(--color-neon)]'
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
      ) : null}

      {active ? (
        <div className="space-y-5">
          <p className="text-sm text-[var(--color-muted)]">{active.blurb}</p>

          <ArticleGroup
            title="Start here (curated)"
            empty="No curated links."
            items={active.curated}
          />
          <ArticleGroup
            title="Recent headlines"
            empty="No live headlines right now — curated links above still work."
            items={active.live}
          />
        </div>
      ) : null}

      {articles?.feed_errors && articles.feed_errors.length > 0 ? (
        <p className="text-xs text-[var(--color-muted)]">
          Some live feeds unavailable: {articles.feed_errors.join(', ')}
        </p>
      ) : null}

      <div className="border-t border-[var(--color-border)] pt-6">
        <h3 className="mb-3 text-sm font-semibold">Your lesson log</h3>
        {lessonsLoading && !lessons ? <SkeletonLines count={3} /> : null}
        {!lessonsLoading && (lessons?.length ?? 0) === 0 ? (
          <p className="text-sm text-[var(--color-muted)]">
            No personal lessons yet — coach postmortems and monthly reports will show up here.
          </p>
        ) : null}
        <ul className="space-y-3">
          {(lessons ?? []).map((l) => (
            <li
              key={l.id}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h4 className="text-sm font-semibold">{l.topic}</h4>
                <span className="font-mono text-xs text-[var(--color-muted)]">
                  {new Date(l.created_at).toLocaleDateString()}
                  {l.source ? ` · ${l.source}` : ''}
                </span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-[var(--color-muted)] whitespace-pre-wrap">
                {l.content}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function ArticleGroup({
  title,
  items,
  empty,
}: {
  title: string
  items: JournalArticle[]
  empty: string
}) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium text-[var(--color-neon)]">{title}</h3>
      {!items.length ? (
        <p className="text-sm text-[var(--color-muted)]">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((a) => (
            <li
              key={`${a.kind}-${a.url}`}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 transition hover:border-[var(--color-accent)]"
            >
              <a
                href={a.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-semibold text-[var(--color-neon)] hover:underline"
              >
                {a.title}
              </a>
              <div className="mt-1 flex flex-wrap gap-2 font-mono text-xs text-[var(--color-muted)]">
                <span>{a.source}</span>
                <span>·</span>
                <span className="uppercase tracking-wide">{a.kind}</span>
              </div>
              {a.summary ? (
                <p className="mt-2 text-sm leading-relaxed text-[var(--color-muted)]">{a.summary}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
