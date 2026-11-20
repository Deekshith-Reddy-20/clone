import { Outlet } from 'react-router-dom'

/** Workspace routes — no sign-in gate. */
export function ProtectedRoute() {
  return <Outlet />
}