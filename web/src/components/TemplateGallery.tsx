import { EMPLOYEE_TEMPLATES, type TemplateCard } from '../data/employeeTemplates'

type Props = {
  selectedId?: string | null
  onSelect: (template: TemplateCard) => void
  compact?: boolean
}

export function TemplateGallery({ selectedId, onSelect, compact = false }: Props) {
  return (
    <ul
      id="employee-templates"
      className={
        compact
          ? 'mt-4 grid gap-2 sm:grid-cols-2'
          : 'mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3'
      }
    >
      {EMPLOYEE_TEMPLATES.map((t) => {
        const active = selectedId === t.id
        return (
          <li key={t.id}>
            <button
              type="button"
              onClick={() => onSelect(t)}
              className={`flex h-full w-full flex-col rounded-2xl border p-4 text-left shadow-sm transition-all ${
                active
                  ? 'border-violet-500 bg-violet-50 ring-2 ring-violet-400/40'
                  : 'border-karyuk-border bg-white hover:border-karyuk-mint/50 hover:shadow-md'
              }`}
            >
              <span className="text-[10px] font-bold uppercase tracking-wider text-karyuk-muted">
                {t.industry}
              </span>
              <span className="mt-2 font-semibold text-karyuk-ink">{t.title}</span>
              <span className="mt-2 line-clamp-2 text-xs text-karyuk-muted">{t.brief}</span>
              {active && (
                <span className="mt-3 text-[10px] font-semibold uppercase text-violet-700">
                  Selected
                </span>
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}