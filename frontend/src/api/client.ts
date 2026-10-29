import axios, { AxiosError } from 'axios'

/**
 * The single axios instance. Every request carries the bearer token, and a 401
 * clears the session exactly once — so an expired token logs the user out
 * rather than leaving the UI retrying against a dead session.
 */
const TOKEN_KEY = 'auth.token'

export const client = axios.create({
  baseURL: '/api',
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    // Private mode and blocked site data both throw here; an unauthenticated
    // app is a better outcome than a blank screen.
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable — the token stays in memory for this page only */
  }
}

client.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

type Unauthorized = () => void
let onUnauthorized: Unauthorized = () => {}

export function setUnauthorizedHandler(handler: Unauthorized): void {
  onUnauthorized = handler
}

client.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ error?: string }>) => {
    if (error.response?.status === 401) {
      setToken(null)
      onUnauthorized()
    }
    // Surface the API's own message; the error layer always sends {error, status}.
    const message = error.response?.data?.error ?? error.message ?? 'Request failed'
    return Promise.reject(new Error(message))
  },
)
