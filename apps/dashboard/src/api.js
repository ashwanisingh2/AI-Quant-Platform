const BASE = '/api'
let token = ''
export function setAuthToken(value) { token = value }
export function getAuthToken() { return token }
const authHeaders = () => ({ Authorization: `Bearer ${token}` })

export async function apiGet(path) {
  const r = await fetch(BASE + path, { headers: authHeaders() })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function apiPost(path, body = {}) {
  const r = await fetch(BASE + path, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export function wsUrl(path) {
  const proto = location.protocol === 'https:' ? 'wss://' : 'ws://'
  return proto + location.host + path
}
