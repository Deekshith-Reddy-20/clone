/** In dev, empty base uses Vite proxy (/v1 → API). Set VITE_API_BASE_URL for production builds. */
export function getApiBase(): string {
  const fromEnv = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
  if (fromEnv) {
    const base = fromEnv.replace(/\/$/, '')
    if (typeof window !== 'undefined') {
      try {
        const target = new URL(base)
        const localTarget =
          target.hostname === 'localhost' || target.hostname === '127.0.0.1'
        const localPage =
          window.location.hostname === 'localhost' ||
          window.location.hostname === '127.0.0.1'
        // e.g. opening http://2.31.134.192:5173 must not call http://localhost:8000 on the laptop
        if (localTarget && !localPage) return ''
      } catch {
        /* use env as-is */
      }
    }
    return base
  }
  if (import.meta.env.DEV) return ''
  return ''
}

export function isApiEnabled() {
  return Boolean(getApiBase()) || import.meta.env.DEV
}

export function wsBaseFromApi(): string {
  const base = getApiBase()
  if (base) return base.replace(/^http/, 'ws')
  if (typeof window !== 'undefined') {
    return window.location.origin.replace(/^http/, 'ws')
  }
  return ''
}

function getStoredToken(): string | null {
  return localStorage.getItem('karyuk_access_token')
}

export function setAccessToken(token: string | null) {
  if (!token) {
    localStorage.removeItem('karyuk_access_token')
    return
  }
  localStorage.setItem('karyuk_access_token', token)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  if (!isApiEnabled()) {
    throw new ApiError(0, 'API base URL is not configured')
  }
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type') && init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getStoredToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const url = `${getApiBase()}${path}`
  const response = await fetch(url, { ...init, headers })
  const text = await response.text()
  let payload: { detail?: string; message?: string } | null = null
  if (text) {
    try {
      payload = JSON.parse(text) as { detail?: string; message?: string }
    } catch {
      payload = null
    }
  }
  if (!response.ok) {
    const message =
      (typeof payload?.detail === 'string' && payload.detail) ||
      payload?.message ||
      response.statusText ||
      'Request failed'
    throw new ApiError(response.status, message)
  }
  return (text ? JSON.parse(text) : {}) as T
}