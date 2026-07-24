# Prompt Lovable — Auth + Login + JWT

## 1. AuthContext

Dans `src/lib/auth.tsx` :

```tsx
import { createContext, useContext, useEffect, useState } from 'react'
import { supabase } from '@/lib/supabase-client'

interface AuthState {
  user: { id: string; email: string; role: string } | null
  session: any
  loading: boolean
}

const AuthContext = createContext<AuthState>({ user: null, session: null, loading: true })

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ user: null, session: null, loading: true })

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setState({
        user: session?.user ? {
          id: session.user.id,
          email: session.user.email ?? '',
          role: 'user',
        } : null,
        session,
        loading: false,
      })
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setState({
        user: session?.user ? {
          id: session.user.id,
          email: session.user.email ?? '',
          role: 'user',
        } : null,
        session,
        loading: false,
      })
    })

    return () => subscription.unsubscribe()
  }, [])

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
```

## 2. LoginPage

```tsx
import { useState } from 'react'
import { supabase } from '@/lib/supabase-client'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) setError(error.message)
    setLoading(false)
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={handleLogin} className="bg-white p-8 rounded-lg shadow-md w-96">
        <h1 className="text-2xl font-bold mb-6">Connexion Plaudia</h1>
        {error && <p className="text-red-500 mb-4">{error}</p>}
        <input
          type="email" placeholder="Email"
          value={email} onChange={e => setEmail(e.target.value)}
          className="w-full p-2 border rounded mb-4" required
        />
        <input
          type="password" placeholder="Mot de passe"
          value={password} onChange={e => setPassword(e.target.value)}
          className="w-full p-2 border rounded mb-4" required
        />
        <button type="submit" disabled={loading}
          className="w-full bg-blue-600 text-white p-2 rounded hover:bg-blue-700">
          {loading ? 'Connexion...' : 'Se connecter'}
        </button>
        <p className="text-sm text-gray-500 mt-4 text-center">
          <a href="#" onClick={() => supabase.auth.resetPasswordForEmail(email)}>
            Mot de passe oublié ?
          </a>
        </p>
      </form>
    </div>
  )
}
```

## 3. getAuthHeaders — remplacer `apiHeaders()`

```ts
export function getAuthHeaders(): Record<string, string> {
  const session = supabase.auth.getSession()
  const token = session?.access_token
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}
```

## 4. callHermes — server function SANS requireSupabaseAuth

```ts
// src/lib/hermes-proxy.functions.ts
import { createServerFn } from "@tanstack/react-start";
import { getRequest } from "@tanstack/react-start/server";

export const callHermes = createServerFn({ method: "POST" })
  .handler(async ({ data }) => {
    const request = getRequest();
    const backendUrl = process.env.PLAUDIA_BACKEND_URL;
    const headers = new Headers();
    headers.set("Content-Type", "application/json");
    headers.set("X-Plaudia-Key", process.env.PLAUDIA_SHARED_KEY);
    headers.set("CF-Access-Client-Id", process.env.CF_CLIENT_ID);
    headers.set("CF-Access-Client-Secret", process.env.CF_CLIENT_SECRET);
    const authHeader = request.headers.get("authorization");
    if (authHeader) headers.set("Authorization", authHeader);
    const response = await fetch(`${backendUrl}${data.path}`, {
      method: data.method || "POST",
      headers,
      body: data.body ? JSON.stringify(data.body) : undefined,
    });
    return { status: response.status, body: await response.text() };
  });
```

## 5. Se souvenir : PAS d'inscription publique

- Martin crée les comptes dans le dashboard Supabase
- Le trigger `on_auth_user_created` crée auto le `user_profiles`
- Pour passer un user en admin : `UPDATE user_profiles SET role = 'admin' WHERE email = '...'`