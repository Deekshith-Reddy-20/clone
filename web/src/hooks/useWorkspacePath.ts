import { useAuth } from '../context/AuthContext'
import { getSession } from '../lib/auth'

export function useWorkspacePath() {
  const { user } = useAuth()
  const workspaceId = user?.workspaceId ?? getSession()?.workspaceId ?? null
  const prefix = workspaceId ? `/v1/workspaces/${workspaceId}` : null
  return { workspaceId, prefix }
}