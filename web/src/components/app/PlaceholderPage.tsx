import { Link } from 'react-router-dom'

export function PlaceholderPage({
  title,
  description,
  nextHref,
  nextLabel,
}: {
  title: string
  description: string
  nextHref?: string
  nextLabel?: string
}) {
  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-semibold text-karyuk-ink">{title}</h1>
      <p className="mt-3 text-karyuk-muted">{description}</p>
      <p className="mt-4 rounded-xl border border-dashed border-karyuk-border bg-white px-4 py-6 text-sm text-karyuk-muted">
        This module connects to the FastAPI backend in the full MVP. Navigation and
        layout are ready so we can wire APIs next.
      </p>
      {nextHref && (
        <Link
          to={nextHref}
          className="mt-6 inline-flex rounded-full bg-karyuk-green-dark px-5 py-2.5 text-sm font-medium text-white hover:bg-karyuk-green"
        >
          {nextLabel ?? 'Continue setup'}
        </Link>
      )}
    </div>
  )
}