async function ensureOk(r) {
  if (r.ok) return r.json()
  const text = await r.text()
  try {
    const j = JSON.parse(text)
    throw new Error(typeof j.detail === 'string' ? j.detail : JSON.stringify(j))
  } catch (e) {
    if (e instanceof SyntaxError) throw new Error(text || `HTTP ${r.status}`)
    throw e
  }
}

export async function getJSON(path) {
  return ensureOk(await fetch(path))
}
export async function postJSON(path, body) {
  return ensureOk(await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }))
}
