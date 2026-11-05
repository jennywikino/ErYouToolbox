import {useRef,useState} from 'react'

type SourceMeta={source:string;version:string;revision:string;synced_at:string}
type Library={format:number;games:Record<string,Record<string,string[]>>;backups:string[];external_meta:SourceMeta|null;external_counts:Record<string,number>}
type Preview={token:string;changes:{game:number;name:string;before:string[]|null;after:string[]|null}[];layer_counts:{external:number;imported:number;personal:number};note:string;external_meta?:SourceMeta|null}
const games=[['8552','原神'],['18366','崩铁'],['19567','绝区零'],['20357','鸣潮'],['21842','终末地'],['23012','异环']]
export default function CharacterLibrary(){
 const dialog=useRef<HTMLDialogElement>(null)
 const [data,setData]=useState<Library|null>(null),[game,setGame]=useState('8552'),[search,setSearch]=useState(''),[name,setName]=useState(''),[aliases,setAliases]=useState(''),[url,setUrl]=useState(''),[backup,setBackup]=useState(''),[preview,setPreview]=useState<Preview|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[page,setPage]=useState(0)
 async function load(){const r=await fetch('/api/character-library');const v:Library&{error?:string}=await r.json();if(!r.ok)throw Error(v.error);setData(v)}
 async function open(){dialog.current?.showModal();setError('');try{await load()}catch(e){setError(String(e))}}
 async function send(body:unknown,confirm=false){setBusy(true);setError('');setMessage('');try{
  const r=await fetch('/api/character-library',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error)
  if(confirm){setPreview(null);await load();setMessage('名称库已保存，下一次搜索立即生效；无需重启。')}else if(v.status==='unchanged'){setPreview(null);setMessage(v.note)}else setPreview(v)
 }catch(e){setError(String(e))}finally{setBusy(false)}}
 async function file(file?:File){if(!file)return;try{if(file.size>512*1024)throw Error('文件超过512 KiB');await send({action:'import',document:JSON.parse(await file.text())})}catch(e){setError(String(e))}}
 function exportNames(){if(!data)return;const blob=new Blob([JSON.stringify({format:1,games:data.games},null,2)],{type:'application/json'});const href=URL.createObjectURL(blob);const a=document.createElement('a');a.href=href;a.download='character-names-v1.json';a.click();URL.revokeObjectURL(href)}
 const entries=Object.entries(data?.games[game]||{}).filter(([n,a])=>[n,...a].some(s=>s.toLowerCase().includes(search.toLowerCase())))
 return <><button className="small-button" onClick={open}>角色名称库</button><dialog className="settings-dialog" ref={dialog}>
  <div className="settings-heading"><h2>角色名称库</h2><button aria-label="关闭角色名称库" onClick={()=>dialog.current?.close()}>✕</button></div>
  <p>个人修正 ＞ 已验证导入 ＞ 外部同步 ＞ 内置词库。只扩展名称匹配，不会创建 MOD；词库匹配成功但本地无作品时仍显示空结果。</p>
  <section><strong>外部来源：Moonholder/JASM-GameAssets</strong><p>版本：{data?.external_meta?.version||'尚未同步'} · 最近成功同步：{data?.external_meta?.synced_at||'无'}</p><p>{games.map(([id,n])=>`${n} ${data?.external_counts[id]??0}`).join(' · ')}（外部中文检索键；异环使用本地数据）</p><button className="small-button" disabled={busy} onClick={()=>send({action:'jasm'})}>手动同步角色库（预览）</button><p>只读取manifest及五游戏名称JSON，不下载图片；与MOD刷新独立，无定期更新。</p></section>
  <label>游戏 <select value={game} onChange={e=>{setGame(e.target.value);setPage(0);setName('');setAliases('')}}>{games.map(([id,n])=><option key={id} value={id}>{n}</option>)}</select></label>
  <label> 查找名称 <input value={search} onChange={e=>{setSearch(e.target.value);setPage(0)}}/></label>
  <div style={{maxHeight:240,overflow:'auto'}}>{entries.slice(page*20,page*20+20).map(([n,a])=><div key={n} style={{display:'flex',gap:8,marginBlock:6,overflowWrap:'anywhere'}}>
   <button className="small-button" onClick={()=>{setName(n);setAliases(a.join('\n'))}}>{n}</button><span style={{flex:1}}>{a.join(' / ')}</span><button className="small-button" disabled={busy} onClick={()=>send({action:'edit',game,name:n,aliases:null})}>删除预览</button>
  </div>)}</div>
  <p>{entries.length} 个名称 · 第 {page+1} 页 <button disabled={!page} onClick={()=>setPage(page-1)}>上一页</button> <button disabled={(page+1)*20>=entries.length} onClick={()=>setPage(page+1)}>下一页</button></p>
  <label>名称 <input maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label>
  <label> 别名（每行一个）<textarea value={aliases} onChange={e=>setAliases(e.target.value)}/></label>
  <button className="small-button" disabled={busy||!name} onClick={()=>send({action:'edit',game,name,aliases:aliases.split('\n').map(s=>s.trim()).filter(Boolean)})}>新增 / 修改预览</button>
  <hr/><p>统一格式：format=1，games 为游戏 ID → 名称 → 别名数组。上限512 KiB / 3000条。</p>
  <label>导入本地 JSON <input type="file" accept=".json,application/json" disabled={busy} onChange={e=>{void file(e.target.files?.[0]);e.target.value=''}}/></label>
  <label>GitHub 原始 JSON URL <input style={{width:'100%'}} placeholder="https://raw.githubusercontent.com/owner/repo/ref/names.json" value={url} onChange={e=>setUrl(e.target.value)}/></label>
  <button className="small-button" disabled={busy||!url} onClick={()=>send({action:'url',url})}>手动获取并预览</button> <button className="small-button" onClick={exportNames}>导出有效词库</button>
  <p>每次修改前自动备份外部、导入及个人层；不修改数据库、已阅或关注。重置恢复内置及受保护官方名称。</p>
  <select aria-label="名称库备份" value={backup} onChange={e=>setBackup(e.target.value)}><option value="">选择备份</option>{data?.backups.map(b=><option key={b}>{b}</option>)}</select>
  <button className="small-button" disabled={busy||!backup} onClick={()=>send({action:'restore',backup})}>恢复预览</button> <button className="small-button" disabled={busy} onClick={()=>send({action:'reset'})}>重置预览</button>
  {preview&&<section><h3>待确认：{preview.changes.length} 项有效名称变更</h3><p>{preview.note}</p>{preview.external_meta&&<p>目标外部版本：{preview.external_meta.version}</p>}<p>外部变更 {preview.layer_counts.external} · 导入层变更 {preview.layer_counts.imported} · 个人层变更 {preview.layer_counts.personal}</p><div style={{maxHeight:180,overflow:'auto'}}>{preview.changes.map(c=><p key={`${c.game}/${c.name}`}>{c.game} · {c.name}：{c.before?.join(' / ')||'无'} → {c.after?.join(' / ')||'删除'}</p>)}</div><button disabled={busy} onClick={()=>send({action:'confirm',token:preview.token},true)}>确认保存名称库</button> <button onClick={()=>setPreview(null)}>放弃</button></section>}
  {busy&&<p role="status">正在处理…</p>}{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
 </dialog></>
}
