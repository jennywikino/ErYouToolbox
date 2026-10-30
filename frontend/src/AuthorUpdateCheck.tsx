import {useEffect,useState} from 'react'
import {syncTimeLabel} from './policy'
type Result={checked_at?:string;status:string;new?:number;updates?:number;baseline_pending?:boolean}
export default function AuthorUpdateCheck(){
  const [data,setData]=useState<Result|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
  useEffect(()=>{const c=new AbortController();fetch('/api/author-updates',{signal:c.signal}).then(r=>r.json()).then(setData).catch(e=>{if(e.name!=='AbortError')setError('检查状态读取失败')});return()=>c.abort()},[])
  async function check(){setBusy(true);setError('');try{
    const r=await fetch('/api/author-updates',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:'{}'})
    const value=await r.json();if(!r.ok)throw Error(value.error);setData(value)
  }catch(e){setError(e instanceof Error?e.message:'检查失败')}finally{setBusy(false)}}
  return <section className="my-4 rounded-lg border border-violet-100 p-4 text-xs text-slate-500">
    <button className="small-button" disabled={busy} onClick={check}>{busy?'正在顺序检查…':'检查关注作者更新'}</button>
    <p className="mt-2">本次仅预览最多两位作者，尚未写入作品；需手动确认报告后导入。</p>
    {data&&<p className="mt-2">最近检查：{syncTimeLabel(data.checked_at)} · {data.status} · 新作候选 {data.new??0} · 来源更新候选 {data.updates??0}{data.baseline_pending?' · 首次检查待建立基线，历史作品不计新提醒':''}</p>}
    {data?.status==='success'&&!data.new&&!data.updates&&<p>本次有界预览未发现新动态，不代表来源全量。</p>}
    {error&&<p role="alert" className="mt-2 text-red-600">{error}</p>}
  </section>
}
