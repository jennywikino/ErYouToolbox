import {useEffect,useState} from 'react'
export type HistoryStatus={settings:{enabled:boolean;paused:boolean;max_pages:number};coverage:string;last_run?:{status:string;started_at?:string;ended_at?:string;requests?:number;error?:string;games?:{newly_collected_old?:number;inserted?:number;duplicates?:number;pages?:unknown[];failures?:unknown[]}[]};games:{game_id:number;name:string;checkpoint?:{page:number;oldest?:string}}[]}
export default function HistorySyncSettings({mode,onComplete,onStatus}:{mode?:string;onComplete:()=>void;onStatus?:(s:HistoryStatus)=>void}){
 const [data,setData]=useState<HistoryStatus|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 useEffect(()=>{let stopped=false;const poll=async()=>{try{const r=await fetch('/api/history-sync');const v=await r.json();if(!r.ok)throw Error(v.error);if(!stopped){setData(v);setError('')}}catch(e){if(!stopped)setError(String(e))}};poll();const timer=setInterval(poll,3000);return()=>{stopped=true;clearInterval(timer)}},[])
 useEffect(()=>{if(data)onStatus?.(data)},[data,onStatus])
 useEffect(()=>{if(data?.last_run?.ended_at)onComplete()},[data?.last_run?.ended_at])
 async function send(action:string){setBusy(true);setError('');try{const r=await fetch('/api/history-sync',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify({action})});const v=await r.json();if(!r.ok)throw Error(v.error)}catch(e){setError(String(e))}finally{setBusy(false)}}
 const [authorization,setAuthorization]=useState(mode||'off')
 useEffect(()=>setAuthorization(mode||'off'),[mode])
 async function authorize(){if(authorization==='apply'&&!window.confirm('授权历史补全入库：使用既有同步模式，也影响旧CLI或已注册任务的入库授权；不改变客户端启动一次/手动刷新规则。将先备份，再事务保存较早作品并推进历史检查点。确认？'))return;setBusy(true);setError('');try{const r=await fetch('/api/history-sync',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify({action:'authorize',mode:authorization})});const v=await r.json();if(!r.ok)throw Error(v.error);setData(v);window.dispatchEvent(new Event('automation-configured'))}catch(e){setError(String(e))}finally{setBusy(false)}}
 const running=data?.last_run?.status==='checking'
 return <section className="mt-3 border-t border-slate-200 pt-3 text-sm"><strong>历史补全 · 继续向前搜索</strong>
 <label>历史补全授权 <select aria-label="历史补全授权" value={authorization} disabled={busy||running} onChange={e=>setAuthorization(e.target.value)}><option value="off">关闭（仅可手动预览）</option><option value="check">仅检查，不入库</option><option value="apply">允许入库</option></select></label> <button className="small-button" disabled={busy||running} onClick={authorize}>确认保存授权</button>
 <p>每批每游戏最多 2 页，包含边界重叠复核；不会后台无限搜索。{mode==='apply'?'当前已授权入库，成功事务后才推进历史边界。':'当前仅预览；入库授权前不推进正式历史检查点。'}</p>
 <button className="small-button" disabled={busy||running} onClick={()=>send('continue')}>继续向前搜索</button><button className="small-button ml-3" disabled={busy||!running} onClick={()=>send('stop')}>暂停</button>
 {data?.last_run&&<p role="status">{data.last_run.status} · 请求 {data.last_run.requests||0} · 已检查页 {data.last_run.games?.reduce((n,g)=>n+(g.pages?.length||0),0)||0} · {mode==='apply'?'新收录':'候选'} {data.last_run.games?.reduce((n,g)=>n+(g.inserted??g.newly_collected_old??0),0)||0} · 重复 {data.last_run.games?.reduce((n,g)=>n+(g.duplicates||0),0)||0} · 失败 {data.last_run.games?.reduce((n,g)=>n+(g.failures?.length||0),0)||0}</p>}
 <details><summary>历史边界及错误（覆盖仍不完整）</summary>{data?.games.map(g=><p key={g.game_id}>{g.name} · 已提交第 {g.checkpoint?.page||0} 页 · 边界日期 {g.checkpoint?.oldest||'尚未确认'}</p>)}{data?.last_run?.error&&<p role="alert">{data.last_run.error}</p>}</details>
 {error&&<p role="alert">{error}</p>}</section>
}
