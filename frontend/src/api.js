async function parse(r) {
  if (!r.ok) {
    const text = await r.text()
    let message = text
    let data = null
    try {
      data = JSON.parse(text)
      if (data && data.error) message = data.error
    } catch {
      /* 非 JSON 响应时保留原文 */
    }
    const err = new Error(message)
    err.status = r.status
    err.data = data
    throw err
  }
  return r.json()
}

export async function getJSON(path) {
  const r = await fetch(path)
  return parse(r)
}

export async function postJSON(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parse(r)
}
