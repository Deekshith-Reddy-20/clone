import { useMemo, useState } from 'react'

type Profile = {
  business?: { name?: string; type?: string; one_line_pitch?: string }
  location?: {
    full_address?: string
    area?: string
    city?: string
    state?: string
    landmarks?: string[]
  }
  contact?: { reception_phone?: string; whatsapp?: string; email?: string; hours?: string }
  offerings?: Array<{
    name?: string
    description?: string
    price_from?: number | null
    price_unit?: string
    price_notes?: string
  }>
  policies?: {
    check_in?: string
    check_out?: string
    cancellation?: string
  }
  faqs?: Array<{ q?: string; a?: string }>
  usps?: string[]
}

type Props = {
  value: Profile
  warnings?: string[]
  onChange: (p: Profile) => void
}

function emptyProfile(): Profile {
  return { business: {}, location: {}, contact: {}, offerings: [{}], policies: {}, faqs: [], usps: [] }
}

export function BusinessProfileEditor({ value, warnings = [], onChange }: Props) {
  const [advanced, setAdvanced] = useState(false)
  const p = useMemo(() => ({ ...emptyProfile(), ...value }), [value])
  const offering = p.offerings?.[0] || {}

  const patch = (next: Profile) => onChange({ ...p, ...next })

  return (
    <section className="space-y-3 rounded-xl border border-karyuk-border bg-white p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-karyuk-ink">Business profile</h2>
        <button
          type="button"
          className="text-xs text-violet-700 underline"
          onClick={() => setAdvanced((v) => !v)}
        >
          {advanced ? 'Form view' : 'Advanced JSON'}
        </button>
      </div>
      {warnings.length > 0 ? (
        <ul className="list-disc pl-4 text-xs text-amber-800">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      {advanced ? (
        <textarea
          className="min-h-48 w-full rounded-xl border border-karyuk-border font-mono text-[11px]"
          value={JSON.stringify(p, null, 2)}
          onChange={(e) => {
            try {
              onChange(JSON.parse(e.target.value) as Profile)
            } catch {
              /* wait for valid JSON */
            }
          }}
          spellCheck={false}
        />
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-xs">
            Business name
            <input
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={p.business?.name || ''}
              onChange={(e) => patch({ business: { ...p.business, name: e.target.value } })}
            />
          </label>
          <label className="text-xs">
            Type
            <select
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={p.business?.type || 'other'}
              onChange={(e) => patch({ business: { ...p.business, type: e.target.value } })}
            >
              <option value="resort">Resort</option>
              <option value="real_estate">Real estate</option>
              <option value="college">College</option>
              <option value="clinic">Clinic</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="col-span-2 text-xs">
            One-line pitch
            <input
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={p.business?.one_line_pitch || ''}
              onChange={(e) => patch({ business: { ...p.business, one_line_pitch: e.target.value } })}
            />
          </label>
          <label className="col-span-2 text-xs">
            Full address
            <input
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={p.location?.full_address || ''}
              onChange={(e) => patch({ location: { ...p.location, full_address: e.target.value } })}
            />
          </label>
          <label className="text-xs">
            Area
            <input
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={p.location?.area || ''}
              onChange={(e) => patch({ location: { ...p.location, area: e.target.value } })}
            />
          </label>
          <label className="text-xs">
            Reception phone
            <input
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={p.contact?.reception_phone || ''}
              onChange={(e) => patch({ contact: { ...p.contact, reception_phone: e.target.value } })}
            />
          </label>
          <label className="text-xs">
            Offering / room
            <input
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={offering.name || ''}
              onChange={(e) =>
                patch({ offerings: [{ ...offering, name: e.target.value }] })
              }
            />
          </label>
          <label className="text-xs">
            Price from (INR)
            <input
              type="number"
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={offering.price_from ?? ''}
              onChange={(e) =>
                patch({
                  offerings: [{ ...offering, price_from: Number(e.target.value) || null }],
                })
              }
            />
          </label>
          <label className="text-xs">
            Check-in
            <input
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={p.policies?.check_in || ''}
              onChange={(e) => patch({ policies: { ...p.policies, check_in: e.target.value } })}
            />
          </label>
          <label className="text-xs">
            Check-out
            <input
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={p.policies?.check_out || ''}
              onChange={(e) => patch({ policies: { ...p.policies, check_out: e.target.value } })}
            />
          </label>
          <label className="col-span-2 text-xs">
            USPs (comma-separated)
            <input
              className="mt-1 w-full rounded-lg border px-2 py-1 text-sm"
              value={(p.usps || []).join(', ')}
              onChange={(e) =>
                patch({ usps: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })
              }
            />
          </label>
        </div>
      )}
    </section>
  )
}