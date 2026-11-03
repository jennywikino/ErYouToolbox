import AutoSyncSettings, {type AutoStatus} from './AutoSyncSettings'
import HistorySyncSettings, {type HistoryStatus} from './HistorySyncSettings'
import CacheSettings from './CacheSettings'
import AutomationConsent from './AutomationConsent'
import {useEffect,useState,useRef} from 'react'
type Counts=Record<string,number>
type Statistics={fetched:number;unique:number;duplicates:number;unclassified:number;classified:number;new:number;source_updated:number;metadata_only:number;unchanged:number;skipped:number;out_of_window?:number;missing_dates?:number}
type GameResult={game_id:number;name:string;status:string;scanned:number;requests:number;report?:Counts;failures:unknown[];pages?:number[];scan_status?:string;statistics?:Statistics;missing_update_evidence?:number;checkpoint?:{frontier?:number;last_success_check_at?:string}}
type Result={status:string;game_id?:number|null;token?:string;scanned?:number;requests?:number;error?:string;failures?:unknown[];report?:Counts;games?:GameResult[];current_game?:string;current_page?:number;completed?:number;planned?:number;statistics?:Statistics;scan_status?:string}
export default function SyncCheck({game,onComplete}:{game:string;onComplete:()=>void}){
 const [value,setValue]=useState<Result>({status:'idle'}),[error,setError]=useState(''),[sending,setSending]=useState(false),[pages,setPages]=useState(3)
 const [expanded,setExpanded]=useState(false),[auto,setAuto]=useState<AutoStatus|null>(null)
 const [autoError,setAutoError]=useState('')
 const [historyStatus,setHistory]=useState<HistoryStatus|null>(null)
 const settingsDialog=useRef<HTMLDialogElement>(null)
 useEffect(()=>{if(expanded)settingsDialog.current?.showModal();else settingsDialog.current?.close()},[expanded])
 const busy=sending||['checking','importing'].includes(value.status)||auto?.last_run?.status==='checking'||historyStatus?.last_run?.status==='checking'
 useEffect(()=>{let disposed=false;const poll=()=>fetch('/api/sync').then(r=>{if(!r.ok)throw Error('状态读取失败');return r.json()}).then(v=>{if(!disposed)setValue(v)}).catch(e=>{if(!disposed)setError(String(e))});poll();const t=setInterval(poll,1500);return()=>{disposed=true;clearInterval(t)}},[])
 useEffect(()=>{if(['success','partial'].includes(value.status))onComplete()},[value.status,value.report?.sync_run_id])
 // The automatic worker may finish author checks after the MOD preview/apply.
 // Refresh once per completed run, including read-only check reports.
 useEffect(()=>{if(auto?.last_run?.ended_at)onComplete()},[auto?.last_run?.ended_at])
 async function send(action:string){setError('');setSending(true);try{
  const body=action==='stop'?{action}:action==='check_all'?{action,max_pages:pages}:action==='check'?{action,game:Number(game),max_pages:pages}:action==='resume'?{action,game:value.game_id??null,max_pages:pages}:{action,game:value.game_id,token:value.token}
  const r=await fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error);setValue(v)
 }catch(e){setError(String(e))}finally{setSending(false)}}
 const labels:Record<string,string>={not_checked:'就绪',idle:'尚未开始',checking:'正在检查',waiting:'等待确认',importing:'正在导入',success:'同步成功',partial:'部分成功',failed:'同步失败',discarded:'已放弃本次预览',stopped:'等待续扫',complete_check:'完整检查（仅本次来源末页）',incomplete:'扫描未完成',awaiting_resume:'等待续扫',rate_limited:'遇到限流',check_failed:'检查失败'}
 const autoFailed=['failed','partial','stopped'].includes(auto?.last_run?.status||'')
 const counts=(r?:Counts)=>r?`新增 ${r.inserted} · 来源更新 ${r.source_update_events} · 仅资料变化/证据不足 ${r.updated-r.source_update_events} · 无变化 ${r.unchanged} · 跳过 ${r.skipped}`:'暂无候选'
 const stats=(s?:Statistics)=>s?`原始记录 ${s.fetched} = 已分类 ${s.classified} + 重复 ${s.duplicates} + 未能分类 ${s.unclassified}；候选去重 ${s.unique} · 窗口外 ${s.out_of_window||0} · 日期缺失 ${s.missing_dates||0}`:''
 async function runSaved(){setSending(true);setError('');try{const r=await fetch('/api/auto-sync/run',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:'{}'});const v=await r.json();if(!r.ok)throw Error(v.error)}catch(e){setError(String(e))}finally{setSending(false)}}
 async function historyAction(action:string){setSending(true);setError('');try{const r=await fetch('/api/history-sync',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify({action})});const v=await r.json();if(!r.ok)throw Error(v.error)}catch(e){setError(String(e))}finally{setSending(false)}}
 return <section className="sync-inline mb-5">
  {auto?.task.status==='unsupported'&&auto.configured===false&&<AutomationConsent onSaved={()=>window.dispatchEvent(new Event('automation-configured'))}/>}
  <div className="sync-inline-actions">
   <button className="small-button refresh-button" disabled={busy} onClick={()=>auto?.settings.mode&&auto.settings.mode!=='off'?runSaved():send(game?'check':'check_all')}>{busy?'刷新中…':'刷新'}</button>
   <span>{auto?.settings.mode==='off'?'手动模式':`自动每 ${auto?.settings.interval_hours||3} 小时`}</span>
   <button className="small-button" disabled={busy} onClick={()=>historyAction('continue')}>继续向前搜索</button>
   <button className="small-button" aria-expanded={expanded} aria-controls="sync-management" onClick={()=>setExpanded(true)}>更多设置</button>
   <CacheSettings/>
   {value.status==='waiting'&&<button className="pending-preview" onClick={()=>setExpanded(true)}>待确认导入</button>}
   {busy&&<button className="small-button" onClick={()=>{fetch('/api/auto-sync/run',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify({action:'stop'})});send('stop');historyAction('stop')}}>停止</button>}
  </div>
  <p className="sync-inline-result" role="status">{busy?`正在检查 ${value.current_game||''} · 已完成 ${value.completed||0} 款`:auto?.last_run?.ended_at?`最近：新增 ${auto.last_run.inserted??0} · 来源更新 ${auto.last_run.source_updated??0}`:value.report?`新增 ${value.report.inserted} · 来源更新 ${value.report.source_update_events}`:'优先发现近90天发布或更新的作品 · 扫描有上限，不代表来源全量'}{historyStatus?.last_run?.status==='checking'?' · 正在搜索更早历史':''}</p>
  {(error||value.error||autoError||autoFailed)&&<p className="status-error" role="alert">{error||value.error||autoError||auto?.last_run?.error||'上次检查未全部成功，请查看更多设置'}</p>}
  <dialog id="sync-management" ref={settingsDialog} onClose={()=>setExpanded(false)} onCancel={()=>setExpanded(false)} className="settings-dialog sync-management">
  <div className="settings-heading"><h2>同步设置与任务详情</h2><button aria-label="关闭同步设置" onClick={()=>setExpanded(false)}>✕</button></div>
  <AutoSyncSettings onStatus={setAuto} onError={setAutoError}/>
  <HistorySyncSettings mode={auto?.settings.mode} onComplete={onComplete} onStatus={setHistory}/>
  <button className="small-button" disabled={!game||busy} onClick={()=>send('check')}>检查当前游戏</button>
  <button className="small-button ml-3" disabled={busy} onClick={()=>send('check_all')}>检查全部游戏</button>
  <label className="ml-3">每游戏最多页数 <select aria-label="同步页数上限" value={pages} disabled={busy} onChange={e=>setPages(Number(e.target.value))}>{Array.from({length:10},(_,i)=><option key={i+1}>{i+1}</option>)}</select></label>
  {value.status==='checking'&&<button className="small-button ml-3" disabled={sending} onClick={()=>send('stop')}>停止（当前请求结束后）</button>}
  {!busy&&value.status!=='idle'&&<button className="small-button ml-3" onClick={()=>send('resume')}>继续扫描（重叠复查）</button>}
  {!game&&<span> 当前游戏检查需先选择具体游戏</span>}
  <span className="ml-3">{labels[value.status]||value.status} · {labels[value.scan_status||'']}</span>
  {value.current_game&&<span> · {value.current_game} 第 {value.current_page} 页 · 已完成 {value.completed||0} 款</span>}
  {value.status==='waiting'&&!busy&&(value.game_id===null||value.game_id===Number(game))&&<button className="small-button ml-3" onClick={()=>send('confirm')}>确认导入{value.game_id===null?'（全部已验证候选）':''}</button>}
  {value.status==='waiting'&&!busy&&<button className="small-button ml-3" onClick={()=>send('discard')}>放弃本次预览</button>}
  <p>默认每游戏最多 3 页；当前游戏每页最多 20 条，全部游戏每页最多 10 条。Coverage=incomplete，不保证无遗漏。预览十分钟有效；未提交续扫会重新检查，只有确认提交才推进正式检查点。</p>
  {value.games?.map(g=><div key={g.game_id} className="mt-2"><p>{g.name} · {labels[g.scan_status||'']||g.status} · 已检查页 {g.pages?.join(', ')||'无'} · 请求 {g.requests} · {counts(g.report)} · 失败 {g.failures.length}</p><p>{stats(g.statistics)} · 缺更新时间证据 {g.missing_update_evidence??0} · 上次成功检查 {g.checkpoint?.last_success_check_at||'无'}</p>{g.failures.length>0&&<p role="alert">{JSON.stringify(g.failures)}</p>}</div>)}
  {value.report&&<p className="mt-2 font-medium">总计：{stats(value.statistics)} · 请求 {value.requests} · {counts(value.report)} · 失败/未执行 {value.failures?.length||0} · 已检查 {value.completed}/{value.planned} 款</p>}
  {(error||value.error)&&<p role="alert">{error||value.error}</p>}
 </dialog>
 </section>
}
