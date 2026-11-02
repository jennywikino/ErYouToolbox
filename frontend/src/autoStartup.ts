// One request per document, including StrictMode/remounts. The server still
// owns interval, preview, cooldown and cross-process lock decisions.
export function createStartupRequest(request: typeof fetch) {
  let pending: Promise<unknown> | undefined
  return () => pending ??= (async () => {
    const status = await request('/api/auto-sync')
    const data = await status.json()
    if (!status.ok) throw Error(data.error || '自动同步状态读取失败')
    if (data.settings.mode === 'off') return {status: 'disabled'}
    const response = await request('/api/auto-sync/startup', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-ErYouToolbox': '1'}, body: '{}',
    })
    const result = await response.json()
    if (!response.ok) throw Error(result.error || '启动检查失败')
    return result
  })()
}
export const requestStartupCheck = createStartupRequest((...args) => fetch(...args))
