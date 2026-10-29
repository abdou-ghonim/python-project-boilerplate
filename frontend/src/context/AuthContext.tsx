import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, type AuthConfig, type User } from '@/api'
import { getToken, setToken, setUnauthorizedHandler } from '@/api/client'

interface AuthState {
  user: User | null
  config: AuthConfig | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  loginWithProvider: () => void
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [loading, setLoading] = useState(true)

  // The OIDC callback returns the token in the URL fragment. Read it once and
  // strip it immediately: a fragment survives in history and in anything the
  // user pastes, and this one is a live session.
  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1))
    const token = fragment.get('access_token')
    if (token) {
      setToken(token)
      window.history.replaceState(null, '', window.location.pathname + window.location.search)
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))

    void (async () => {
      try {
        const authConfig = await api.authConfig()
        setConfig(authConfig)
        // 'none' means the backend treats every caller as authenticated; asking
        // for /me still returns the identity it will use.
        if (authConfig.provider === 'none' || getToken()) {
          setUser(await api.me())
        }
      } catch {
        setUser(null)
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const result = await api.login(username, password)
    setToken(result.access_token)
    setUser(await api.me())
  }, [])

  const loginWithProvider = useCallback(() => {
    // A full navigation, not fetch: the IdP redirect must happen in the browser.
    window.location.href = config?.login_url ?? '/api/auth/login'
  }, [config])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setToken(null)
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, config, loading, login, loginWithProvider, logout }),
    [user, config, loading, login, loginWithProvider, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
