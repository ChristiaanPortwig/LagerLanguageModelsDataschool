export const API_ROOT = import.meta.env.VITE_API_BASE_URL || 'http://localhost:4000/api'
export const API_BASE = `${API_ROOT}/clients`

export async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, options)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(body.error || body.detail || `Request failed with status ${response.status}`)
  }
  return body
}
