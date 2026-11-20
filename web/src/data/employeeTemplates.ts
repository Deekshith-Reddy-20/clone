import type { CallMode } from '../lib/workspace'

export const LANGUAGES = [
  'English',
  'Telugu',
  'Hindi',
  'Tamil',
  'Kannada',
  'Malayalam',
  'Marathi',
] as const

export type TemplateCard = {
  id: string
  industry: string
  title: string
  brief: string
  defaultMode?: CallMode
  defaultLanguage?: string
}

export const PENDING_TEMPLATE_STORAGE_KEY = 'karyuk_pending_template_id'

export const EMPLOYEE_TEMPLATES: TemplateCard[] = [
  {
    id: 'bfsi',
    industry: 'BFSI',
    title: 'Loan & insurance leads',
    brief:
      'Call new loan and insurance enquiries, qualify intent, and schedule a callback with an advisor.',
  },
  {
    id: 'real-estate',
    industry: 'Real Estate',
    title: 'Site visit booking',
    brief: 'Call property leads, confirm interest, and book a site visit in the right timezone.',
    defaultMode: 'bulk',
  },
  {
    id: 'coaching',
    industry: 'Coaching & Tuition',
    title: 'Admission enquiries',
    brief: 'Answer admission questions, explain batches, and book a demo class slot.',
    defaultMode: 'instant',
  },
  {
    id: 'hospital',
    industry: 'Hospital & Clinic',
    title: 'Appointment scheduling',
    brief: 'Confirm patient details and schedule or reschedule clinic appointments.',
    defaultMode: 'inbound',
  },
  {
    id: 'dealership',
    industry: 'Car & Bike Dealership',
    title: 'Test drive booking',
    brief: 'Call everyone who asks for a test drive and fix a slot at the nearest branch.',
  },
  {
    id: 'interiors',
    industry: 'Interiors & Construction',
    title: 'Site measurement visit',
    brief: 'Follow up on quotation requests and schedule a site measurement visit.',
    defaultMode: 'bulk',
  },
]

export function getTemplateById(id: string): TemplateCard | undefined {
  return EMPLOYEE_TEMPLATES.find((t) => t.id === id)
}

export function templateDefaults(t: TemplateCard) {
  return {
    brief: t.brief,
    templateId: t.id,
    mode: t.defaultMode ?? ('instant' as CallMode),
    language: t.defaultLanguage ?? 'English',
    naturalSpoken: true,
  }
}

/** Landing “Industries” cards → hire templates */
export const INDUSTRY_TEMPLATE_MAP: { title: string; detail: string; templateId: string }[] = [
  {
    title: 'Resorts & hotels',
    detail: 'Room availability, check-in questions, and booking handoffs.',
    templateId: 'real-estate',
  },
  {
    title: 'Clinics & hospitals',
    detail: 'Appointment scheduling, follow-ups, and after-hours routing.',
    templateId: 'hospital',
  },
  {
    title: 'Consultation businesses',
    detail: 'Lead qualification, slot booking, and team escalation.',
    templateId: 'coaching',
  },
  {
    title: 'Real estate & automotive',
    detail: 'Site visits, test drives, and callback scheduling.',
    templateId: 'dealership',
  },
]

export const ONBOARDING_STEPS = [
  { label: 'Create workspace', description: 'Account and team space ready.' },
  { label: 'Hire your first employee', description: 'Brief, language, and call mode.' },
  { label: 'Connect a phone number', description: 'Assign routing for calls.' },
  { label: 'Import or add leads', description: 'Eligible contacts for outreach.' },
  { label: 'Run a test call', description: 'Verify voice and outcome.' },
  { label: 'Add credits', description: 'Top up for production traffic.' },
] as const