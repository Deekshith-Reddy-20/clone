import { Outlet } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { WorkspaceProvider } from '../../context/WorkspaceContext'
import { AppSidebar } from './AppSidebar'
import { AppTopBar } from './AppTopBar'
import { OnboardingChecklist } from './OnboardingChecklist'

export function AppShell() {
  const { authReady, sessionError, retrySession } = useAuth()

  if (!authReady) {
    return (
      <div className="flex min-h-svh items-center justify-center bg-[#f4f6f5] text-sm text-karyuk-muted">
        Opening workspace…
      </div>
    )
  }

  if (sessionError) {
    return (
      <div className="flex min-h-svh flex-col items-center justify-center gap-4 bg-[#f4f6f5] px-6 text-center">
        <p className="max-w-md text-sm text-karyuk-ink">{sessionError}</p>
        <button
          type="button"
          onClick={retrySession}
          className="rounded-full bg-karyuk-green-dark px-5 py-2 text-sm font-medium text-white hover:bg-karyuk-green"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <WorkspaceProvider>
      <div className="flex min-h-svh bg-[#f4f6f5] text-karyuk-ink">
        <AppSidebar />
        <div className="flex min-h-svh min-w-0 flex-1 flex-col">
          <AppTopBar />
          <main className="relative flex-1 overflow-auto p-4 sm:p-6 lg:p-8">
            <Outlet />
          </main>
          <OnboardingChecklist />
        </div>
      </div>
    </WorkspaceProvider>
  )
}