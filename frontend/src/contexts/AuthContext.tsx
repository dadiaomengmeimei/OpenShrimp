import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { UserInfo, authLogin, authRegister, authMe } from '../services/api'

interface AuthContextType {
  user: UserInfo | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, displayName?: string) => Promise<void>
  logout: () => void
  isAuthenticated: boolean
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [loading, setLoading] = useState(true)

  // On mount, check if we have a stored token and validate it
  useEffect(() => {
    const token = localStorage.getItem('auth_token')
    const storedUser = localStorage.getItem('auth_user')

    if (token && storedUser) {
      // Optimistically set user from localStorage
      try {
        setUser(JSON.parse(storedUser))
      } catch {
        // ignore parse errors
      }
      // Validate token with backend
      authMe()
        .then((userData) => {
          setUser(userData)
          localStorage.setItem('auth_user', JSON.stringify(userData))
        })
        .catch(() => {
          // Token expired or invalid
          localStorage.removeItem('auth_token')
          localStorage.removeItem('auth_user')
          setUser(null)
        })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const login = async (username: string, password: string) => {
    const data = await authLogin(username, password)
    localStorage.setItem('auth_token', data.access_token)
    localStorage.setItem('auth_user', JSON.stringify(data.user))
    setUser(data.user)
  }

  const register = async (username: string, password: string, displayName?: string) => {
    const data = await authRegister(username, password, displayName)
    localStorage.setItem('auth_token', data.access_token)
    localStorage.setItem('auth_user', JSON.stringify(data.user))
    setUser(data.user)
  }

  const logout = () => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{
      user,
      loading,
      login,
      register,
      logout,
      isAuthenticated: !!user,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
