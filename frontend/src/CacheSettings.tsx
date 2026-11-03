import {useEffect,useRef,useState} from 'react'
type Category={id:string;name:string;bytes:number;files:number;allowed:boolean;scope:string}
export default function CacheSettings(){
 const [open,setOpen]=useState(false),[data,setData]=useState<{categories:Category[];last_cleared_at:string|null}|null>(null),[selected,setSelected]=useState<string[]>(['memory']),[error,setError]=useState(''),[busy,setBusy]=useState(false),[result,setResult]=useState('')
 const dialog=useRef<HTMLDialogElement>(null)
 async function load(){const r=await fetch('/api/cache');const v=await r.json();if(!r.ok)throw Error(v.error);setData(v)}
 useEffect(()=>{if(!open)return;dialog.current?.showModal();load().catch(e=>setError(String(e)))},[open])
 async function clear(){setBusy(true);setError('');setResult('');try{
  async function send(body:unknown){const r=await fetch('/api/cache',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error);return v}
  const preview=await send({action:'preview',categories:selected})
  const names=data?.categories.filter(c=>selected.includes(c.id)).map(c=>c.name).join('、')
  if(!window.confirm(`将清理：${names}\n过期资料文件 ${preview.files.length} 个。\n保留数据库、已阅、关注、检查点与备份。继续？`))return
  const saved=await send({action:'clear',token:preview.token});setResult(saved.status==='success'?'缓存清理完成':'部分缓存未清理：'+JSON.stringify(saved.errors));await load()
 }catch(e){setError(String(e))}finally{setBusy(false)}}
 return <><button className="small-button" onClick={()=>setOpen(true)}>缓存管理</button><dialog className="settings-dialog" ref={dialog} onClose={()=>setOpen(false)} onCancel={()=>setOpen(false)}>
  <div className="settings-heading"><h2>缓存管理</h2><button onClick={()=>dialog.current?.close()} aria-label="关闭缓存管理">✕</button></div>
  <p>清理缓存不会清空已阅或删除作品。WebView统计包含网页资料；实际只清理官方磁盘缓存。</p>
  {data?.categories.map(c=><label className="cache-category" key={c.id}><input type="checkbox" disabled={!c.allowed||busy} checked={selected.includes(c.id)} onChange={e=>setSelected(e.target.checked?[...selected,c.id]:selected.filter(id=>id!==c.id))}/><span><strong>{c.name}</strong><small>{c.files} 个文件/条目 · {(c.bytes/1048576).toFixed(2)} MB</small><small>{c.scope}</small></span></label>)}
  <p>上次清理：{data?.last_cleared_at||'尚未清理'}</p><button className="small-button" disabled={busy||!selected.length||!data} onClick={clear}>{busy?'正在处理…':'预览并确认清理'}</button>
  {error&&<p role="alert">{error}</p>}{result&&<p role="status">{result}</p>}
 </dialog></>
}
