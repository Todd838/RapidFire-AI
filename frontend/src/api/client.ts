const JSON_HEADERS: HeadersInit = {
  Accept: 'application/json',
  'Content-Type': 'application/json',
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal, headers: { Accept: 'application/json' } })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new ApiError(text || `HTTP ${res.status}`, res.status)
  }
  return res.json() as Promise<T>
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new ApiError(text || `HTTP ${res.status}`, res.status)
  }
  const ct = res.headers.get('content-type') ?? ''
  if (ct.includes('application/json')) {
    return res.json() as Promise<T>
  }
  return { message: await res.text() } as T
}

/** Coach ask: SSE stream when available, otherwise JSON body. */
export async function coachAsk(
  question: string,
  onChunk: (text: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/coach/ask', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ question, stream: true }),
    signal,
  })

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new ApiError(text || `HTTP ${res.status}`, res.status)
  }

  const ct = res.headers.get('content-type') ?? ''
  if (ct.includes('text/event-stream') && res.body) {
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n')
      buffer = parts.pop() ?? ''
      for (const line of parts) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6).trim()
          if (data === '[DONE]') continue
          try {
            const parsed = JSON.parse(data) as {
              delta?: string
              text?: string
              content?: string
            }
            const chunk =
              parsed.delta ?? parsed.text ?? parsed.content ?? (typeof parsed === 'string' ? parsed : '')
            if (chunk) onChunk(chunk)
          } catch {
            if (data) onChunk(data)
          }
        }
      }
    }
    return
  }

  const json = (await res.json()) as {
    text?: string
    answer?: string
    message?: string
    content?: string
  }
  onChunk(json.text ?? json.answer ?? json.message ?? json.content ?? 'No response from coach.')
}