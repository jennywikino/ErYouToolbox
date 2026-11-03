import {MyAuthors,AuthorHeader,type Author} from './Authors'
import SyncCheck from './SyncCheck'
import {requestStartupCheck,requestDueCheck} from './autoStartup'
import { useEffect, useState, useRef, type FormEvent } from 'react'
import type { Game, Mod, ModPage } from './types'
import Icon from './Icons'
import PreviewCard from './PreviewCard'
import ModDetail from './ModDetail'
import AuthorUpdateCheck from './AuthorUpdateCheck'
import RatingEnrichment from './RatingEnrichment'
import CategorySidebar from './CategorySidebar'
import PopularPanel, {type PopularView} from './PopularPanel'
import { syncTimeLabel, syncStatusLabel, restoreScrollTop, restorePopularView, validBrowseSnapshot, listingPreferences, resizedPage, imagePreferenceQuery, imagePreferences } from './policy'

const LISTING_KEY='eryouListing'
function savedListing(){try{return listingPreferences(JSON.parse(localStorage.getItem(LISTING_KEY)||'null'))}catch{return listingPreferences(null)}}

async function read<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url+(/^\/api\/mods?\?/.test(url)?imagePreferenceQuery():''), { signal })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || `读取失败：HTTP ${response.status}`)
  return data as T
}

function detailIdentity(hash: string) {
  const parts = hash.slice(1).split('/')
  if (parts.length !== 5 || parts[1] !== 'mod') return null
  try {
    return { source: decodeURIComponent(parts[2]), item_type: decodeURIComponent(parts[3]), item_id: parts[4] }
  } catch { return null }
}

export default function App() {
  const [games, setGames] = useState<Game[]>([])
  const [game, setGame] = useState('')
  const [category,setCategory]=useState(''),[subcategory,setSubcategory]=useState('')
  const [author,setAuthor]=useState<Author|null>(null)
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('created')
  const [feed, setFeed] = useState('latest')
  const [popular,setPopular]=useState<PopularView>({sort:'likes',scope:'recent',days:30,maxPages:2,groups:{}})
  const [feedRevision, setFeedRevision] = useState(0)
  const [readFilter,setReadFilter]=useState('all')
  const [page, setPage] = useState(0)
  const [viewMode,setViewMode]=useState(()=>savedListing().viewMode)
  const [pageSize,setPageSize]=useState(()=>savedListing().pageSize)
  const gridRef=useRef<HTMLDivElement>(null)
  const [firstRow,setFirstRow]=useState(3)
  const [withImages, setWithImages] = useState(false)
  const [allowUnknown, setAllowUnknown] = useState(() => localStorage.getItem("showPreviewImages") !== "0")
  const [extraImages,setExtraImages]=useState(imagePreferences)
  const [ratingsOpen,setRatingsOpen]=useState(false)
  const [ratingOptions, setRatingOptions] = useState<{_sAlias: string; _sTitle: string}[]>([])
  const [ratings, setRatings] = useState<string[] | null>(null)
  const [data, setData] = useState<ModPage | null>(null)
  const [error, setError] = useState('')
  const [configError, setConfigError] = useState('')
  const [hash, setHash] = useState(window.location.hash)
  const [detail, setDetail] = useState<Mod | null>(null)
  const [detailError, setDetailError] = useState('')
  const [loading, setLoading] = useState(false)
  const [revision, setRevision] = useState(0)
  const identity = detailIdentity(hash)
  const isDetail = identity !== null
  const listRef=useRef<HTMLDivElement>(null)
  const [renderKey,setRenderKey]=useState('')
  const listKey=JSON.stringify([feed,game,search,sort,ratings,readFilter,page,pageSize,withImages,allowUnknown,author,category,subcategory])
  const currentView={feed,game,draft,search,sort,ratings,readFilter,page,pageSize,viewMode,withImages,allowUnknown,popular,author,category,subcategory}
  const viewRef=useRef(currentView);viewRef.current=currentView
  type SavedView=typeof currentView & {scrollY:number;anchor:string;anchorTop:number;anchorGame?:number}
  const pendingRestore=useRef<SavedView|null>(null)
  const applyView=(v:SavedView)=>{setCategory(v.category||'');setSubcategory(v.subcategory||'');setAuthor(v.author||null);setFeed(v.feed);setGame(v.game);setDraft(v.draft);setSearch(v.search);setSort(v.sort);setRatings(v.ratings);setReadFilter(v.readFilter);setPage(v.page);setPageSize(v.pageSize);setViewMode(v.viewMode);setWithImages(v.withImages);setAllowUnknown(v.allowUnknown);setPopular(v.popular)}
  const resetList=(leaveAuthor=false)=>{pendingRestore.current=null;history.replaceState({...history.state,eryouView:null},'');window.location.hash=!leaveAuthor&&viewRef.current.author?`#/author/${encodeURIComponent(viewRef.current.author.source)}/${viewRef.current.author.author_id}`:'';window.scrollTo({top:0,behavior:'instant'})}
  const returnToList=()=>{if(history.state?.eryouView){history.back()}else resetList()}
  const refreshLibrary=()=>{
    if(!isDetail&&feed!=='popular'&&!pendingRestore.current){
      const anchor=Array.from(listRef.current?.querySelectorAll<HTMLElement>('[data-mod-identity]')||[]).find(el=>el.getBoundingClientRect().bottom>0)
      pendingRestore.current={...viewRef.current,scrollY:window.scrollY,anchor:anchor?.dataset.modIdentity||'',anchorTop:anchor?.getBoundingClientRect().top||0}
    }
    setFeedRevision(v=>v+1)
  }

  // Independent of library queries; never delay local first paint or cancel a
  // server-owned job when navigating away from this page.
  useEffect(()=>{
    let pending=false
    const error=(e:unknown)=>window.dispatchEvent(new CustomEvent('auto-sync-error',{detail:String(e)}))
    requestStartupCheck().catch(error)
    const timer=setInterval(()=>{if(pending)return;pending=true;requestDueCheck(fetch).catch(error).finally(()=>{pending=false})},60000)
    return()=>clearInterval(timer)
  },[])
  useEffect(()=>{try{localStorage.setItem(LISTING_KEY,JSON.stringify({viewMode,pageSize}))}catch{/* Storage may be disabled; browsing still works. */}},[viewMode,pageSize])
  useEffect(()=>{
    if(!gridRef.current||feed==='popular'||isDetail)return
    const grid=gridRef.current
    const update=()=>setFirstRow(Math.max(1,getComputedStyle(grid).gridTemplateColumns.split(/\s+/).length))
    update();const observer=new ResizeObserver(update);observer.observe(grid)
    return()=>observer.disconnect()
  },[viewMode,feed,isDetail])

  useEffect(() => {
    const controller = new AbortController()
    read<{ games: Game[] }>('/api/games', controller.signal).then(value => setGames(value.games))
      .catch(error => { if (error.name !== 'AbortError') setConfigError('游戏配置读取失败：' + error.message) })
    read<{options: {_sAlias: string; _sTitle: string}[]}>('/api/content-ratings', controller.signal)
      .then(value => setRatingOptions(value.options))
      .catch(error => { if (error.name !== 'AbortError') setConfigError('分级配置读取失败：' + error.message) })
    const previousScroll=history.scrollRestoration;history.scrollRestoration='manual'
    const onHash = () => {
      const old=validBrowseSnapshot(history.state?.eryouView)?history.state.eryouView as SavedView:undefined
      const preferences=listingPreferences({...savedListing(),...old})
      const v=old?{...old,...preferences,page:old.pageSize?old.page:Math.floor(old.page*18/preferences.pageSize),author:old.author||null,category:old.category||'',subcategory:old.subcategory||'',popular:restorePopularView(old.popular)}:undefined
      if(v){applyView(v);pendingRestore.current=v}
      if(!v&&window.location.hash.startsWith('#/author/')){const parts=window.location.hash.split('/');const id=Number(parts[3]);if(Number.isSafeInteger(id)&&id>0){setAuthor({source:decodeURIComponent(parts[2]),author_id:id});setFeed('latest')}}
      setHash(window.location.hash)
      if(window.location.hash.includes('/mod/'))window.scrollTo({top:0,behavior:'instant'})
    }
    window.addEventListener('hashchange', onHash)
    window.addEventListener('popstate',onHash);onHash()
    return () => { controller.abort();history.scrollRestoration=previousScroll;window.removeEventListener('popstate',onHash);window.removeEventListener('hashchange', onHash) }
  }, [])

  useEffect(() => {
    if (feed === 'popular' || isDetail) return
    const controller = new AbortController()
    const params = new URLSearchParams({
      game, search, sort, feed, read:readFilter, limit: String(pageSize), offset: String(page * pageSize),
      with_images: withImages ? '1' : '0', show_unrated: allowUnknown ? '1' : '0',
    })
    if(author){params.set('author_source',author.source);params.set('author_id',String(author.author_id))}
    if(category)params.set('category',category)
    if(subcategory)params.set('subcategory',subcategory)
    if (ratings !== null) params.set("ratings", ratings.join(","))
    setLoading(true); setError('')
    read<ModPage>('/api/mods?' + params, controller.signal).then(value=>{if(controller.signal.aborted)return;setRenderKey(listKey);setData(value);const last=Math.max(0,Math.ceil(value.total_count/pageSize)-1);if(page>last)setPage(last)})
      .catch(error => { if (error.name !== 'AbortError') setError(error.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [game, search, sort, page, pageSize, withImages, allowUnknown, revision, ratings, feed, feedRevision,readFilter,isDetail,author,category,subcategory])

  useEffect(()=>{
    const saved=pendingRestore.current
    if(isDetail||!saved||Object.entries(viewRef.current).some(([key,value])=>JSON.stringify(value)!==JSON.stringify(saved[key as keyof SavedView])))return
    let timer:number|undefined,frame=0,stopped=false
    const restore=()=>{
      if(stopped)return
      if(feed==='popular'){
        const groups=Array.from(listRef.current?.querySelectorAll<HTMLElement>('[data-ranking-game]')||[])
        if(!groups.some(el=>(!saved.anchorGame||el.dataset.rankingGame===String(saved.anchorGame))&&el.dataset.rankingReady==='true'))return
      }else if(loading||renderKey!==listKey)return
      const anchor=Array.from(listRef.current?.querySelectorAll<HTMLElement>('[data-mod-identity]')||[]).find(el=>el.dataset.modIdentity===saved.anchor)
      window.scrollTo({top:restoreScrollTop(anchor?.getBoundingClientRect().top??null,scrollY,saved.anchorTop,saved.scrollY),behavior:'instant'})
      if(timer===undefined)timer=window.setTimeout(stop,2000)
    }
    frame=requestAnimationFrame(()=>{restore();frame=requestAnimationFrame(restore)})
    const observer=new ResizeObserver(restore);if(listRef.current)observer.observe(listRef.current)
    const mutation=new MutationObserver(restore);if(listRef.current)mutation.observe(listRef.current,{childList:true,subtree:true,attributes:true,attributeFilter:['data-ranking-ready']})
    const stop=()=>{stopped=true;pendingRestore.current=null;observer.disconnect();mutation.disconnect();cancelAnimationFrame(frame)}
    window.addEventListener('wheel',stop,{once:true});window.addEventListener('pointerdown',stop,{once:true});window.addEventListener('keydown',stop,{once:true})
    return()=>{stopped=true;clearTimeout(timer);observer.disconnect();mutation.disconnect();cancelAnimationFrame(frame);window.removeEventListener('wheel',stop);window.removeEventListener('pointerdown',stop);window.removeEventListener('keydown',stop)}
  },[isDetail,loading,data,feed,game,page,renderKey,listKey,popular,viewMode])

  useEffect(() => {
    if (!identity) { setDetail(null); setDetailError(''); return }
    const controller = new AbortController()
    const params = new URLSearchParams({ ...identity, show_unrated: allowUnknown ? '1' : '0' })
    if(history.state?.eryouRemoteGame)params.set('remote_game',String(history.state.eryouRemoteGame))
    setDetail(null); setDetailError('')
    read<Mod>('/api/mod?' + params, controller.signal).then(setDetail)
      .catch(error => { if (error.name !== 'AbortError') setDetailError(error.message) })
    return () => controller.abort()
  }, [hash, allowUnknown, revision])

  const openMod = (mod: Mod) => {
    const anchor=`${mod.source}:${mod.item_type}:${mod.item_id}`
    const element=Array.from(listRef.current?.querySelectorAll<HTMLElement>('[data-mod-identity]')||[]).find(el=>el.dataset.modIdentity===anchor)
    const saved:SavedView={...viewRef.current,scrollY:window.scrollY,anchor,anchorTop:element?.getBoundingClientRect().top??0,anchorGame:mod.game_id??undefined}
    history.replaceState({...history.state,eryouView:saved},'')
    history.pushState({eryouView:saved,eryouRemoteGame:mod.is_local===false?mod.game_id:undefined},'',`#/mod/${encodeURIComponent(mod.source)}/${encodeURIComponent(mod.item_type)}/${mod.item_id}`)
    setHash(window.location.hash)
    window.scrollTo({ top: 0, behavior: 'instant' })
  }
  const openAuthor=(a:Author)=>{
    const next:SavedView={...viewRef.current,author:a,category:'',subcategory:'',feed:'latest',game:'',draft:'',search:'',sort:'created',page:0,scrollY:0,anchor:'',anchorTop:0}
    history.pushState({eryouView:next},'',`#/author/${encodeURIComponent(a.source)}/${a.author_id}`);applyView(next);setHash(window.location.hash);window.scrollTo(0,0)
  }
  const submitSearch = (event: FormEvent) => { event.preventDefault(); setSearch(draft.trim()); setPage(0); resetList() }
  const changeListing=(mode:typeof viewMode,size:typeof pageSize)=>{
    if(mode===viewMode&&size===pageSize)return
    const nextPage=size===pageSize?page:resizedPage(page,pageSize,size,data?.total_count||0)
    const cards=Array.from(gridRef.current?.querySelectorAll<HTMLElement>('[data-mod-identity]')||[])
    const anchor=size!==pageSize?cards[0]:cards.find(el=>el.getBoundingClientRect().bottom>0)
    pendingRestore.current={...viewRef.current,viewMode:mode,pageSize:size,page:nextPage,scrollY:window.scrollY,anchor:anchor?.dataset.modIdentity||'',anchorTop:anchor?.getBoundingClientRect().top||0}
    setViewMode(mode);setPageSize(size);setPage(nextPage)
  }
  const pageCount = Math.max(1, Math.ceil((data?.total_count || 0) / pageSize))
  const selectCategory=(cat:string,sub:string)=>{setCategory(cat);setSubcategory(sub);setPage(0);resetList()}
  const currentGame = games.find(item => String(item.game_id) === game)?.name || '全部游戏'

  return <div className="app-shell">
    <nav className="icon-rail" aria-label="主导航">
      <a className="brand-mark" href="#" aria-label="二游工具盒首页">E<span>。</span></a>
      <a href="#" className="rail-button active" aria-label="MOD 作品库" title="MOD 作品库"><Icon name="grid" /></a>
      <div className="flex-1" />
      <a href="http://127.0.0.1:8501" target="_blank" rel="noopener noreferrer"
        className="rail-button" aria-label="打开 Streamlit 旧版界面" title="打开 Streamlit 旧版界面"><Icon name="external" /></a>
      <span className="pb-6 text-[10px] text-slate-400">V0.5 RC2</span>
    </nav>
    <div className="app-body">
      <header className="topbar">
        <div className="flex min-w-0 items-center gap-4">
          <select aria-label="选择游戏" value={game} className="game-select"
            onChange={event => { setGame(event.target.value);setCategory('');setSubcategory(''); setPage(0); resetList() }}>
            <option value="">全部游戏</option>
            {games.map(item => <option key={item.game_id} value={item.game_id}>{item.name}</option>)}
          </select>
          <span className="hidden whitespace-nowrap text-xs text-slate-400 lg:block">GameBanana / {isDetail ? '作品详情' : '本地作品库'}</span>
        </div>
        <form onSubmit={submitSearch} className="search-box">
          <Icon name="search" />
          <input aria-label="搜索 MOD ID、标题或作者" placeholder="搜索 MOD ID、标题或作者" value={draft} onChange={event => setDraft(event.target.value)} />
          <button type="submit" className="search-submit">搜索</button>
        </form>
      </header>
      <div className="content-shell">
        <main className="main-content">
          <nav aria-label="作品发现分区" className="mb-6 flex flex-wrap gap-6 border-b border-slate-200 text-sm">
            <button aria-current={feed === 'subscriptions' ? 'page' : undefined} className={`pb-3 ${feed === 'subscriptions' ? 'border-b-2 border-violet-500 font-semibold text-violet-700' : 'text-slate-500'}`} onClick={() => {setCategory('');setSubcategory('');setAuthor(null);setFeed('subscriptions'); setSort('created'); setPage(0); resetList(true)}}>订阅动态</button>
            <button aria-current={feed === 'latest' ? 'page' : undefined} className={`pb-3 ${feed === 'latest' ? 'border-b-2 border-violet-500 font-semibold text-violet-700' : 'text-slate-500'}`} onClick={() => {setCategory('');setSubcategory('');setAuthor(null);setFeed('latest'); setPage(0); resetList(true)}}>最新 MOD</button>
            <button aria-current={feed === 'popular' ? 'page' : undefined} className={`pb-3 ${feed === 'popular' ? 'border-b-2 border-violet-500 font-semibold text-violet-700' : 'text-slate-500'}`} onClick={()=>{setCategory('');setSubcategory('');setAuthor(null);setFeed('popular');resetList(true)}}>热门 MOD</button>
          </nav>
          {configError && <div className="error-banner">{configError}</div>}
          <nav className="browse-path" aria-label="当前浏览路径"><button onClick={()=>selectCategory('','')}>{currentGame}</button>
           {category&&<><span> / </span><button onClick={()=>selectCategory(category,'')}>{category}</button></>}
           {subcategory&&<><span> / </span><button onClick={()=>selectCategory(category,subcategory)}>{subcategory}</button></>}
           {isDetail&&<span> / {detail?.title||'作品详情'}</span>}
          </nav>
          <div hidden={feed!=='latest'||isDetail}><SyncCheck game={game} onComplete={refreshLibrary}/></div>
          <div ref={listRef} hidden={isDetail}>{feed === 'popular' ? <PopularPanel games={games} game={game} search={search} ratings={ratings} allowUnknown={allowUnknown} onOpen={openMod} view={popular} onViewChange={setPopular} paused={isDetail}/> : <>
            {feed === 'subscriptions' && <><MyAuthors revision={feedRevision} onOpen={openAuthor} onChange={()=>setFeedRevision(v=>v+1)}/><AuthorUpdateCheck /></>}
            {author&&<AuthorHeader key={`${author.source}:${author.author_id}`} author={author} onChange={()=>setFeedRevision(v=>v+1)}/>}
            <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
              <div><p className="section-kicker">二游工具盒 · 本地浏览</p>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">{author?'作者作品':feed === 'subscriptions' ? '订阅动态' : '最新 MOD'}<span className="text-violet-500">。</span></h1>
                {feed === 'subscriptions' && <p className="mt-2 text-xs text-slate-500">仅显示已关注作者的本地作品 · 包含关注前历史作品 · 非实时追踪 · 最近更新仅含 source_updated 事件</p>}
                <p className="mt-2 text-xs text-slate-500">{currentGame} · {withImages ? '优先浏览已保存图片的作品' : '浏览全部已收录作品'}</p>
                <p className="mt-2 text-xs text-slate-500">{sort === 'updated' ? '最近来源更新 · 仅显示具有来源更新时间的作品' : sort === 'first_seen' ? '本地首次发现 · 不代表来源新发布' : '新发布 · 按来源发布时间排序'}</p>
                {data?.discovery && <details className="mt-3 space-y-1 text-[11px] leading-5 text-slate-400">
                  <summary className="cursor-pointer">本地收录 {data.discovery.local_count} 条 · 同步记录</summary>
                  <p>本地收录 {data.discovery.local_count} 条 · 不代表来源全量 · 时间范围完整性未验证</p>
                  <p>最近一条同步记录：{data.discovery.last_sync
                    ? `${syncTimeLabel(data.discovery.last_sync.ended_at || data.discovery.last_sync.started_at)} · ${syncStatusLabel(data.discovery.last_sync.status)} · 游戏 ${data.discovery.last_sync.game_id ?? '未指定'}`
                    : '暂无同步记录'}</p>
                  {!game && <p>全部游戏模式展示任一游戏最近一条记录，不代表六游戏同时完成。</p>}
                </details>}
              </div>
              <div className="pagination">
                <button aria-label="上一页" disabled={page === 0 || loading} onClick={() => setPage(page - 1)}><Icon name="left" /></button>
                <span>{page + 1}<span className="mx-2 text-slate-300">/</span>{pageCount}</span>
                <button aria-label="下一页" disabled={!data || page + 1 >= pageCount || loading} onClick={() => setPage(page + 1)}><Icon name="right" /></button>
              </div>
            </div>
            <div className="list-toolbar">
              <div className="view-switch" aria-label="已阅筛选">{[['all','全部'],['unread','未阅'],['read','已阅']].map(([value,label])=><button key={value} className={readFilter===value?'selected':''} onClick={()=>{setReadFilter(value);setPage(0)}}>{label}</button>)}</div>
              <div className="view-switch" aria-label="作品范围">
                <button className={withImages ? 'selected' : ''} onClick={() => { setWithImages(true); setPage(0) }}><Icon name="image" />已有图片</button>
                <button className={!withImages ? 'selected' : ''} onClick={() => { setWithImages(false); setPage(0) }}>全部作品</button>
              </div>
              <label className="flex items-center gap-2 text-xs text-slate-500">排序
                <select aria-label="作品排序" value={sort} onChange={event => { setSort(event.target.value); setPage(0) }}>
                  <option value="created">最近发布 · 来源发布时间</option><option value="updated">最近来源更新</option>{feed !== 'subscriptions' && <option value="first_seen">本地首次发现</option>}
                </select>
              </label>
              <div className="view-switch density-switch" aria-label="列表密度">{(['standard','compact'] as const).map(mode=><button key={mode} aria-pressed={viewMode===mode} className={viewMode===mode?'selected':''} onClick={()=>changeListing(mode,pageSize)}>{mode==='standard'?'标准视图':'紧凑视图'}</button>)}</div>
              <label className="page-size-control">每页 <select aria-label="每页作品数量" disabled={loading} value={pageSize} onChange={e=>changeListing(viewMode,listingPreferences({pageSize:Number(e.target.value)}).pageSize)}>{[15,25,50].map(n=><option value={n} key={n}>{n} 件</option>)}</select></label>
            </div>
            {loading && !data && <div className={`mod-grid${viewMode==='compact'?' compact-grid':''}`} role="status" aria-label="正在读取本地作品">{Array.from({length:5},(_,i)=><div key={i} className="card-skeleton"><span/><span/><span/></div>)}</div>}
            {error && <div className="error-banner" role="alert">{error}<button className="small-button mt-3" onClick={() => setRevision(revision + 1)}>重新读取</button></div>}
            {!loading && !error && data?.items.length === 0 && <div className="empty-state"><Icon name="folder" /><h2>{data.discovery?.local_count===0?'尚未收录本地作品':'没有符合当前筛选条件的作品'}</h2>
              <p>{feed === 'subscriptions' ? '可以在作品详情中关注作者；也可调整游戏、搜索或分级条件。' : '试试“全部作品”，或调整游戏与搜索条件。'}</p></div>}
            <div ref={gridRef} className={`mod-grid${viewMode==='compact'?' compact-grid':''}`}>
              {data?.items.map((mod,index) => <PreviewCard key={`${mod.source}:${mod.item_type}:${mod.item_id}:${allowUnknown}`}
                mod={mod} compact={viewMode==='compact'} priority={index<firstRow} allowUnknown={allowUnknown} timeMode={sort} onOpen={() => openMod(mod)} onReadChange={()=>setFeedRevision(value=>value+1)} />)}
            </div>
            {data && <p className="mt-6 text-xs text-slate-400">匹配 {data.total_count} 条 · 本页 {data.items.length} 条 · 每页 {pageSize} 件（上限 50）</p>}
          </>}</div>
          {isDetail && (detailError ? <div className="error-banner">{detailError}<button onClick={returnToList} className="back-link mt-4">返回作品库</button></div>
            : detail ? <ModDetail key={`${detail.source}:${detail.item_type}:${detail.item_id}:${allowUnknown}`} mod={detail} ratings={ratings} allowUnknown={allowUnknown} onOpenAuthor={openAuthor} onOpenMod={openMod} onBack={returnToList} onFollowChange={() => setFeedRevision(value => value + 1)} />
            : <div className="empty-state" role="status">正在读取作品详情…</div>)}
        </main>
        <aside className="category-panel">
          <div><p className="section-kicker">浏览设置</p><h2 className="mt-2 text-base font-semibold text-slate-800">留一点空间给发现</h2></div>
          <div className="privacy-box">
            <Icon name="shield" />
            <label className="flex flex-1 items-start justify-between gap-3 text-xs leading-5">
              <span>显示作品图片<span className="mt-1 block text-[11px] text-slate-400">独立于来源分级；仅保存本机显示偏好</span></span>
              <input aria-label="显示作品图片" type="checkbox" checked={allowUnknown} onChange={event => { setAllowUnknown(event.target.checked); localStorage.setItem("showPreviewImages", event.target.checked ? "1" : "0") }} />
            </label>
          </div>
          <div className="mb-4 space-y-2 text-xs text-slate-500">
            <label className="flex items-center justify-between gap-2">显示 UNKNOWN / 待评级图片<input type="checkbox" checked={extraImages.unknown} onChange={e=>{localStorage.setItem('showUnknownPreviews',e.target.checked?'1':'0');setExtraImages(imagePreferences());setRevision(v=>v+1)}}/></label>
            <label className="flex items-center justify-between gap-2">显示敏感分级图片<input type="checkbox" checked={extraImages.sensitive} onChange={e=>{localStorage.setItem('showSensitivePreviews',e.target.checked?'1':'0');setExtraImages(imagePreferences());setRevision(v=>v+1)}}/></label>
          </div>
          <section className="border-t border-slate-100 pt-6">
            <button className="filter-heading" aria-expanded={ratingsOpen} aria-controls="rating-options" onClick={()=>setRatingsOpen(!ratingsOpen)}><span>内容分级</span><span>{ratings===null||ratings.length===ratingOptions.length?'全部已选':`已选 ${ratings.length}`}{ratingsOpen?' ▴':' ▾'}</span></button>
            <div id="rating-options" hidden={!ratingsOpen}>
            <p className="my-2 text-xs text-slate-500">来源标签，多选按 OR 筛选；与人工转载审核无关。</p>
            <div className="my-3 flex gap-3 text-xs">
              <button onClick={() => { setRatings(null); setPage(0) }}>全选</button>
              <button onClick={() => { setRatings([]); setPage(0) }}>取消全选</button>
              <button onClick={() => { setRatings(null); setPage(0) }}>恢复默认</button>
            </div>
            <RatingEnrichment onComplete={refreshLibrary}/>
            {ratingOptions.map(option => <label key={option._sAlias} className="my-2 flex gap-2 text-xs">
              <input type="checkbox" checked={ratings === null || ratings.includes(option._sAlias)} onChange={event => {
                const current = ratings ?? ratingOptions.map(item => item._sAlias)
                setRatings(event.target.checked ? [...current, option._sAlias] : current.filter(code => code !== option._sAlias)); setPage(0)
              }} />{option._sTitle}
            </label>)}
            </div>
          </section>
          <CategorySidebar game={game} category={category} subcategory={subcategory} revision={feedRevision} onSelect={selectCategory} disabled={feed==='popular'}/>
          <div className="mt-auto border-t border-slate-100 pt-5 text-[11px] leading-6 text-slate-400">
            <p>ErYouToolbox · V0.5 RC2</p><p>数据来自本机 SQLite</p><p>图片来源于作品原帖</p>
          </div>
        </aside>
      </div>
    </div>
  </div>
}

