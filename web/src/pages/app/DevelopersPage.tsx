import { useEffect, useState } from 'react'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { apiBlockedMessage, formatActionError } from '../../lib/actionFeedback'
import { pushAudit } from '../../lib/localPlatform'

function apiBaseLabel() {
  const fromEnv = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
  if (fromEnv) return fromEnv.replace(/\/$/, '')
  if (import.meta.env.DEV && typeof window !== 'undefined') return window.location.origin
  return '(configure VITE_API_BASE_URL)'
}

export function DevelopersPage() {
  const { prefix } = useWorkspacePath()
  const local = useLocalPlatform()
  const [ingress, setIngress] = useState<{ integration_id: string; endpoint: string; secret: string } | null>(null)
  const [webhookUrl, setWebhookUrl] = useState('https://webhook.site/test')
  const [integrations, setIntegrations] = useState<{ integration_type: string; status: string }[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isApiEnabled()) {
      setIngress({
        integration_id: 'local',
        endpoint: `/v1/workspaces/${local.workspaceId}/ingress/leads`,
        secret: local.state.ingressSecret,
      })
      setIntegrations(local.state.integrations)
      return
    }
    if (!prefix) return
    void apiFetch<{ integration_id: string; endpoint: string; secret: string }>(`${prefix}/developers/ingress`).then(setIngress)
    void apiFetch<{ integration_type: string; status: string }[]>(`${prefix}/integrations`).then(setIntegrations)
  }, [prefix, local.workspaceId, local.state.ingressSecret, local.state.integrations])

  const addWebhook = async () => {
    setError(null)
    setMsg(null)
    try {
    if (!isApiEnabled()) {
      local.update((prev) => ({ ...prev, webhookUrl }))
      pushAudit(local.workspaceId, 'webhook.saved', webhookUrl)
      setMsg('Webhook saved (local).')
      return
    }
    if (!prefix) {
      setError(apiBlockedMessage())
      return
    }
    await apiFetch(`${prefix}/webhook-endpoints`, {
      method: 'POST',
      body: JSON.stringify({ url: webhookUrl, events: ['call.finalized.v1'] }),
    })
    setMsg('Webhook endpoint saved.')
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  const connect = async (type: string) => {
    setError(null)
    try {
    if (!isApiEnabled()) {
      local.update((prev) => ({
        ...prev,
        integrations: [
          ...prev.integrations.filter((i) => i.integration_type !== type),
          { integration_type: type, status: 'connected' },
        ],
      }))
      const next = pushAudit(local.workspaceId, 'integration.connected', type)
      setIntegrations(next.integrations)
      setMsg(`Connected ${type} (local).`)
      return
    }
    if (!prefix) {
      setError(apiBlockedMessage())
      return
    }
    await apiFetch(`${prefix}/integrations/${type}/connect`, { method: 'POST' })
    void apiFetch<{ integration_type: string; status: string }[]>(`${prefix}/integrations`).then(setIntegrations)
    setMsg(`Connected ${type}.`)
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <h1 className="text-2xl font-semibold">Developers</h1>
      {msg && <p className="text-sm text-karyuk-green-dark">{msg}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!isApiEnabled() && (
        <p className="text-xs text-karyuk-muted">Local preview — wire API later with VITE_API_BASE_URL.</p>
      )}
      {ingress && (
        <pre className="overflow-x-auto rounded-2xl border bg-karyuk-panel p-4 text-xs">
          {`POST ${isApiEnabled() ? apiBaseLabel() : '(future API)'}${ingress.endpoint}\nAuthorization: Bearer ${ingress.secret}\nBody: { "phone": "9876543210", "employee_id": "<uuid>" }`}
        </pre>
      )}
      <section className="space-y-2 rounded-2xl border bg-white p-4">
        <h2 className="font-medium">Post-call webhooks (M12)</h2>
        <input className="w-full rounded border px-2 py-1 text-sm" value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} />
        <button type="button" onClick={addWebhook} className="rounded-full border px-4 py-2 text-sm">
          Save endpoint
        </button>
        {!isApiEnabled() && local.state.webhookUrl && (
          <p className="text-xs text-karyuk-green-dark">Saved: {local.state.webhookUrl}</p>
        )}
      </section>
      <section className="space-y-2">
        <h2 className="font-medium">Integrations (M11)</h2>
        {['calendar', 'sheets', 'whatsapp', 'custom'].map((t) => (
          <button key={t} type="button" onClick={() => connect(t)} className="mr-2 rounded-full border px-3 py-1 text-sm capitalize">
            Connect {t}
          </button>
        ))}
        <ul className="text-sm text-karyuk-muted">
          {integrations.map((i, idx) => (
            <li key={idx}>
              {i.integration_type}: {i.status}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}