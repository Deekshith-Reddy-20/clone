import { apiFetch, isApiEnabled, setAccessToken } from './api/client'
import { newId } from './id'

export type AuthUser = {
  id: string
  name: string
  email: string
  workspaceId: string
  workspaceName: string
}

const USERS_KEY = 'karyuk_users'
const SESSION_KEY = 'karyuk_session'

type StoredUser = AuthUser & { password: string }

type ApiTokenResponse = { access_token: string; expires_in: number }
type ApiMeResponse = {
  id: string
  email: string
  display_name: string
  workspaces: { id: string; name: string; role: string }[]
}

function readUsers(): StoredUser[] {
  try {
    const raw = localStorage.getItem(USERS_KEY)
    return raw ? (JSON.parse(raw) as StoredUser[]) : []
  } catch {
    return []
  }
}

function writeUsers(users: StoredUser[]) {
  localStorage.setItem(USERS_KEY, JSON.stringify(users))
}

function meToAuthUser(me: ApiMeResponse): AuthUser {
  const ws = me.workspaces[0]
  if (!ws) {
    throw new Error('No workspace on account')
  }
  return {
    id: me.id,
    name: me.display_name,
    email: me.email,
    workspaceId: ws.id,
    workspaceName: ws.name,
  }
}

export function getSession(): AuthUser | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function setSession(user: AuthUser | null) {
  if (!user) {
    localStorage.removeItem(SESSION_KEY)
    return
  }
  localStorage.setItem(SESSION_KEY, JSON.stringify(user))
}

async function refreshMeSession(): Promise<AuthUser> {
  const me = await apiFetch<ApiMeResponse>('/v1/me')
  const user = meToAuthUser(me)
  setSession(user)
  return user
}

export async function registerUser(input: {
  name: string
  email: string
  password: string
  workspaceName: string
}): Promise<{ user?: AuthUser; error?: string }> {
  if (isApiEnabled()) {
    try {
      const tokenRes = await apiFetch<ApiTokenResponse>('/v1/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          name: input.name,
          email: input.email,
          password: input.password,
          workspace_name: input.workspaceName,
        }),
      })
      setAccessToken(tokenRes.access_token)
      const user = await refreshMeSession()
      return { user }
    } catch (e) {
      return { error: e instanceof Error ? e.message : 'Registration failed' }
    }
  }

  const email = input.email.trim().toLowerCase()
  if (!email.includes('@')) {
    return { error: 'Enter a valid email address.' }
  }
  if (input.password.length < 8) {
    return { error: 'Password must be at least 8 characters.' }
  }
  if (!input.name.trim() || !input.workspaceName.trim()) {
    return { error: 'Name and workspace are required.' }
  }

  const users = readUsers()
  if (users.some((u) => u.email === email)) {
    return { error: 'An account with this email already exists. Sign in instead.' }
  }

  const user: StoredUser = {
    id: newId(),
    name: input.name.trim(),
    email,
    workspaceName: input.workspaceName.trim(),
    workspaceId: newId(),
    password: input.password,
  }
  writeUsers([...users, user])
  const session: AuthUser = {
    id: user.id,
    name: user.name,
    email: user.email,
    workspaceName: user.workspaceName,
    workspaceId: user.workspaceId,
  }
  setSession(session)
  return { user: session }
}

export async function signInUser(
  email: string,
  password: string,
): Promise<{ user?: AuthUser; error?: string }> {
  if (isApiEnabled()) {
    try {
      const tokenRes = await apiFetch<ApiTokenResponse>('/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      setAccessToken(tokenRes.access_token)
      const user = await refreshMeSession()
      return { user }
    } catch (e) {
      return { error: e instanceof Error ? e.message : 'Sign in failed' }
    }
  }

  const normalized = email.trim().toLowerCase()
  const match = readUsers().find(
    (u) => u.email === normalized && u.password === password,
  )
  if (!match) {
    return { error: 'Email or password is incorrect.' }
  }
  const session: AuthUser = {
    id: match.id,
    name: match.name,
    email: match.email,
    workspaceName: match.workspaceName,
    workspaceId: match.workspaceId,
  }
  setSession(session)
  return { user: session }
}

export function signOut() {
  setAccessToken(null)
  setSession(null)
}

const DEV_AUTO_EMAIL = 'dev@example.com'

export async function bootstrapDevSession(): Promise<AuthUser | null> {
  if (isApiEnabled()) {
    try {
      const tokenRes = await apiFetch<ApiTokenResponse>('/v1/auth/dev-session', {
        method: 'POST',
      })
      setAccessToken(tokenRes.access_token)
      return await refreshMeSession()
    } catch (e) {
      signOut()
      if (import.meta.env.DEV && e instanceof Error) {
        console.warn('[auth] dev-session failed:', e.message)
      }
      return null
    }
  }
  const session: AuthUser = {
    id: 'dev-local',
    name: 'Dev',
    email: DEV_AUTO_EMAIL,
    workspaceId: 'b96e99eb-2bda-4bdd-9aa9-ba9bc43762e3',
    workspaceName: 'Dev Workspace',
  }
  setSession(session)
  return session
}

export async function hydrateSessionFromApi(): Promise<AuthUser | null> {
  if (!isApiEnabled() || !localStorage.getItem('karyuk_access_token')) {
    return getSession()
  }
  try {
    return await refreshMeSession()
  } catch {
    signOut()
    return null
  }
}

/** Re-fetch workspace id from API when local session is stale (common when API was enabled after local sign-up). */
export async function syncSessionWithApi(): Promise<AuthUser | null> {
  if (!isApiEnabled()) return getSession()
  const token = localStorage.getItem('karyuk_access_token')
  if (!token) return null
  try {
    return await refreshMeSession()
  } catch {
    return null
  }
}