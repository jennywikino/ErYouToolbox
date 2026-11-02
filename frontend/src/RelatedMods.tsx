import {useEffect,useState} from 'react'
import type {Mod} from './types'
import {canShowImages,safeUrl} from './policy'
import type {Author} from './Authors'
export default function RelatedMods({mod,allowUnknown,onOpen,onAuthor,ratings}:{mod:Mod;allowUnknown:boolean;onOpen:(m:Mod)=>void;onAuthor:(a:Author)=>void;ratings?:string[]|null}){
 const [items,setItems]=useState<Mod[]>([]),[error,setError]=useState('')
 useEffect(()=>{setItems([]);setError('');if(!mod.author_id)return;const c=new AbortController();const params=new URLSearchParams({author_source:mod.source,author_id:String(mod.author_id),exclude_id:String(mod.item_id),sort:'created',limit:'4',show_unrated:allowUnknown?'1':'0'});if(ratings!=null)params.set('ratings',ratings.join(','));fetch('/api/mods?'+params,{signal:c.signal}).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.error);return v}).then(v=>setItems(v.items)).catch(e=>{if(e.name!=='AbortError')setError(String(e))});return()=>c.abort()},[mod.source,mod.item_id,mod.author_id,allowUnknown,ratings])
 if(!mod.author_id)return null
 return <section className="mt-5"><h3>该作者的其他作品</h3><button className="text-violet-700" onClick={()=>onAuthor({source:mod.source,author_id:mod.author_id!,name:mod.author_name||undefined})}>查看全部</button>{error&&<p role="alert">{error}</p>}{!error&&!items.length&&<p>暂无其他本地收录作品</p>}<div className="related-list">{items.map(item=><RelatedItem key={`${item.source}:${item.item_id}`} item={item} allowUnknown={allowUnknown} onOpen={()=>onOpen(item)}/>)}</div></section>
}

function RelatedItem({item,allowUnknown,onOpen}:{item:Mod;allowUnknown:boolean;onOpen:()=>void}){
 const [failed,setFailed]=useState(false)
 const url=canShowImages(item.content_rating_status,allowUnknown)?safeUrl(item.preview_urls[0]):null
 return <button className="related-item" onClick={onOpen} aria-label={`查看详情：${item.title||item.item_id}`}><span className="related-cover">{url&&!failed?<img src={url} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={()=>setFailed(true)}/>:<span>暂无预览</span>}</span><span className="line-clamp-2">{item.title||'暂无标题'}</span></button>
}
