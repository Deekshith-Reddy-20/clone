import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useAuth } from './AuthContext'
import { newId } from '../lib/id'
import {
  loadWorkspace,
  saveWorkspace,
  type CallMode,
  type EmployeeDraft,
  type WorkspaceState,
} from '../lib/workspace'

type WorkspaceContextValue = {
  state: WorkspaceState
  addCredits: (amount: number) => void
  setOnboardingStep: (step: number) => void
  completeOnboardingStep: (index: number) => void
  createEmployeeFromBrief: (input: {
    brief: string
    language: string
    naturalSpoken: boolean
    mode: CallMode
    templateId?: string
  }) => EmployeeDraft
  publishEmployee: (employeeId: string) => void
  updateEmployeeDraft: (
    employeeId: string,
    patch: Partial<Pick<EmployeeDraft, 'brief' | 'language' | 'naturalSpoken' | 'mode'>>,
  ) => void
  employees: EmployeeDraft[]
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const workspaceId = user?.workspaceId ?? user?.id ?? 'guest'

  const [state, setState] = useState<WorkspaceState>(() =>
    loadWorkspace(workspaceId),
  )

  useEffect(() => {
    setState(loadWorkspace(workspaceId))
  }, [workspaceId])

  const update = useCallback(
    (updater: (prev: WorkspaceState) => WorkspaceState) => {
      setState((prev) => {
        const next = updater(prev)
        saveWorkspace(workspaceId, next)
        return next
      })
    },
    [workspaceId],
  )

  const addCredits = useCallback(
    (amount: number) => {
      update((prev) => ({ ...prev, credits: prev.credits + amount }))
    },
    [update],
  )

  const setOnboardingStep = useCallback(
    (step: number) => {
      update((prev) => ({ ...prev, onboardingStep: step }))
    },
    [update],
  )

  const completeOnboardingStep = useCallback(
    (index: number) => {
      update((prev) => {
        const completed = [...prev.onboardingCompleted]
        completed[index] = true
        const nextStep = Math.min(6, Math.max(prev.onboardingStep, index + 2))
        return {
          ...prev,
          onboardingCompleted: completed,
          onboardingStep: nextStep,
        }
      })
    },
    [update],
  )

  const updateEmployeeDraft = useCallback(
    (
      employeeId: string,
      patch: Partial<Pick<EmployeeDraft, 'brief' | 'language' | 'naturalSpoken' | 'mode'>>,
    ) => {
      update((prev) => ({
        ...prev,
        employees: prev.employees.map((e) =>
          e.id === employeeId ? { ...e, ...patch } : e,
        ),
      }))
    },
    [update],
  )

  const publishEmployee = useCallback(
    (employeeId: string) => {
      update((prev) => ({
        ...prev,
        employees: prev.employees.map((e) =>
          e.id === employeeId ? { ...e, status: 'published' as const } : e,
        ),
      }))
    },
    [update],
  )

  const createEmployeeFromBrief = useCallback(
    (input: {
      brief: string
      language: string
      naturalSpoken: boolean
      mode: CallMode
      templateId?: string
    }) => {
      const draft: EmployeeDraft = {
        id: newId(),
        brief: input.brief.trim(),
        language: input.language,
        naturalSpoken: input.naturalSpoken,
        mode: input.mode,
        templateId: input.templateId,
        createdAt: new Date().toISOString(),
      }
      update((prev) => {
        const completed = [...prev.onboardingCompleted]
        completed[1] = true
        return {
          ...prev,
          employees: [...prev.employees, draft],
          activeDraftId: draft.id,
          onboardingCompleted: completed,
          onboardingStep: Math.max(prev.onboardingStep, 3),
        }
      })
      return draft
    },
    [update],
  )

  const value = useMemo(
    () => ({
      state,
      addCredits,
      setOnboardingStep,
      completeOnboardingStep,
      createEmployeeFromBrief,
      publishEmployee,
      updateEmployeeDraft,
      employees: state.employees,
    }),
    [
      state,
      addCredits,
      setOnboardingStep,
      completeOnboardingStep,
      createEmployeeFromBrief,
      publishEmployee,
      updateEmployeeDraft,
    ],
  )

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) {
    throw new Error('useWorkspace must be used within WorkspaceProvider')
  }
  return ctx
}