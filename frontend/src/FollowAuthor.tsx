import {useEffect, useState} from 'react'

export default function FollowAuthor({source, authorId, onChange}: {source: string; authorId: number | null; onChange: () => void}) {
  const [state, setState] = useState<{available: boolean; followed: boolean} | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const valid = Number.isSafeInteger(authorId) && (authorId ?? 0) > 0
  useEffect(() => {
    if (!valid) return
    const controller = new AbortController()
    fetch('/api/subscription?' + new URLSearchParams({source, author_id: String(authorId)}), {signal: controller.signal})
      .then(async response => {const data = await response.json(); if (!response.ok) throw Error(data.error); setState(data)})
      .catch(error => {if (error.name !== 'AbortError') setError(error.message)})
    return () => controller.abort()
  }, [source, authorId, valid])
  const toggle = async () => {
    if (!state?.available || busy) return
    setBusy(true); setError('')
    try {
      const response = await fetch('/api/subscription', {method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-ErYouToolbox': '1'},
        body: JSON.stringify({source, author_id: authorId, followed: !state.followed})})
      const data = await response.json()
      if (!response.ok) throw Error(data.error)
      setState(data); onChange()
    } catch (error) {setError(error instanceof Error ? error.message : '关注操作失败')}
    finally {setBusy(false)}
  }
  return <div className="my-3 text-xs">
    <button className="small-button" disabled={!valid || !state?.available || busy} onClick={toggle}>
      {busy ? '保存中…' : state?.followed ? '已关注 · 取消关注' : '关注作者'}
    </button>
    {!valid && <p className="mt-2 text-slate-500">缺少有效作者 ID，无法关注。</p>}
    {state && !state.available && <p className="mt-2 text-slate-500">需先手动迁移作者订阅数据表。</p>}
    {error && <p role="alert" className="mt-2 text-red-600">{error}</p>}
  </div>
}
