import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { bootstrapDevSession, hydrateSessionFromApi, type AuthUser } from '../lib/auth'

type AuthContextValue = {
  user: AuthUser | null
  authReady: boolean
  sessionError: string | null
  retrySession: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authReady, setAuthReady] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setAuthReady(false)
    void (async () => {
      const hydrated = await hydrateSessionFromApi()
      if (cancelled) return
      if (hydrated) {
        setUser(hydrated)
        setSessionError(null)
        setAuthReady(true)
        return
      }
      const boot = await bootstrapDevSession()
      if (cancelled) return
      setUser(boot)
      if (boot) {
        setSessionError(null)
      } else {
        setSessionError(
          'Could not connect to the workspace API (dev-session). Ensure API is on port 8010 and use this site URL — not localhost on your PC unless port-forwarded.',
        )
      }
      setAuthReady(true)
    })()
    return () => {
      cancelled = true
    }
  }, [attempt])

  const retrySession = useMemo(() => () => setAttempt((n) => n + 1), [])

  const value = useMemo(
    () => ({ user, authReady, sessionError, retrySession }),
    [user, authReady, sessionError, retrySession],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return ctx
}