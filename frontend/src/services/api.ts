import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 300000,
})

// ─── Auth token interceptor ───
// Automatically attach the JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Auto-redirect to login on 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/')) {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('auth_user')
      // Redirect to login (only if not already there)
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

// ─── Types ───

export interface AppInfo {
  id: string
  name: string
  description: string
  icon: string
  version: string
  author: string
  author_id: string | null
  category: string
  config: Record<string, unknown>
  enabled: boolean
  is_public: boolean
  sort_order: number
  created_at: string
  updated_at: string
  added_by_user?: boolean  // Market annotation
}

export interface UserInfo {
  id: string
  username: string
  display_name: string
  is_admin: boolean
  created_at: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: UserInfo
}

export interface UploadResult {
  session_id: string
  filename: string
  rows?: number
  columns?: string[]
  preview?: Record<string, unknown>[]
  total_chars?: number
  num_chunks?: number
}

// ─── Auth APIs ───

export const authLogin = (username: string, password: string) =>
  api.post<AuthResponse>('/auth/login', { username, password }).then(r => r.data)

export const authRegister = (username: string, password: string, display_name?: string) =>
  api.post<AuthResponse>('/auth/register', { username, password, display_name }).then(r => r.data)

export const authMe = () => api.get<UserInfo>('/auth/me').then(r => r.data)

// ─── Platform App APIs ───

export const listApps = () => api.get<AppInfo[]>('/apps').then(r => r.data)
export const getApp = (id: string) => api.get<AppInfo>(`/apps/${id}`).then(r => r.data)
export const createApp = (data: Partial<AppInfo>) => api.post<AppInfo>('/apps', data).then(r => r.data)
export const deleteApp = (id: string) => api.delete(`/apps/${id}`).then(r => r.data)
export const updateAppInfo = (id: string, data: { name?: string; description?: string; icon?: string }) =>
  api.put<AppInfo>(`/apps/${id}/info`, data).then(r => r.data)

// ─── Market APIs ───

export const listMarket = () => api.get<AppInfo[]>('/market').then(r => r.data)
export const addFromMarket = (appId: string) => api.post<{ ok: boolean; app_id: string }>(`/market/${appId}/add`).then(r => r.data)
export const removeFromMarket = (appId: string) => api.delete<{ ok: boolean; app_id: string }>(`/market/${appId}/remove`).then(r => r.data)
export const publishApp = (appId: string) => api.post<AppInfo>(`/apps/${appId}/publish`).then(r => r.data)
export const unpublishApp = (appId: string) => api.post<AppInfo>(`/apps/${appId}/unpublish`).then(r => r.data)

// ─── Admin APIs ───

export const adminListUsers = () => api.get<UserInfo[]>('/admin/users').then(r => r.data)
export const adminListAllApps = () => api.get<AppInfo[]>('/admin/apps').then(r => r.data)

// ─── Generic App File Upload API ───

export interface GenericUploadResult {
  ok: boolean
  file_path: string
  original_name: string
  size: number
  ext: string
}

export const uploadFileForApp = (appId: string, file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post<GenericUploadResult>(`/apps/${appId}/upload`, fd).then(r => r.data)
}

// ─── Excel Analyzer APIs ───

export const uploadExcel = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post<UploadResult & {
    numeric_columns?: string[]
    categorical_columns?: string[]
    datetime_columns?: string[]
  }>('/apps/excel_analyzer/upload', fd).then(r => r.data)
}
export const analyzeExcel = (sessionId: string, question: string, history: Array<{role: string; content: string}> = []) =>
  api.post<{ answer: string; code: string[]; exec_results: string[] }>('/apps/excel_analyzer/analyze', { session_id: sessionId, question, history }).then(r => r.data)
export const generateChart = (sessionId: string, instruction: string) =>
  api.post<{ image: string; code: string; chart_id: string }>('/apps/excel_analyzer/chart', { session_id: sessionId, instruction }).then(r => r.data)

export const generatePresetChart = (sessionId: string, chartType: string, xColumn?: string, yColumn?: string, title?: string, columns?: string[]) =>
  api.post<{ image: string; code: string; chart_id: string; chart_type: string }>('/apps/excel_analyzer/chart/preset', {
    session_id: sessionId, chart_type: chartType, x_column: xColumn, y_column: yColumn, title, columns
  }).then(r => r.data)

export const getChartHistory = (sessionId: string) =>
  api.get<Array<{ id: string; instruction: string; chart_type: string; timestamp: number }>>(`/apps/excel_analyzer/chart/history/${sessionId}`).then(r => r.data)

export const getChartById = (sessionId: string, chartId: string) =>
  api.get<{ id: string; image: string; code: string; instruction: string; chart_type: string; timestamp: number }>(`/apps/excel_analyzer/chart/history/${sessionId}/${chartId}`).then(r => r.data)

export const exportChartUrl = (sessionId: string, chartId: string) =>
  `/api/apps/excel_analyzer/chart/export/${sessionId}/${chartId}`

export const suggestCharts = (sessionId: string) =>
  api.post<{ suggestions: Array<{ chart_type: string; label: string; description: string; x_column: string | null; y_column: string | null }> }>('/apps/excel_analyzer/chart/suggest', { session_id: sessionId, question: '' }).then(r => r.data)

// ─── RAG Reader APIs ───

export const uploadDocument = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post<UploadResult>('/apps/rag_reader/upload', fd).then(r => r.data)
}
export const queryDocument = (sessionId: string, question: string) =>
  api.post<{ answer: string; sources: number }>('/apps/rag_reader/query', { session_id: sessionId, question }).then(r => r.data)

// ─── Agent APIs (SSE streaming) ───

export interface AgentEvent {
  type: 'start' | 'log' | 'text_delta' | 'tool_call' | 'tool_result' | 'file_modified' | 'done' | 'error' | 'skills_updated' | 'scope_warning' | '_loop_done'
  message?: string
  delta?: string
  tool?: string
  input?: Record<string, unknown>
  output?: string
  path?: string
  files_modified?: string[]
  method?: string
  app_id?: string
  session_id?: string
  name?: string
  description?: string
  icon?: string
  category?: string
  error?: string
  count?: number
  items?: string[]
  iterations?: number
  reason?: string
  suggestion?: string
}

// Helper: attach auth token to fetch requests (for SSE streams)
function _authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('auth_token')
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

export async function generateAppStream(
  description: string,
  appId?: string,
  baseAppId?: string,
  onEvent?: (event: AgentEvent) => void,
): Promise<void> {
  console.log('[generateAppStream] starting', { appId, descLen: description.length })
  let response: Response
  try {
    response = await fetch('/api/agent/generate', {
      method: 'POST',
      headers: _authHeaders(),
      body: JSON.stringify({ description, app_id: appId, base_app_id: baseAppId }),
    })
  } catch (fetchErr: any) {
    console.error('[generateAppStream] fetch failed:', fetchErr)
    throw new Error(`Network error: ${fetchErr.message || 'Failed to fetch'}. Check if the backend is running.`)
  }

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    console.error('[generateAppStream] HTTP error:', response.status, text)
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('No response body')

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event: AgentEvent = JSON.parse(line.slice(6))
            onEvent?.(event)
          } catch {
            // Skip malformed JSON
          }
        }
      }
    }
  } catch (streamErr: any) {
    console.error('[generateAppStream] stream read error:', streamErr)
    throw new Error(`Stream interrupted: ${streamErr.message}. The agent may still be running on the backend.`)
  }
  console.log('[generateAppStream] completed')
}

export interface AutoFixParams {
  app_id: string
  error_message: string
  error_type?: string
  traceback?: string
  user_input?: string
  phase?: string
  mode?: string
  conversation_history?: Array<{ role: string; content: string }>
  actual_output?: string
  expected_behavior?: string
}

export async function autoFixAppStream(
  params: AutoFixParams,
  onEvent?: (event: AgentEvent) => void,
): Promise<void> {
  console.log('[autoFixAppStream] starting', { app_id: params.app_id, mode: params.mode })
  let response: Response
  try {
    response = await fetch('/api/agent/auto-fix', {
      method: 'POST',
      headers: _authHeaders(),
      body: JSON.stringify(params),
    })
  } catch (fetchErr: any) {
    console.error('[autoFixAppStream] fetch failed:', fetchErr)
    throw new Error(`Network error: ${fetchErr.message || 'Failed to fetch'}. Check if the backend is running.`)
  }

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    console.error('[autoFixAppStream] HTTP error:', response.status, text)
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('No response body')

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event: AgentEvent = JSON.parse(line.slice(6))
          onEvent?.(event)
        } catch {
          // Skip malformed JSON
        }
      }
    }
  }
}

export const testApp = (appId: string) =>
  api.post<{ ok: boolean; phase: string; error: string | null; traceback?: string; auto_fixable?: boolean }>(`/apps/${appId}/test`).then(r => r.data)

export const getAgentStatus = () => api.get('/agent/status').then(r => r.data)

// Agent session control
export const interruptAgent = (sessionId: string) =>
  api.post<{ ok: boolean; session_id: string; message: string }>(`/agent/interrupt/${sessionId}`).then(r => r.data)

export const injectAgentMessage = (sessionId: string, message: string) =>
  api.post<{ ok: boolean; session_id: string; queued: number }>('/agent/inject', { session_id: sessionId, message }).then(r => r.data)

export const listAgentSessions = () =>
  api.get<Array<{ id: string; running: boolean; interrupted: boolean }>>('/agent/sessions').then(r => r.data)

// Skills APIs
export interface SkillsData {
  app_id: string
  items: string[]
  updated_at: string | null
  session_count: number
  total_chars: number
  max_chars: number
}

export const getAppSkills = (appId: string) =>
  api.get<SkillsData>(`/agent/skills/${appId}`).then(r => r.data)

export const updateAppSkills = (appId: string, data: { items?: string[]; add_item?: string; remove_index?: number }) =>
  api.put<SkillsData>(`/agent/skills/${appId}`, data).then(r => r.data)

export default api
