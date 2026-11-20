import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { useWorkspace } from '../../context/WorkspaceContext'
import { apiFetch, isApiEnabled } from '../../lib/api/client'

export function CreditsWidget({ compact = false }: { compact?: boolean }) {
  const { prefix } = useWorkspacePath()
  const { state } = useWorkspace()
  const [credits, setCredits] = useState(state.credits)

  useEffect(() => {
    if (!prefix || !isApiEnabled()) {
      setCredits(state.credits)
      return
    }
    void apiFetch<{ credits: number }>(`${prefix}/wallet`).then((w) => setCredits(w.credits))
  }, [prefix, state.credits])

  const minutesLow = Math.floor(credits / 7)
  const minutesHigh = Math.floor(credits / 5)

  if (!compact) {
    return null
  }

  return (
    <div className="rounded-2xl border border-karyuk-border bg-karyuk-panel/80 p-3">
      <p className="text-xs font-medium text-karyuk-muted">Credits</p>
      <p className="mt-0.5 text-lg font-semibold text-karyuk-ink">{credits}</p>
      <p className="text-[10px] text-karyuk-muted">
        ≈ {minutesLow}–{minutesHigh} min of calls
      </p>
      <Link
        to="/app/billing"
        className="mt-2 block w-full rounded-xl bg-karyuk-green-dark py-2 text-center text-xs font-medium text-white hover:bg-karyuk-green"
      >
        + Add credits
      </Link>
    </div>
  )
}