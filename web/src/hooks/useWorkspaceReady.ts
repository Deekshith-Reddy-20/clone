import { useAuth } from '../context/AuthContext'
import { useWorkspacePath } from './useWorkspacePath'
import { isApiEnabled } from '../lib/api/client'

/** Dev uses Vite proxy + dev-session; `ready` when API calls can run. */
export function useWorkspaceReady() {
  const { authReady, user } = useAuth()
  const { prefix, workspaceId } = useWorkspacePath()
  const apiMode = isApiEnabled()
  const ready = !apiMode || (authReady && Boolean(prefix))
  const blockedReason =
    apiMode && authReady && !prefix
      ? 'Workspace API is not connected. Confirm the API on port 8010 is running, then refresh.'
      : null
  return { ready, prefix, workspaceId, authReady, apiMode, blockedReason, user }
}