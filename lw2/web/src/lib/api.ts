export type Ev = { id: number; ts: number; type: string; [k: string]: any }

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers || {}) },
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`)
  return body as T
}

export const post = <T = any>(path: string, data?: unknown) =>
  api<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) })

export const short = (h?: string, a = 6, b = 4) =>
  !h ? '' : h.length <= a + b + 2 ? h : `${h.slice(0, a + 2)}…${h.slice(-b)}`

export const usdc = (minor?: number) =>
  minor == null ? '—' : (minor / 1e6).toLocaleString('en-US', { maximumFractionDigits: 2 }) + ' USDC'

export const secs = (ms?: number) => (ms == null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`)
