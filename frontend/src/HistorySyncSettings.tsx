import {useEffect,useState} from 'react'

type Settings={enabled:boolean;paused:boolean;max_pages:number}
type HistoryStatus={settings:Settings;coverage:string;not_before:number;last_run?:{status:string;mode?:string;ended_at?:string;started_at?:string;requests?:number;error?:string;games?:{newly_collected_old?:number;failures?:unknown[]}[]};games:{game_id:number;name:string;status?:string;last_scan_at?:string;failures?:unknown[];checkpoint?:{page:number;per_page:number;oldest?:string;source_end_observed:boolean}}[]}

export default function HistorySyncSettings({mode,onComplete}:{mode?:string;onComplete:()=>void}){
 const [data,setData]=useState<HistoryStatus|null>(null),[error,setError]=useState(''),[sending,setSending]=useState(false)
 useEffect(()=>{let stopped=false;const poll=async()=>{try{const r=await fetch('/api/history-sync');const v=await r.json();if(!r.ok)throw Error(v.error);if(!stopped){setData(v);setError('')}}catch(e){if(!stopped)setError(String(e))}};poll();const timer=setInterval(poll,5000);return()=>{stopped=true;clearInterval(timer)}},[])
 useEffect(()=>{if(data?.last_run?.ended_at)onComplete()},[data?.last_run?.ended_at])
 async function send(settings?:Settings){
  if(settings?.enabled&&!data?.settings.enabled&&mode==='apply'&&!window.confirm('当前为自动入库模式。启用历史补全后，已有计划任务可逐批导入历史作品。是否启用？'))return
  setSending(true);setError('');try{const r=await fetch('/api/history-sync',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify(settings?{action:'configure',settings}:{action:'run'})});const v=await r.json();if(!r.ok)throw Error(v.error);if(v.settings)setData(v)}catch(e){setError(String(e))}finally{setSending(false)}
 }
 const busy=sending||data?.last_run?.status==='checking'
 const labels:Record<string,string>={checking:'正在扫描',success:'本轮已完成',partial:'部分完成',failed:'检查失败',stopped:'已暂停，等待复核',not_due:'未到检查时间',not_requested:'尚未开始',disabled:'已关闭',cooldown:'限流冷却中',manual_preview_pending:'等待处理手动预览'}
 const result=data?.last_run
 return <section className="mt-3 border-t border-slate-200 pt-3 text-sm" aria-label="历史补全">
  <strong>历史补全</strong>
  {data&&<><label className="ml-3"><input type="checkbox" checked={data.settings.enabled} disabled={sending} onChange={e=>send({...data.settings,enabled:e.target.checked})}/> 启用</label>
   <label className="ml-3">每游戏最多页数 <select aria-label="历史扫描页数" value={data.settings.max_pages} disabled={sending} onChange={e=>send({...data.settings,max_pages:Number(e.target.value)})}>{[1,2,3,4,5].map(n=><option key={n}>{n}</option>)}</select></label>
   <button className="small-button ml-3" disabled={busy||!data.settings.enabled||data.settings.paused||!mode||mode==='off'} onClick={()=>send()}>手动执行一次</button>
   <button className="small-button ml-3" disabled={sending||!data.settings.enabled} onClick={()=>send({...data.settings,paused:!data.settings.paused})}>{data.settings.paused?'继续':'暂停'}</button>
   <p className="mt-2" role="status">{!data.settings.enabled?'已关闭':data.settings.paused?'已暂停':labels[result?.status||'not_requested']||result?.status} · 最近扫描 {result?.started_at||'暂无'} · {result?.mode==='check'?'新收录候选':'新收录'} {result?.games?.reduce((n,g)=>n+(g.newly_collected_old||0),0)||0} · 失败 {result?.games?.reduce((n,g)=>n+(g.failures?.length||0),0)||0}</p>
   <p className="text-xs text-slate-500">低优先级 · 每游戏每 24 小时最多一次（失败尝试也计入）· 仅 check 模式预览，apply 模式才入库 · 覆盖仍不完整。续扫建议至少 2 页，包含边界重叠复核。</p>
   {mode==='off'&&data.settings.enabled&&<p>自动同步已关闭，历史任务不会运行。</p>}
   {data.not_before>Date.now()/1000&&<p>限流冷却至 {new Date(data.not_before*1000).toLocaleString()}</p>}
   <details className="mt-2"><summary>各游戏进度与错误</summary>{data.games.map(g=><p key={g.game_id}>{g.name} · 最近扫描 {g.last_scan_at||'无'} · 已提交至第 {g.checkpoint?.page||0} 页 · 实际每页 {g.checkpoint?.per_page||'未验证'} 条 · {g.checkpoint?.source_end_observed?'观察到来源末页':'尚未确认末页'} · {g.failures?.length?`${g.failures.length} 项错误，等待复核`:labels[g.status||'not_requested']||g.status}</p>)}{result?.error&&<p role="alert">{result.error}</p>}</details>
  </>}
  {error&&<p role="alert">{error}</p>}
 </section>
}
