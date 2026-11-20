import { Bell, Moon, Search } from 'lucide-react'
import { useWorkspace } from '../../context/WorkspaceContext'

export function AppTopBar() {
  const { state } = useWorkspace()

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-karyuk-border bg-white px-4 sm:px-6">
      <div className="flex flex-1 items-center gap-2 rounded-xl border border-karyuk-border bg-karyuk-panel/50 px-3 py-2 text-sm text-karyuk-muted">
        <Search className="h-4 w-4 shrink-0" aria-hidden />
        <input
          type="search"
          placeholder="Search employees, leads, calls…"
          className="w-full min-w-0 bg-transparent text-sm text-karyuk-ink outline-none placeholder:text-karyuk-muted"
          aria-label="Search workspace"
        />
      </div>

      <p className="hidden whitespace-nowrap text-xs font-medium text-karyuk-muted sm:block">
        <span className="text-karyuk-ink">0</span> on calls ·{' '}
        <span className="text-karyuk-ink">0.0</span>/min
      </p>

      <button
        type="button"
        className="hidden rounded-lg border border-karyuk-border px-3 py-1.5 text-xs font-medium text-karyuk-muted hover:bg-karyuk-panel sm:inline"
      >
        Take the tour
      </button>

      <button
        type="button"
        className="rounded-lg border border-karyuk-border p-2 text-karyuk-muted hover:bg-karyuk-panel"
        aria-label="Toggle theme"
      >
        <Moon className="h-4 w-4" />
      </button>

      <button
        type="button"
        className="relative rounded-lg border border-karyuk-border p-2 text-karyuk-muted hover:bg-karyuk-panel"
        aria-label="Notifications"
      >
        <Bell className="h-4 w-4" />
        {state.onboardingStep <= 4 && (
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-karyuk-mint" />
        )}
      </button>
    </header>
  )
}