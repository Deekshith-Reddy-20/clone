import { useCallback, useEffect, useState } from 'react'
import { useWorkspace } from '../context/WorkspaceContext'
import { useAuth } from '../context/AuthContext'
import { useLocalPlatform } from './useLocalPlatform'
import { useWorkspacePath } from './useWorkspacePath'
import { apiFetch, isApiEnabled } from '../lib/api/client'

export type CatalogEmployee = { id: string; label: string; status?: string }
export type CatalogLead = { id: string; label: string; phone_e164: string }

type ApiEmp = { id: string; status: string; draft: { brief: string } | null }
type ApiLead = { id: string; name?: string; phone_e164: string }

export function useWorkspaceCatalog() {
  const { authReady } = useAuth()
  const { prefix } = useWorkspacePath()
  const { state } = useWorkspace()
  const local = useLocalPlatform()
  const [apiEmployees, setApiEmployees] = useState<CatalogEmployee[]>([])
  const [apiLeads, setApiLeads] = useState<CatalogLead[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    if (!isApiEnabled() || !prefix) return
    setLoading(true)
    try {
      const [emps, leads] = await Promise.all([
        apiFetch<ApiEmp[]>(`${prefix}/employees`),
        apiFetch<ApiLead[]>(`${prefix}/leads`),
      ])
      setApiEmployees(
        emps.map((e) => ({
          id: e.id,
          label: (e.draft?.brief ?? 'Employee').slice(0, 56),
          status: e.status,
        })),
      )
      setApiLeads(
        leads.map((l) => ({
          id: l.id,
          label: l.name ? `${l.name} · ${l.phone_e164}` : l.phone_e164,
          phone_e164: l.phone_e164,
        })),
      )
    } catch {
      /* pages show their own errors */
    } finally {
      setLoading(false)
    }
  }, [prefix])

  useEffect(() => {
    if (!isApiEnabled() || !authReady || !prefix) return
    void refresh()
  }, [authReady, prefix, refresh])

  const employees: CatalogEmployee[] =
    isApiEnabled() && prefix
      ? apiEmployees
      : state.employees.map((e) => ({
          id: e.id,
          label: e.brief.slice(0, 56),
          status: e.status,
        }))

  const leads: CatalogLead[] =
    isApiEnabled() && prefix
      ? apiLeads
      : local.state.leads.map((l) => ({
          id: l.id,
          label: l.name ? `${l.name} · ${l.phone_e164}` : l.phone_e164,
          phone_e164: l.phone_e164,
        }))

  return { employees, leads, loading, refresh, prefix }
}