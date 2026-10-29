import { client } from './client'

export interface AuthConfig {
  provider: 'local' | 'oidc' | 'none'
  login_style: 'password' | 'redirect' | 'none'
  app_name: string
  version: string
  login_url?: string
}

export interface User {
  id?: string
  username: string
  email: string | null
  display_name?: string | null
  role: string
  auth_provider?: string
}

export interface Item {
  id: number
  name: string
  description: string | null
  status: string
  quantity: number
  created_at: string
  updated_at: string
}

export interface Page<T> {
  items: T[]
  page: number
  per_page: number
  total: number
  pages: number
}

export const api = {
  authConfig: () => client.get<AuthConfig>('/auth/config').then((r) => r.data),

  login: (username: string, password: string) =>
    client.post<{ access_token: string; user: User }>('/auth/login', { username, password })
      .then((r) => r.data),

  logout: () => client.post('/auth/logout').then((r) => r.data),

  me: () => client.get<User>('/auth/me').then((r) => r.data),

  items: (params: { page?: number; per_page?: number; status?: string; q?: string } = {}) =>
    client.get<Page<Item>>('/items', { params }).then((r) => r.data),

  itemSummary: () =>
    client.get<{ by_status: Record<string, number>; total: number }>('/items/summary')
      .then((r) => r.data),

  createItem: (data: Partial<Item>) => client.post<Item>('/items', data).then((r) => r.data),

  deleteItem: (id: number) => client.delete(`/items/${id}`).then((r) => r.data),
}
