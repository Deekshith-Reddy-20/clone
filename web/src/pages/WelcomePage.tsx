import { Link } from 'react-router-dom'

export function WelcomePage() {
  return (
    <div className="bg-grid flex min-h-svh flex-col items-center justify-center px-6 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-karyuk-green-dark text-lg font-semibold text-white">
        K
      </span>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight text-karyuk-ink">KARYUK</h1>
      <p className="mt-2 max-w-sm text-sm text-karyuk-muted">
        AI front desk — calls, bookings, and your employee playbook.
      </p>
      <Link
        to="/app"
        className="mt-8 inline-flex items-center justify-center rounded-full bg-karyuk-green-dark px-8 py-3 text-sm font-medium text-white shadow-sm transition-colors hover:bg-karyuk-green"
      >
        Open workspace
      </Link>
    </div>
  )
}