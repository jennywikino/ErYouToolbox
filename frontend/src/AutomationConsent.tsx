import {useState} from 'react'

export default function AutomationConsent({onSaved}:{onSaved:()=>void}) {
 const [mode,setMode]=useState('apply'),[busy,setBusy]=useState(false),[error,setError]=useState('')
 async function save(){
  setBusy(true);setError('')
  try{
   const headers={'Content-Type':'application/json','X-ErYouToolbox':'1'}
   // Save the lower-priority history preference first; it cannot run while the
   // existing default mode is off. Only the final explicit action enables apply.
   for(const [url,body] of [['/api/history-sync',{action:'configure',settings:{enabled:false,paused:false,max_pages:2}}],['/api/auto-sync',{mode,interval_hours:3,max_pages:3}]] as const){
    const r=await fetch(url,{method:'POST',headers,body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error||'设置保存失败')
   }
   onSaved()
  }catch(e){setError(String(e))}finally{setBusy(false)}
 }
 return <section className="automation-consent" aria-label="首次自动化设置">
  <strong>首次使用：选择自动化方式</strong><p>推荐每 3 小时检查并入库近90天作品；更早历史由你主动搜索。关闭客户端后不运行。已有个人数据不会随安装包提供。</p>
  <label>模式 <select value={mode} disabled={busy} onChange={e=>setMode(e.target.value)}><option value="off">关闭 · 手动处理</option><option value="check">仅检查 · 等待确认</option><option value="apply">检查并自动入库（需明确授权）</option></select></label>
  <button className="small-button" disabled={busy} onClick={save}>{busy?'正在保存…':mode==='apply'?'授权并保存自动入库设置':'确认并保存设置'}</button>
  {error&&<p role="alert">{error}</p>}
 </section>
}
