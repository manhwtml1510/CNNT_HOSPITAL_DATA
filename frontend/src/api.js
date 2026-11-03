const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, { token, ...options } = {}) {
  const headers = new Headers(options.headers || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!response.ok) {
    let detail = `Yêu cầu không thành công (${response.status})`
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : detail
    } catch {
      // Keep the readable status message when the server did not return JSON.
    }
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return null
  return response
}

export async function login(username, password) {
  const response = await request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  return response.json()
}

export async function getMe(token) {
  const response = await request('/auth/me', { token })
  return response.json()
}

export async function getRecords(token, offset = 0, limit = 50) {
  const response = await request(`/records?limit=${limit}&offset=${offset}`, { token })
  return response.json()
}

export async function createRecord(token, payload) {
  const response = await request('/records', { token, method: 'POST', body: JSON.stringify(payload) })
  return response.json()
}

export async function updateRecord(token, id, payload) {
  const response = await request(`/records/${id}`, { token, method: 'PATCH', body: JSON.stringify(payload) })
  return response.json()
}

export async function uploadFile(token, recordId, file) {
  const form = new FormData()
  form.append('upload', file)
  const response = await request(`/files/records/${recordId}`, { token, method: 'POST', body: form })
  return response.json()
}

export async function downloadFile(token, fileId) {
  return request(`/files/${fileId}/download`, { token })
}
