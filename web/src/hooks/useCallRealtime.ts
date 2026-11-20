import { useEffect, useState } from 'react'
import { apiFetch, isApiEnabled } from '../lib/api/client'
import { getPlatform, resolveLocalCallOutcome } from '../lib/localPlatform'

export type CallSnapshot = {
  id: string
  outcome: string
  realtime: boolean
  transcript?: string | null
  summary?: string | null
  provider?: string | null
  livekit_room?: string | null
}

const TERMINAL = new Set(['completed', 'failed', 'canceled', 'busy', 'no_answer'])

export function useCallRealtime(
  callId: string | null,
  workspaceId: string,
  prefix: string | null,
) {
  const [call, setCall] = useState<CallSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!callId) {
      setCall(null)
      return
    }

    let active = true
    let timer: ReturnType<typeof setInterval> | null = null

    const pull = async () => {
      try {
        if (!isApiEnabled() || !prefix) {
          const raw = getPlatform(workspaceId).calls.find((c) => c.id === callId)
          if (!raw) return
          const row = resolveLocalCallOutcome(raw)
          const outcome = row.outcome ?? 'completed'
          const snap: CallSnapshot = {
            id: row.id,
            outcome,
            realtime: !TERMINAL.has(outcome),
            transcript: row.transcript,
            summary: row.summary,
            provider: row.provider ?? 'local',
          }
          if (active) setCall(snap)
          return
        }
        if (active && call?.provider === 'exotel') {
          try {
            await apiFetch(`${prefix}/calls/${callId}/sync-provider`, { method: 'POST' })
          } catch {
            /* optional */
          }
        }
        let snap = await apiFetch<CallSnapshot>(`${prefix}/calls/${callId}`)
        if (snap.provider === 'exotel' && snap.realtime) {
          await apiFetch(`${prefix}/calls/${callId}/sync-provider`, { method: 'POST' })
          snap = await apiFetch<CallSnapshot>(`${prefix}/calls/${callId}`)
        }
        if (active) {
          setCall(snap)
          setError(null)
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : 'Status unavailable')
      }
    }

    void pull()
    timer = setInterval(() => {
      void pull()
    }, 2000)

    return () => {
      active = false
      if (timer) clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- poll keyed by callId
  }, [callId, prefix, workspaceId])

  return { call, error, isLive: Boolean(call?.realtime) }
}