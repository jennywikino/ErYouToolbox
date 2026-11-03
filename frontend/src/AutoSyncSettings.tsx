import {useEffect,useState} from 'react'
type Settings={mode:string;interval_hours:number;max_pages:number}
export type AutoStatus={settings:Settings;configured?:boolean;next_due:string|null;task:{status?:string;registered?:boolean;enabled?:boolean;next_run?:string;interval_hours?:number;error?:string};last_run?:{status:string;started_at:string;ended_at?:string;inserted?:number;source_updated?:number;failures?:unknown[];coverage?:string;error?:string;requests?:number}}
export default function AutoSyncSettings({visible=true,onStatus,onError}:{visible?:boolean;onStatus?:(v:AutoStatus|null)=>void;onError?:(e:string)=>void}){
 const [data,setData]=useState<AutoStatus|null>(null),[draft,setDraft]=useState<Settings>({mode:'off',interval_hours:6,max_pages:3}),[error,setError]=useState(''),[saving,setSaving]=useState(false)
 useEffect(()=>{let stopped=false,first=true;const poll=async()=>{try{const r=await fetch('/api/auto-sync');const v=await r.json();if(!r.ok)throw Error(v.error);if(!stopped){setData(v);setError('');if(first){setDraft(v.settings);first=false}}}catch(e){if(!stopped)setError(String(e))}};const startupError=(e:Event)=>setError((e as CustomEvent<string>).detail);const configured=()=>{first=true;void poll()};window.addEventListener('automation-configured',configured);poll();const timer=setInterval(poll,3000);window.addEventListener('auto-sync-error',startupError);return()=>{stopped=true;clearInterval(timer);window.removeEventListener('automation-configured',configured);window.removeEventListener('auto-sync-error',startupError)}},[])
 useEffect(()=>{onStatus?.(data)},[data,onStatus])
 useEffect(()=>{onError?.(error)},[error,onError])
 async function save(){if(draft.mode==='apply'&&data?.settings.mode!=='apply'&&!window.confirm('启用自动入库后，已注册的本机任务及立即运行可自动写入新作品和可靠来源更新。请先完成小样本验收。继续保存？'))return
  setSaving(true);setError('');try{const r=await fetch('/api/auto-sync',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify(draft)});const v=await r.json();if(!r.ok)throw Error(v.error);setData(v)}catch(e){setError(String(e))}finally{setSaving(false)}}
 async function run(){setSaving(true);setError('');try{const r=await fetch('/api/auto-sync/run',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:'{}'});const v=await r.json();if(!r.ok)throw Error(v.error)}catch(e){setError(String(e))}finally{setSaving(false)}}
 return <div hidden={!visible} className="mb-3 border-b border-slate-200 pb-3 text-sm"><label>自动同步 <select aria-label="自动同步模式" value={draft.mode} onChange={e=>setDraft({...draft,mode:e.target.value})}><option value="off">关闭（手动模式）</option><option value="check">自动检查</option><option value="apply">自动检查并入库</option></select></label>
 <label className="ml-3">间隔 <input aria-label="自动同步间隔小时" className="w-14" type="number" min={1} max={168} value={draft.interval_hours} onChange={e=>setDraft({...draft,interval_hours:Number(e.target.value)})}/> 小时</label>
 <label className="ml-3">每游戏页数 <select value={draft.max_pages} aria-label="自动同步页数" onChange={e=>setDraft({...draft,max_pages:Number(e.target.value)})}>{Array.from({length:10},(_,i)=><option key={i+1}>{i+1}</option>)}</select></label>
 <button className="small-button ml-3" disabled={saving} onClick={save}>保存设置</button><button className="small-button ml-3" disabled={saving||!data||data.settings.mode==='off'} onClick={run}>按已保存模式立即运行</button>
 <p>{data?.task.status==='unsupported'?'便携版设置保存在 userdata；支持客户端打开期间按到期时间检查及立即运行，关闭后不执行后台任务。':'本机设置持久保存；网页不注册计划任务。启用或调整计划间隔后须手动注册/更新本机任务。关闭会阻止后续检查，不强制打断已开始的事务。'}</p>
 {data&&<><p>计划任务：{data.task.registered===false?'未注册':data.task.registered===true?(data.task.enabled?'已注册 · 已启用':'已注册 · 已禁用'):'状态未知'} · 上次检查：{data.last_run?.started_at||'无'} · 当前状态：{data.last_run?.status==='preview_resolved'?'预览已处理，可重新运行':data.last_run?.status||'尚未开始'}</p><p>下次允许检查：{data.next_due||'关闭'} · 下次计划触发：{data.task.next_run||'暂无（请查询任务）'}</p>
 {data.task.status==='unsupported'?<p>便携客户端打开期间每分钟检查到期状态，沿用服务端间隔和限流；关闭后的后台计划任务尚不支持。现有 Web 版计划任务不会操作此便携数据目录。</p>:data.task.registered===false&&<p>保存配置不等于注册任务。请在项目根目录使用项目虚拟环境运行 scripts/manage_auto_sync.py register；未注册时不会定期触发，可使用立即运行。</p>}
 {data.last_run&&<p>新增 {data.last_run.inserted??0} · 来源更新 {data.last_run.source_updated??0} · 失败 {data.last_run.failures?.length??(data.last_run.error?1:0)} · 请求 {data.last_run.requests??0} · Coverage={data.last_run.coverage||'incomplete'}</p>}
 {data.task.interval_hours!==undefined&&data.task.interval_hours!==data.settings.interval_hours&&<p>计划间隔与保存设置不同，请重新运行任务注册命令。</p>}
 {(data.task.error||data.last_run?.error)&&<p role="alert">{data.task.error||data.last_run?.error}</p>}</>}
 {error&&<p role="alert">{error}</p>}</div>
}

