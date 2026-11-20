import { isApiEnabled } from './api/client'

export function apiBlockedMessage(): string {
  return 'Workspace is still loading — wait a moment and try again.'
}

export function formatActionError(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong'
}

export function needPrefix(prefix: string | null): prefix is string {
  return Boolean(prefix) || !isApiEnabled()
}