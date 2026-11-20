import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ONBOARDING_STEPS } from '../../data/employeeTemplates'
import { useWorkspace } from '../../context/WorkspaceContext'

export function OnboardingChecklist() {
  const { state, setOnboardingStep } = useWorkspace()
  const [open, setOpen] = useState(true)

  const currentIndex = Math.min(
    ONBOARDING_STEPS.length - 1,
    Math.max(0, state.onboardingStep - 1),
  )
  const current = ONBOARDING_STEPS[currentIndex]
  const done = state.onboardingCompleted[currentIndex]

  const actionHref =
    currentIndex === 1
      ? '/app'
      : currentIndex === 2
        ? '/app/numbers'
        : currentIndex === 3
          ? '/app/leads'
          : currentIndex === 4
            ? '/app/team'
            : '/app/billing'

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-40 rounded-full bg-karyuk-green-dark px-4 py-2 text-sm font-medium text-white shadow-lg"
      >
        Onboarding · Step {state.onboardingStep} of 6
      </button>
    )
  }

  return (
    <div
      className="fixed bottom-4 right-4 z-40 w-[min(100%,20rem)] rounded-2xl border border-karyuk-border bg-white p-4 shadow-xl"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-karyuk-muted">
          Step {currentIndex + 1} of {ONBOARDING_STEPS.length}
          {done ? ' · Completed' : ''}
        </p>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-xs text-karyuk-muted hover:text-karyuk-ink"
          aria-label="Minimize onboarding"
        >
          Minimize
        </button>
      </div>
      <p className="mt-1 font-semibold text-karyuk-ink">{current.label}</p>
      <p className="mt-1 text-xs text-karyuk-muted">{current.description}</p>
      <div className="mt-3 flex gap-2">
        <Link
          to={actionHref}
          className="flex-1 rounded-xl bg-karyuk-green-dark py-2 text-center text-sm font-medium text-white hover:bg-karyuk-green"
        >
          Do it
        </Link>
        <button
          type="button"
          onClick={() =>
            setOnboardingStep(Math.min(6, state.onboardingStep + 1))
          }
          className="rounded-xl border border-karyuk-border px-3 py-2 text-sm font-medium text-karyuk-muted hover:bg-karyuk-panel"
        >
          Later
        </button>
      </div>
    </div>
  )
}