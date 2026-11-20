import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  getPlatform,
  patchPlatform,
  setPlatform,
  type LocalPlatformState,
} from '../lib/localPlatform'

export function useWorkspaceId() {
  const { user } = useAuth()
  return user?.workspaceId ?? user?.id ?? 'guest'
}

export function useLocalPlatform() {
  const workspaceId = useWorkspaceId()
  const [state, setState] = useState<LocalPlatformState>(() =>
    getPlatform(workspaceId),
  )

  useEffect(() => {
    setState(getPlatform(workspaceId))
  }, [workspaceId])

  const refresh = useCallback(() => {
    setState(getPlatform(workspaceId))
  }, [workspaceId])

  const update = useCallback(
    (updater: (prev: LocalPlatformState) => LocalPlatformState) => {
      const next = patchPlatform(workspaceId, updater)
      setState(next)
      return next
    },
    [workspaceId],
  )

  const replace = useCallback(
    (next: LocalPlatformState) => {
      setPlatform(workspaceId, next)
      setState(next)
    },
    [workspaceId],
  )

  return { workspaceId, state, update, replace, refresh }
}