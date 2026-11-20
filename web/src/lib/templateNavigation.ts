import type { NavigateFunction } from 'react-router-dom'
import { PENDING_TEMPLATE_STORAGE_KEY } from '../data/employeeTemplates'

export function goToHireWithTemplate(
  templateId: string,
  navigate: NavigateFunction,
  isSignedIn: boolean,
) {
  if (isSignedIn) {
    navigate(`/app?template=${encodeURIComponent(templateId)}`)
    return
  }
  window.sessionStorage.setItem(PENDING_TEMPLATE_STORAGE_KEY, templateId)
  navigate('/app')
}