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

// A periodic request is only a due-time hint. The server still rechecks settings,
// cooldown, pending preview and the shared cross-process lock before any scan.
export async function requestDueCheck(request:typeof fetch, now=Date.now()) {
  const response=await request('/api/auto-sync')
  const status=await response.json()
  if(!response.ok)throw Error(status.error||'自动同步状态读取失败')
  if(status.settings.mode==='off'||!status.next_due||Date.parse(status.next_due)>now||status.last_run?.status==='checking'||status.last_run?.status==='manual_preview_pending')return {status:'not_due'}
  const result=await request('/api/auto-sync/startup',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:'{}'})
  const body=await result.json()
  if(!result.ok)throw Error(body.error||'到期检查失败')
  return body
}
