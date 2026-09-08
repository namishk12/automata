export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`
    throw new Error(detail)
  }
  return body as T
}

export function parseVariables(text: string): Record<string, unknown> {
  if (!text.trim()) return {}
  try {
    const value = JSON.parse(text)
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('Variables must be a JSON object.')
    return value
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : 'Variables must be valid JSON.')
  }
}

export function formatDate(value?: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value))
}
