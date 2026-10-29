import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'

/** One page for every auth provider: the backend says which UI to render, so
 *  switching from local passwords to SSO changes no frontend code. */
export default function Login() {
  const { user, config, loading, login, loginWithProvider } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (loading) return null
  if (user) return <Navigate to="/" replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-5">
      <div className="card w-full max-w-sm p-6">
        <h1 className="text-lg font-semibold">{config?.app_name ?? 'Sign in'}</h1>
        <p className="mt-1 mb-6 text-sm text-muted">
          {config?.login_style === 'redirect'
            ? 'Continue with your organisation account.'
            : 'Sign in to continue.'}
        </p>

        {config?.login_style === 'redirect' ? (
          <button onClick={loginWithProvider} className="btn-primary w-full">
            Sign in with SSO
          </button>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label htmlFor="username" className="mb-1 block text-sm">Username</label>
              <input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
                className="w-full rounded-lg border border-base bg-bg px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1 block text-sm">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                className="w-full rounded-lg border border-base bg-bg px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </div>

            {error && (
              <p role="alert" className="text-sm text-danger">{error}</p>
            )}

            <button type="submit" disabled={busy} className="btn-primary w-full">
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
