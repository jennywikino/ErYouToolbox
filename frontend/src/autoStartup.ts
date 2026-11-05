// One request per document. The server additionally claims one startup per
// service lifetime; browser reloads and navigation cannot create another scan.
export function createStartupRequest(request: typeof fetch) {
  let pending: Promise<unknown> | undefined
  return () => pending ??= (async () => {
    const status = await request('/api/auto-sync')
    const data = await status.json()
    if (!status.ok) throw Error(data.error || '自动同步状态读取失败')
    const response = await request('/api/auto-sync/startup', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-ErYouToolbox': '1'}, body: '{}',
    })
    const result = await response.json()
    if (!response.ok) throw Error(result.error || '启动检查失败')
    return result
  })()
}
export const requestStartupCheck = createStartupRequest((...args) => fetch(...args))
