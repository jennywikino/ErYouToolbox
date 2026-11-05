import {type AutoStatus} from './AutoSyncSettings'
import HistorySyncSettings, {type HistoryStatus} from './HistorySyncSettings'
import CacheSettings from './CacheSettings'
import CharacterLibrary from './CharacterLibrary'
import {gameBananaModId,syncFailureCount} from './policy'
import {useEffect,useState,useRef} from 'react'
type Counts=Record<string,number>
type Statistics={fetched:number;unique:number;duplicates:number;unclassified:number;classified:number;new:number;source_updated:number;metadata_only:number;unchanged:number;skipped:number;out_of_window?:number;missing_dates?:number}
type GameResult={game_id:number;name:string;status:string;scanned:number;requests:number;report?:Counts;failures:unknown[];network_seconds?:number;selection_seconds?:number;timestamp_skipped?:number;batch_import_seconds_shared?:number|null;pages?:number[];scan_status?:string;statistics?:Statistics;missing_update_evidence?:number;checkpoint?:{frontier?:number;last_success_check_at?:string}}
type Result={lookup?:boolean;lookup_record?:{item_id:number;title:string;author_name:string};status:string;game_id?:number|null;token?:string;scanned?:number;requests?:number;error?:string;failures?:unknown[];report?:Counts;games?:GameResult[];current_game?:string;current_page?:number;completed?:number;planned?:number;statistics?:Statistics;scan_status?:string}
export default function SyncCheck({game,games,visible=true,onComplete}:{game:string;games:{game_id:number;name:string}[];visible?:boolean;onComplete:()=>void}){
 const [value,setValue]=useState<Result>({status:'idle'}),[error,setError]=useState(''),[sending,setSending]=useState(false)
 const [lookupId,setLookupId]=useState('')
 const [manualGame,setManualGame]=useState(game),[manualOpen,setManualOpen]=useState(false)
 const manualDialog=useRef<HTMLDialogElement>(null)
 const [expanded,setExpanded]=useState(false),[auto,setAuto]=useState<AutoStatus|null>(null)
 const [historyStatus,setHistory]=useState<HistoryStatus|null>(null)
 const settingsDialog=useRef<HTMLDialogElement>(null)
 useEffect(()=>{if(expanded)settingsDialog.current?.showModal();else settingsDialog.current?.close()},[expanded])
 useEffect(()=>{if(manualOpen)manualDialog.current?.showModal();else manualDialog.current?.close()},[manualOpen])
 useEffect(()=>{const failed=(event:Event)=>setError((event as CustomEvent<string>).detail);window.addEventListener('auto-sync-error',failed);return()=>window.removeEventListener('auto-sync-error',failed)},[])
 useEffect(()=>{const open=(event:Event)=>{const detail=(event as CustomEvent<{game:string;query:string}>).detail;setManualGame(detail.game);setLookupId(gameBananaModId(detail.query)===null?'':detail.query);setManualOpen(true)};window.addEventListener('open-mod-query',open);return()=>window.removeEventListener('open-mod-query',open)},[])
 const busy=sending||['checking','importing'].includes(value.status)||auto?.last_run?.status==='checking'||historyStatus?.last_run?.status==='checking'
 useEffect(()=>{let disposed=false;const poll=async()=>{try{const responses=await Promise.all([fetch('/api/sync'),fetch('/api/auto-sync')]);if(responses.some(r=>!r.ok))throw Error('状态读取失败');const [sync,status]=await Promise.all(responses.map(r=>r.json()));if(!disposed){setValue(sync);setAuto(status)}}catch(e){if(!disposed)setError(String(e))}};void poll();const t=setInterval(poll,1500);return()=>{disposed=true;clearInterval(t)}},[])
 useEffect(()=>{if(['success','partial'].includes(value.status))onComplete()},[value.status,value.report?.sync_run_id])
 // The automatic worker may finish author checks after the MOD preview/apply.
 // Refresh once per completed run, including read-only check reports.
 useEffect(()=>{if(auto?.last_run?.ended_at)onComplete()},[auto?.last_run?.ended_at])
 async function send(action:string){setError('');setSending(true);try{
  const body=action==='lookup'?{action,game:Number(manualGame),item_id:gameBananaModId(lookupId)}:action==='stop'?{action}:{action,game:value.game_id,token:value.token}
  const r=await fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error);setValue(v)
 }catch(e){setError(String(e))}finally{setSending(false)}}
 const labels:Record<string,string>={not_checked:'就绪',idle:'尚未开始',checking:'正在检查',waiting:'等待确认',importing:'正在导入',success:'同步成功',partial:'部分成功',failed:'同步失败',discarded:'已放弃本次预览',stopped:'等待续扫',complete_check:'完整检查（仅本次来源末页）',incomplete:'扫描未完成',awaiting_resume:'等待续扫',rate_limited:'遇到限流',check_failed:'检查失败'}
 const autoFailed=['failed','partial','stopped'].includes(auto?.last_run?.status||'')
 const counts=(r?:Counts)=>r?`新增 ${r.inserted} · 来源更新 ${r.source_update_events} · 仅资料变化/证据不足 ${r.updated-r.source_update_events} · 无变化 ${r.unchanged} · 跳过 ${r.skipped}`:'暂无候选'
 const stats=(s?:Statistics)=>s?`原始记录 ${s.fetched} = 已分类 ${s.classified} + 重复 ${s.duplicates} + 未能分类 ${s.unclassified}；候选去重 ${s.unique} · 窗口外 ${s.out_of_window||0} · 日期缺失 ${s.missing_dates||0}`:''
 async function refresh(){setSending(true);setError('');try{const r=await fetch('/api/auto-sync/refresh',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:'{}'});const v=await r.json();if(!r.ok)throw Error(v.error);if(v.status==='requested')window.dispatchEvent(new Event('automation-configured'))}catch(e){setError(String(e))}finally{setSending(false)}}
 async function historyAction(action:string){setSending(true);setError('');try{const r=await fetch('/api/history-sync',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify({action})});const v=await r.json();if(!r.ok)throw Error(v.error)}catch(e){setError(String(e))}finally{setSending(false)}}
 return <section className={visible?'sync-inline mb-5':''}>
 <div hidden={!visible}>
  <div className="sync-inline-actions">
   <button className="small-button refresh-button" disabled={busy} onClick={refresh}>{busy?'刷新中…':'刷新MOD'}</button>
   <span>启动时刷新一次 · 自动入库</span>
   <button className="small-button" aria-expanded={expanded} aria-controls="sync-management" onClick={()=>setExpanded(true)}>更多设置</button>
   <CacheSettings/>
   {busy&&<button className="small-button" onClick={()=>{fetch('/api/auto-sync/run',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify({action:'stop'})});send('stop');historyAction('stop')}}>停止</button>}
  </div>
  <p className="sync-inline-result" role="status">{busy?`正在检查 ${value.current_game||''} · 已完成 ${value.completed||0}/${value.planned||6} 款`:auto?.last_run?.ended_at?`最近：新增 ${auto.last_run.inserted??0} · 来源更新 ${auto.last_run.source_updated??0} · 失败/待处理 ${syncFailureCount(auto.last_run)}`:value.report?`新增 ${value.report.inserted} · 来源更新 ${value.report.source_update_events} · 失败 ${value.failures?.length||0}`:'先显示本地作品，后台有界检查六游戏近90天动态'}{historyStatus?.last_run?.status==='checking'?' · 正在搜索更早历史':''}</p>
  {value.status==='waiting'&&!busy&&<p role="status">有尚未处理的精确查询或旧预览，请在{value.lookup?'高级查询':'更多设置'}中处理；本次刷新不会覆盖它。</p>}
  {(error||value.error||autoFailed)&&<p className="status-error" role="alert">{error||value.error||auto?.last_run?.error||((auto?.last_run?.author_failures||0)>0?'MOD检查已结束，作者检查有失败或待处理项，请查看更多设置':'上次检查未全部成功，可手动刷新重试或查看更多设置')}</p>}
 </div>
  <dialog className="settings-dialog" ref={manualDialog} onClose={()=>setManualOpen(false)} onCancel={()=>setManualOpen(false)}>
   <div className="settings-heading"><h2>高级查询 · GameBanana MOD</h2><button aria-label="关闭高级查询" onClick={()=>setManualOpen(false)}>✕</button></div>
   <p>选择来源游戏，粘贴 GameBanana 作品链接或 MOD ID。只获取元数据，确认前不入库，不下载 MOD 文件。</p>
   <label>游戏 <select value={manualGame} disabled={busy} onChange={e=>setManualGame(e.target.value)}><option value="">请选择游戏</option>{games.map(g=><option key={g.game_id} value={g.game_id}>{g.name}</option>)}</select></label>
   <label>作品链接或 MOD ID <input aria-label="远程 MOD ID 或链接" placeholder="https://gamebanana.com/mods/541855" value={lookupId} onChange={e=>setLookupId(e.target.value)}/></label>
   <button className="small-button refresh-button" disabled={busy||!manualGame||gameBananaModId(lookupId)===null} onClick={()=>send('lookup')}>获取预览</button>
   {busy&&<p role="status">正在处理，请稍候…</p>}
   {value.lookup_record&&<p>{value.lookup_record.title} · {value.lookup_record.author_name} · MOD {value.lookup_record.item_id}</p>}
   {value.lookup&&value.status==='waiting'&&!busy&&<><button className="small-button refresh-button" onClick={()=>send('confirm')}>确认保存到作品库</button><button className="small-button" onClick={()=>send('discard')}>放弃预览</button></>}
   {value.lookup&&['success','partial'].includes(value.status)&&<p role="status">已保存，作品列表已刷新。</p>}
   {(error||value.error)&&<p role="alert">{error||value.error}</p>}
  </dialog>
  <dialog id="sync-management" ref={settingsDialog} onClose={()=>setExpanded(false)} onCancel={()=>setExpanded(false)} className="settings-dialog sync-management">
  <div className="settings-heading"><h2>同步设置与任务详情</h2><button aria-label="关闭同步设置" onClick={()=>setExpanded(false)}>✕</button></div>
  <CharacterLibrary/>
  {value.lookup_record&&<p>来源预览：{value.lookup_record.item_id} · {value.lookup_record.title} · {value.lookup_record.author_name}（确认导入前未保存）</p>}
  <p>每次启动本地服务后自动刷新一轮；不按小时定期扫描。“刷新MOD”可再次检查并入库。网络失败保留本地数据。</p>
  <details><summary>最近运行详情</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(auto?.last_run||{},null,2)}</pre></details>
  <HistorySyncSettings mode={auto?.settings.mode} onComplete={onComplete} onStatus={setHistory}/>
  {value.status==='checking'&&<button className="small-button ml-3" disabled={sending} onClick={()=>send('stop')}>停止（当前请求结束后）</button>}
  <span className="ml-3">{labels[value.status]||value.status} · {labels[value.scan_status||'']}</span>
  {value.current_game&&<span> · {value.current_game} 第 {value.current_page} 页 · 已完成 {value.completed||0} 款</span>}
  {value.status==='waiting'&&!busy&&(value.game_id===null||value.game_id===Number(game))&&<button className="small-button ml-3" onClick={()=>send('confirm')}>确认导入{value.game_id===null?'（全部已验证候选）':''}</button>}
  {value.status==='waiting'&&!busy&&<button className="small-button ml-3" onClick={()=>send('discard')}>放弃本次预览</button>}
  <p>启动/刷新均串行检查六游戏，空库启动每游戏最多1页，其他每游戏最多3页、每页最多10条。Coverage=incomplete，不保证全站覆盖。高级查询仍需确认保存；旧预览可在这里确认或放弃。</p>
  {value.games?.map(g=><div key={g.game_id} className="mt-2"><p>{g.name} · {labels[g.scan_status||'']||g.status} · 已检查页 {g.pages?.join(', ')||'无'} · 请求 {g.requests} · {counts(g.report)} · 失败 {g.failures.length}</p><p>{stats(g.statistics)} · 缺更新时间证据 {g.missing_update_evidence??0} · 上次成功检查 {g.checkpoint?.last_success_check_at||'无'}</p>{g.failures.length>0&&<p role="alert">{JSON.stringify(g.failures)}</p>}</div>)}
  {value.games?.map(g=><p key={`timing-${g.game_id}`}>{g.name} · 无变化 {g.report?.unchanged??0} · 更新时间跳过 {g.timestamp_skipped??0} · 网络/解析 {g.network_seconds?.toFixed(3)??'未测'} 秒 · 候选比较 {g.selection_seconds?.toFixed(3)??'未测'} 秒 · 共用批次入库 {g.batch_import_seconds_shared?.toFixed(3)??'未测'} 秒</p>)}
  {value.report&&<p className="mt-2 font-medium">总计：{stats(value.statistics)} · 请求 {value.requests} · {counts(value.report)} · 失败/未执行 {value.failures?.length||0} · 已检查 {value.completed}/{value.planned} 款</p>}
  {(error||value.error)&&<p role="alert">{error||value.error}</p>}
 </dialog>
 </section>
}
