import {useEffect,useState,useRef} from 'react'

type Status={status:string;running:boolean;requests?:number;error?:string;totals?:{updated:number;failed:number;success:number;candidates:number};inventory:{total:number;missing:number;verification:Record<string,number>};errors?:{mod_id:number;reason:string}[]}

export default function RatingEnrichment({onComplete}:{onComplete:()=>void}){
 const [data,setData]=useState<Status|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(false),[busy,setBusy]=useState(false)
 const callback=useRef(onComplete);callback.current=onComplete
 const pending=useRef(false)
 useEffect(()=>{let stopped=false,wasRunning=false,timer:ReturnType<typeof setTimeout>;const poll=async()=>{try{
  const r=await fetch('/api/rating-enrichment');const v=await r.json();if(!r.ok)throw Error(v.error)
  if(!stopped){setData(v);if((wasRunning||pending.current)&&!v.running){pending.current=false;callback.current()}wasRunning=v.running}
 }catch(e){if(!stopped)setError(String(e))}finally{if(!stopped)timer=setTimeout(poll,3000)}};poll();return()=>{stopped=true;clearTimeout(timer)}},[])
 const run=async(apply:boolean)=>{
  if(apply&&!window.confirm('将对最多20条缺少可信分级的作品请求详情，备份后保存来源分级。不会改变人工审核、图片或用户状态。继续？'))return
  setBusy(true);setError('')
  try{const r=await fetch('/api/rating-enrichment',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify({action:'run',apply,limit:20,retry_failed:retry})});const v=await r.json();if(!r.ok)throw Error(v.error);pending.current=true;setData(old=>old?{...old,...v,running:true}:old)}catch(e){setError(String(e))}finally{setBusy(false)}
 }
 const stop=async()=>{try{const r=await fetch('/api/rating-enrichment',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:'{"action":"stop"}'});if(!r.ok)throw Error('停止请求失败')}catch(e){setError(String(e))}}
 return <details className="my-4 border-t border-slate-100 pt-3 text-xs"><summary>分级补全 · {data?`明确 ${data.inventory.verification.explicit_labels||0} · Unrated ${data.inventory.verification.source_unrated_flag||0} · UNKNOWN ${data.inventory.missing}`:'读取中'}</summary>
 <p className="my-2">仅补全本地缺失来源证据；每批最多20条，顺序请求。Unrated不是人工安全审核。</p>
 <label className="my-2 flex gap-2"><input type="checkbox" checked={retry} onChange={e=>setRetry(e.target.checked)}/>重试失败队列</label>
 <div className="flex flex-wrap gap-2"><button className="small-button" disabled={busy||data?.running} onClick={()=>run(false)}>预览补全</button><button className="small-button" disabled={busy||data?.running} onClick={()=>run(true)}>补全并保存…</button>{data?.running&&<button className="small-button" onClick={stop}>停止后续请求</button>}</div>
 <p className="my-2" role="status">{data?.running?'正在补全':data?.status||'尚未开始'} · 请求 {data?.requests||0} · 候选 {data?.totals?.candidates||0} · 保存 {data?.totals?.updated||0} · 失败 {data?.totals?.failed||0}</p>
 {(error||data?.error)&&<p role="alert">{error||data?.error}</p>}{data?.errors?.slice(0,3).map((e,i)=><p key={i}>MOD {e.mod_id||'—'}：{e.reason}</p>)}
 </details>
}
