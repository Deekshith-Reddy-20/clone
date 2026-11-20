import { useCallback, useEffect, useState } from 'react'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { useWorkspace } from '../../context/WorkspaceContext'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { apiBlockedMessage, formatActionError } from '../../lib/actionFeedback'
import { pushAudit } from '../../lib/localPlatform'

const PACKS = [
  { credits: 50, inr: 499, label: 'Starter' },
  { credits: 150, inr: 1299, label: 'Growth' },
  { credits: 500, inr: 3999, label: 'Scale' },
]

export function BillingPage() {
  const { prefix } = useWorkspacePath()
  const { state, addCredits, completeOnboardingStep } = useWorkspace()
  const local = useLocalPlatform()
  const [credits, setCredits] = useState<number | null>(isApiEnabled() ? null : state.credits)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [txns, setTxns] = useState<{ entry_type: string; amount_paise: number }[]>([])

  const load = useCallback(() => {
    if (!isApiEnabled()) {
      setCredits(state.credits)
      setTxns(local.state.walletTransactions)
      return
    }
    if (!prefix) return
    void apiFetch<{ credits: number }>(`${prefix}/wallet`).then((w) => setCredits(w.credits))
    void apiFetch<{ entry_type: string; amount_paise: number }[]>(`${prefix}/wallet/transactions`).then(setTxns)
  }, [prefix, state.credits, local.state.walletTransactions])

  useEffect(() => {
    load()
  }, [load])

  const topUp = async (amount: number, inr: number) => {
    setError(null)
    try {
    if (!isApiEnabled()) {
      addCredits(amount)
      local.update((prev) => ({
        ...prev,
        walletTransactions: [
          { entry_type: 'top_up', amount_paise: inr * 100 },
          ...prev.walletTransactions,
        ],
      }))
      pushAudit(local.workspaceId, 'wallet.top_up', `${amount} credits`)
      setMessage(`Added ${amount} credits (local sandbox).`)
      completeOnboardingStep(5)
      load()
      return
    }
    if (!prefix) {
      setError(apiBlockedMessage())
      return
    }
      await apiFetch(`${prefix}/wallet/top-ups`, {
        method: 'POST',
        body: JSON.stringify({ credits: amount }),
      })
      setMessage(`Added ${amount} credits (sandbox).`)
      completeOnboardingStep(5)
      load()
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-semibold text-karyuk-ink">Credits & billing</h1>
      <p className="mt-2 text-karyuk-muted">
        INR wallet with ledger (M13).
        {!isApiEnabled() && <span className="text-karyuk-green-dark"> Local balance only.</span>}
      </p>

      <div className="mt-8 rounded-2xl border border-karyuk-border bg-white p-6">
        <p className="text-sm text-karyuk-muted">Available balance</p>
        <p className="mt-1 text-4xl font-semibold text-karyuk-ink">{credits ?? '—'}</p>
        <p className="text-sm text-karyuk-muted">credits</p>
      </div>

      {message && (
        <p className="mt-4 rounded-xl bg-karyuk-mint-soft px-4 py-3 text-sm text-karyuk-green-dark">{message}</p>
      )}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="mt-8 grid gap-4 sm:grid-cols-3">
        {PACKS.map((pack) => (
          <button
            key={pack.label}
            type="button"
            onClick={() => topUp(pack.credits, pack.inr)}
            className="rounded-2xl border border-karyuk-border bg-white p-4 text-left hover:border-karyuk-mint/50"
          >
            <p className="text-xs font-semibold uppercase text-karyuk-muted">{pack.label}</p>
            <p className="mt-2 text-xl font-semibold text-karyuk-ink">{pack.credits} credits</p>
            <p className="mt-1 text-sm text-karyuk-muted">₹{pack.inr} (sandbox)</p>
          </button>
        ))}
      </div>

      {txns.length > 0 && (
        <ul className="mt-8 space-y-1 text-xs text-karyuk-muted">
          {txns.slice(0, 10).map((t, i) => (
            <li key={i}>
              {t.entry_type}: ₹{(t.amount_paise / 100).toFixed(2)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}