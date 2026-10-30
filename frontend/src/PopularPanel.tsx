import {useEffect,useState,useRef} from 'react'
import type {Game,Mod} from './types'
import PreviewCard from './PreviewCard'
import {safeUrl,syncTimeLabel} from './policy'
type Board={items:Mod[];fetched_at:string;cached:boolean;has_more:boolean;coverage?:string;pages_scanned?:number;candidate_count?:number;missing_metrics?:number;errors?:string[];cutoff?:string}
export type PopularView={sort:string;scope:string;days:number;maxPages:number;groups:Record<string,{loaded:boolean;page:number}>}
function Group({game,sort,search,ratings,allowUnknown,onOpen,scope,days,maxPages,group,onGroupChange,paused}:{game:Game;sort:string;search:string;ratings:string[]|null;allowUnknown:boolean;onOpen:(mod:Mod)=>void;scope:string;days:number;maxPages:number;group:{loaded:boolean;page:number};onGroupChange:(value:{loaded:boolean;page:number})=>void;paused:boolean}){
  const {loaded,page}=group
  const setLoaded=(value:boolean)=>onGroupChange({...group,loaded:value})
  const setPage=(value:number)=>onGroupChange({...group,page:value})
  const [revision,setRevision]=useState(0)
  const [data,setData]=useState<Board|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[remote,setRemote]=useState<Mod|null>(null)
  const [lastSuccess,setLastSuccess]=useState<string|null>(null)
  const refreshSent=useRef(0)
  const dataKey=useRef('')
  useEffect(()=>{if(!loaded||paused)return;const key=JSON.stringify([page,sort,allowUnknown,revision,game.game_id,scope,days,maxPages]);if(data&&dataKey.current===key)return;const c=new AbortController();setBusy(true);setError('');setData(null)
    const refresh=revision>refreshSent.current;refreshSent.current=revision
    const params=new URLSearchParams({game:String(game.game_id),sort,scope,days:String(days),max_pages:String(maxPages),page:String(page),limit:'20',show_unrated:allowUnknown?'1':'0',refresh:refresh?'1':'0'})
    fetch('/api/popular?'+params,{signal:c.signal}).then(async r=>{const value=await r.json();if(!r.ok)throw Error(value.error);return value}).then(value=>{dataKey.current=key;setData(value);setLastSuccess(value.fetched_at)})
      .catch(e=>{if(e.name!=='AbortError')setError(e.message)}).finally(()=>{if(!c.signal.aborted)setBusy(false)})
    return()=>c.abort()
  },[loaded,page,sort,allowUnknown,revision,game.game_id,scope,days,maxPages,paused])
  const items=data?.items.filter(m=>(!search||[m.title,m.author_name,String(m.item_id)].some(s=>s?.toLowerCase().includes(search.toLowerCase())))&&(ratings===null||m.source_ratings?.codes.some(code=>ratings.includes(code))))||[]
  return <section className="mb-8" data-ranking-game={game.game_id} data-ranking-ready={!busy&&!!(data||error)}>
    <h2 className="mb-3 text-lg font-semibold">{game.name}</h2>
    {!loaded?<button className="small-button" onClick={()=>setLoaded(true)}>加载该游戏榜单</button>:<>
      <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <button className="small-button" disabled={busy||page<=1} onClick={()=>{setRevision(0);setPage(page-1)}}>上一页</button><span>{scope==='recent'?'候选榜单':'来源'}第 {page} 页</span>
        <button className="small-button" disabled={busy||!data?.has_more} onClick={()=>{setRevision(0);setPage(page+1)}}>下一页</button>
        <button className="small-button" disabled={busy} onClick={()=>setRevision(v=>v+1)}>手动刷新</button>
        {lastSuccess&&<span>最后成功获取 {syncTimeLabel(lastSuccess)}{data?.cached?' · 缓存':''}</span>}
      </div>
      {busy&&<p role="status">正在读取来源榜单…</p>}{error&&<p role="alert" className="error-banner">{error}</p>}
      {scope==='recent'&&data&&<div className="mb-4 text-xs leading-6 text-slate-500"><p>coverage={data.coverage} · 扫描 {data.pages_scanned} 页 · 窗口内去重候选 {data.candidate_count} 条 · 指标缺失 {data.missing_metrics} 条</p><p>窗口起点 {syncTimeLabel(data.cutoff)} · 即使观察到边界，也不保证榜单完整无遗漏。</p>{data.errors?.map((message,i)=><p key={i} role="alert" className="text-red-600">扫描中断：{message}</p>)}</div>}
      {remote&&<div className="mb-4 rounded-lg border border-violet-100 p-4 text-sm"><button className="small-button" onClick={()=>setRemote(null)}>关闭来源信息</button><h3 className="my-2 font-semibold">{remote.title}</h3><p>{remote.author_name} · {remote.game_name} · MOD {remote.item_id}</p><p>尚未收录，以上为来源列表信息；浏览不会入库。</p>{safeUrl(remote.original_url)&&<a className="text-violet-700" href={safeUrl(remote.original_url)!} target="_blank" rel="noopener noreferrer">打开原站 ↗</a>}</div>}
      <div className="mod-grid">{items.map(m=><PreviewCard key={`${m.item_id}:${allowUnknown}`} mod={m} allowUnknown={allowUnknown} onOpen={()=>m.is_local?onOpen(m):setRemote(m)}/>)}</div>
      {data&&!items.length&&<p className="my-4 text-sm text-slate-500">{scope==='recent'&&sort==='downloads'?'暂无可靠下载量数据。':'当前页没有符合筛选条件且具有所选指标的作品。'}</p>}
    </>}
  </section>
}
export default function PopularPanel(props:{games:Game[];game:string;search:string;ratings:string[]|null;allowUnknown:boolean;onOpen:(mod:Mod)=>void;view:PopularView;onViewChange:(value:PopularView)=>void;paused:boolean}){
  const {sort,scope,days,maxPages}=props.view
  const setSort=(value:string)=>props.onViewChange({...props.view,sort:value,groups:{}})
  const setScope=(value:string)=>props.onViewChange({...props.view,scope:value,groups:{}})
  const setDays=(value:number)=>props.onViewChange({...props.view,days:value,groups:{}})
  const setMaxPages=(value:number)=>props.onViewChange({...props.view,maxPages:value,groups:{}})
  return <>
    <h1 className="mb-3 text-2xl font-semibold">热门 MOD</h1>
    <div className="mb-4 flex gap-3"><button className="small-button" aria-pressed={scope==='recent'} onClick={()=>setScope('recent')}>近期发布</button><button className="small-button" aria-pressed={scope==='history'} onClick={()=>setScope('history')}>历史累计</button></div>
    {scope==='recent'&&<div className="mb-4 flex gap-4 text-sm"><label>发布时间窗口 <select aria-label="近期时间窗口" value={days} onChange={e=>setDays(Number(e.target.value))}>{[7,30,90].map(n=><option key={n} value={n}>{n} 天</option>)}</select></label><label>扫描上限 <select aria-label="近期扫描页数上限" value={maxPages} onChange={e=>setMaxPages(Number(e.target.value))}>{[1,2,3,4,5].map(n=><option key={n} value={n}>{n} 页</option>)}</select></label></div>}
    <p className="mb-4 text-xs leading-6 text-slate-500">{scope==='recent'?'近期发布作品的累计热度排序，候选来自 Generic_Newest 有界扫描；不是官方近期热度增长榜。每次扫描每页最多 50 条，未观察到时间边界时 coverage=incomplete。':'GameBanana 历史累计来源榜单，保留来源排名。'} 缓存 30 分钟；搜索与分级只筛当前展示页。缺少具体分级标签时显示 UNKNOWN；无可靠下载量时显示暂无数据。</p>
    <select className="mb-5 rounded border p-2 text-sm" aria-label="热门排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="likes">最多喜欢</option><option value="views">最多浏览</option><option value="downloads">最多下载</option></select>
    {!props.game&&<p className="mb-5 text-xs text-slate-500">全部游戏按游戏分组，点击加载；不合成跨游戏排名。</p>}
    {props.games.filter(g=>!props.game||String(g.game_id)===props.game).map(g=><Group key={`${g.game_id}:${sort}:${props.game}:${scope}:${days}:${maxPages}`} {...props} game={g} group={props.view.groups[g.game_id]??{loaded:!!props.game,page:1}} onGroupChange={value=>props.onViewChange({...props.view,groups:{...props.view.groups,[g.game_id]:value}})} sort={sort} scope={scope} days={days} maxPages={maxPages}/>)}
  </>
}
