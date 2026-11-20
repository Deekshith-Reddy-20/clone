export type CallMode = 'instant' | 'bulk' | 'inbound'

export type EmployeeDraft = {
  id: string
  brief: string
  language: string
  naturalSpoken: boolean
  mode: CallMode
  templateId?: string
  createdAt: string
  status?: 'draft' | 'published'
}

export type WorkspaceState = {
  credits: number
  onboardingStep: number
  onboardingCompleted: boolean[]
  employees: EmployeeDraft[]
  activeDraftId: string | null
}

const keyFor = (workspaceId: string) => `karyuk_workspace_${workspaceId}`

const defaultState = (): WorkspaceState => ({
  credits: 50,
  onboardingStep: 2,
  onboardingCompleted: [true, false, false, false, false, false],
  employees: [],
  activeDraftId: null,
})

export function loadWorkspace(workspaceId: string): WorkspaceState {
  try {
    const raw = localStorage.getItem(keyFor(workspaceId))
    if (!raw) return defaultState()
    return { ...defaultState(), ...(JSON.parse(raw) as WorkspaceState) }
  } catch {
    return defaultState()
  }
}

export function saveWorkspace(workspaceId: string, state: WorkspaceState) {
  localStorage.setItem(keyFor(workspaceId), JSON.stringify(state))
}