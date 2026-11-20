/** User-facing labels — keep telephony backends invisible in the UI. */
export function providerLabel(provider: string | null | undefined): string {
  if (!provider) return ''
  const key = provider.toLowerCase()
  if (key === 'outpero') return 'voice'
  if (key === 'exotel') return 'phone'
  if (key === 'simulated') return 'simulated'
  if (key === 'browser_preview') return 'browser'
  return provider
}

export function leadSourceLabel(source: string | null | undefined): string {
  if (!source) return ''
  if (source === 'outpero' || source === 'outpero_test') return 'voice agent'
  return source
}
