import {useEffect,useState} from 'react'
type Entry={category:string;subcategory:string|null;count:number}
export default function CategorySidebar({game,category,subcategory,revision,onSelect,disabled=false}:{game:string;category:string;subcategory:string;revision:number;onSelect:(category:string,subcategory:string)=>void;disabled?:boolean}){
 const [items,setItems]=useState<Entry[]>([]),[search,setSearch]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 useEffect(()=>{const c=new AbortController();setBusy(true);fetch('/api/categories?'+new URLSearchParams({game}),{signal:c.signal}).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.error);return v}).then(v=>{setItems(v.items);setError('')}).catch(e=>{if(e.name!=='AbortError')setError(String(e))}).finally(()=>{if(!c.signal.aborted)setBusy(false)});return()=>c.abort()},[game,revision])
 const grouped=new Map<string,number>()
 for(const item of items){const name=category?item.category===category?item.subcategory:null:item.category;if(name)grouped.set(name,(grouped.get(name)||0)+item.count)}
 return <section className="category-browser" aria-label="本地分类导航"><h2>分类索引</h2><p>本地收录数量 · 当前游戏全部作品，非全站统计</p>
  {disabled?<p>热门榜来自远程。分类索引请在本地作品库使用。</p>:<><input aria-label="搜索分类" placeholder="搜索已保存分类" value={search} onChange={e=>setSearch(e.target.value)}/>
  {category&&<button className="back-link" onClick={()=>onSelect(subcategory?category:'','')}>← {subcategory?'返回 '+category:'全部分类'}</button>}
  <div className="category-scroll">{[...grouped].filter(([name])=>name.toLowerCase().includes(search.toLowerCase())).map(([name,count])=><button key={name} aria-pressed={category?subcategory===name:false} className={subcategory===name?'selected':''} onClick={()=>{setSearch('');onSelect(category||name,category?name:'')}}><span>{name}</span><span>{count}</span></button>)}
  {busy&&<p role="status">读取分类…</p>}{!busy&&grouped.size===0&&<p>暂无更多已保存分类</p>}</div></>}
  {error&&<p role="alert">{error}</p>}
 </section>
}
