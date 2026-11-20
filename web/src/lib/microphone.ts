export type MicSupport = {
  ok: boolean
  reason: 'secure' | 'insecure' | 'unsupported' | 'denied'
  detail: string
  secureUrl?: string
}

/** Public HTTPS entry when the page is opened over plain HTTP (mic blocked by the browser). */
export function voiceSecureOrigin(): string {
  const fromEnv = (import.meta.env.VITE_VOICE_SECURE_ORIGIN as string | undefined)?.trim()
  if (fromEnv) return fromEnv.replace(/\/$/, '')
  if (typeof window === 'undefined') return ''
  const { hostname } = window.location
  const httpsPort = (import.meta.env.VITE_VOICE_HTTPS_PORT as string | undefined)?.trim() || '5174'
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return `https://${hostname}:${httpsPort}`
  }
  return `https://${hostname}:${httpsPort}`
}

/** Same page on the dev HTTPS listener (mic-safe), full path preserved. */
export function suggestedSecureVoiceUrl(): string | undefined {
  if (typeof window === 'undefined') return undefined
  if (window.isSecureContext) return undefined
  const { pathname, search, hash } = window.location
  const origin = voiceSecureOrigin()
  if (!origin) return undefined
  return `${origin}${pathname}${search}${hash}`
}

export function micSupportState(): MicSupport {
  if (typeof navigator === 'undefined') {
    return { ok: false, reason: 'unsupported', detail: 'Microphone is not available in this environment.' }
  }
  // Chrome hides mediaDevices entirely on plain HTTP — classify as insecure, not unsupported.
  if (!window.isSecureContext) {
    const secureUrl = suggestedSecureVoiceUrl()
    return {
      ok: false,
      reason: 'insecure',
      detail: secureUrl
        ? 'Microphone needs HTTPS. Use the secure link below (trust the certificate once), then start the voice test again.'
        : 'Microphone needs a secure page (HTTPS or localhost). SSH tunnel: ssh -L 5174:127.0.0.1:5174 <host> then open https://localhost:5174',
      secureUrl,
    }
  }
  const hasModern = Boolean(navigator.mediaDevices?.getUserMedia)
  const legacy =
    typeof (navigator as Navigator & { getUserMedia?: unknown }).getUserMedia === 'function' ||
    typeof (navigator as Navigator & { webkitGetUserMedia?: unknown }).webkitGetUserMedia === 'function'
  if (!hasModern && !legacy) {
    return {
      ok: false,
      reason: 'unsupported',
      detail: 'This browser does not expose the microphone API.',
    }
  }
  return { ok: true, reason: 'secure', detail: '' }
}

export async function acquireMicrophoneStream(): Promise<MediaStream> {
  const support = micSupportState()
  if (!support.ok) {
    throw new Error(support.detail || 'Microphone unavailable')
  }
  if (navigator.mediaDevices?.getUserMedia) {
    return navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    })
  }
  return new Promise((resolve, reject) => {
    const nav = navigator as Navigator & {
      getUserMedia?: (c: MediaStreamConstraints, ok: (s: MediaStream) => void, err: (e: Error) => void) => void
      webkitGetUserMedia?: (
        c: MediaStreamConstraints,
        ok: (s: MediaStream) => void,
        err: (e: Error) => void,
      ) => void
    }
    const legacy = nav.getUserMedia ?? nav.webkitGetUserMedia
    if (!legacy) {
      reject(new Error('Microphone API not available'))
      return
    }
    legacy.call(
      navigator,
      { audio: true, video: false },
      resolve,
      (e) => reject(e ?? new Error('Microphone permission denied')),
    )
  })
}