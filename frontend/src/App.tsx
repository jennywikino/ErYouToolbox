import SyncCheck from './SyncCheck'
import { useEffect, useState, useRef, type FormEvent } from 'react'
import type { Game, Mod, ModPage } from './types'
import Icon from './Icons'
import PreviewCard from './PreviewCard'
import ModDetail from './ModDetail'
import AuthorUpdateCheck from './AuthorUpdateCheck'
import PopularPanel, {type PopularView} from './PopularPanel'
import { syncTimeLabel, syncStatusLabel, restoreScrollTop, restorePopularView, validBrowseSnapshot } from './policy'

const PAGE_SIZE = 18

async function read<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
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
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('created')
  const [feed, setFeed] = useState('latest')
  const [popular,setPopular]=useState<PopularView>({sort:'likes',scope:'recent',days:30,maxPages:2,groups:{}})
  const [feedRevision, setFeedRevision] = useState(0)
  const [readFilter,setReadFilter]=useState('all')
  const [page, setPage] = useState(0)
  const [withImages, setWithImages] = useState(false)
  const [allowUnknown, setAllowUnknown] = useState(() => localStorage.getItem("showPreviewImages") !== "0")
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
  const listKey=JSON.stringify([feed,game,search,sort,ratings,readFilter,page,withImages,allowUnknown])
  const currentView={feed,game,draft,search,sort,ratings,readFilter,page,withImages,allowUnknown,popular}
  const viewRef=useRef(currentView);viewRef.current=currentView
  type SavedView=typeof currentView & {scrollY:number;anchor:string;anchorTop:number;anchorGame?:number}
  const pendingRestore=useRef<SavedView|null>(null)
  const applyView=(v:SavedView)=>{setFeed(v.feed);setGame(v.game);setDraft(v.draft);setSearch(v.search);setSort(v.sort);setRatings(v.ratings);setReadFilter(v.readFilter);setPage(v.page);setWithImages(v.withImages);setAllowUnknown(v.allowUnknown);setPopular(v.popular)}
  const resetList=()=>{pendingRestore.current=null;history.replaceState({...history.state,eryouView:null},'');window.location.hash='';window.scrollTo({top:0,behavior:'instant'})}
  const returnToList=()=>{if(history.state?.eryouView){history.back()}else resetList()}

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
      const v=old?{...old,popular:restorePopularView(old.popular)}:undefined
      if(v){applyView(v);pendingRestore.current=v}
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
      game, search, sort, feed, read:readFilter, limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE),
      with_images: withImages ? '1' : '0', show_unrated: allowUnknown ? '1' : '0',
    })
    if (ratings !== null) params.set("ratings", ratings.join(","))
    setLoading(true); setError('')
    read<ModPage>('/api/mods?' + params, controller.signal).then(value=>{if(controller.signal.aborted)return;setRenderKey(listKey);setData(value);const last=Math.max(0,Math.ceil(value.total_count/PAGE_SIZE)-1);if(page>last)setPage(last)})
      .catch(error => { if (error.name !== 'AbortError') setError(error.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [game, search, sort, page, withImages, allowUnknown, revision, ratings, feed, feedRevision,readFilter,isDetail])

  useEffect(()=>{
    const saved=pendingRestore.current
    if(isDetail||!saved||JSON.stringify(viewRef.current)!==JSON.stringify(Object.fromEntries(Object.entries(saved).filter(([k])=>!['scrollY','anchor','anchorTop','anchorGame'].includes(k)))))return
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
  },[isDetail,loading,data,feed,game,page,renderKey,listKey,popular])

  useEffect(() => {
    if (!identity) { setDetail(null); setDetailError(''); return }
    const controller = new AbortController()
    const params = new URLSearchParams({ ...identity, show_unrated: allowUnknown ? '1' : '0' })
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
    history.pushState({eryouView:saved},'',`#/mod/${encodeURIComponent(mod.source)}/${encodeURIComponent(mod.item_type)}/${mod.item_id}`)
    setHash(window.location.hash)
    window.scrollTo({ top: 0, behavior: 'instant' })
  }
  const submitSearch = (event: FormEvent) => { event.preventDefault(); setSearch(draft.trim()); setPage(0); resetList() }
  const pageCount = Math.max(1, Math.ceil((data?.total_count || 0) / PAGE_SIZE))
  const categories = [...new Set(data?.items.map(item => item.category).filter((name): name is string => !!name))]
  const currentGame = games.find(item => String(item.game_id) === game)?.name || '全部游戏'

  return <div className="app-shell">
    <nav className="icon-rail" aria-label="主导航">
      <a className="brand-mark" href="#" aria-label="二游工具盒首页">E<span>。</span></a>
      <a href="#" className="rail-button active" aria-label="MOD 作品库" title="MOD 作品库"><Icon name="grid" /></a>
      <div className="flex-1" />
      <a href="http://127.0.0.1:8501" target="_blank" rel="noopener noreferrer"
        className="rail-button" aria-label="打开 Streamlit 旧版界面" title="打开 Streamlit 旧版界面"><Icon name="external" /></a>
      <span className="pb-6 text-[10px] text-slate-400">V0.4</span>
    </nav>
    <div className="app-body">
      <header className="topbar">
        <div className="flex min-w-0 items-center gap-4">
          <select aria-label="选择游戏" value={game} className="game-select"
            onChange={event => { setGame(event.target.value); setPage(0); resetList() }}>
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
            <button aria-current={feed === 'subscriptions' ? 'page' : undefined} className={`pb-3 ${feed === 'subscriptions' ? 'border-b-2 border-violet-500 font-semibold text-violet-700' : 'text-slate-500'}`} onClick={() => {setFeed('subscriptions'); setSort('created'); setPage(0); resetList()}}>订阅动态</button>
            <button aria-current={feed === 'latest' ? 'page' : undefined} className={`pb-3 ${feed === 'latest' ? 'border-b-2 border-violet-500 font-semibold text-violet-700' : 'text-slate-500'}`} onClick={() => {setFeed('latest'); setPage(0); resetList()}}>最新 MOD</button>
            <button aria-current={feed === 'popular' ? 'page' : undefined} className={`pb-3 ${feed === 'popular' ? 'border-b-2 border-violet-500 font-semibold text-violet-700' : 'text-slate-500'}`} onClick={()=>{setFeed('popular');resetList()}}>热门 MOD</button>
          </nav>
          {configError && <div className="error-banner">{configError}</div>}
          <div ref={listRef} hidden={isDetail}>{feed === 'popular' ? <PopularPanel games={games} game={game} search={search} ratings={ratings} allowUnknown={allowUnknown} onOpen={openMod} view={popular} onViewChange={setPopular} paused={isDetail}/> : <>
            {feed === 'latest' && <SyncCheck game={game} onComplete={()=>setFeedRevision(v=>v+1)}/>}
            {feed === 'subscriptions' && <AuthorUpdateCheck />}
            <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
              <div><p className="section-kicker">二游工具盒 · 本地浏览</p>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">{feed === 'subscriptions' ? '订阅动态' : '最新 MOD'}<span className="text-violet-500">。</span></h1>
                {feed === 'subscriptions' && <p className="mt-2 text-xs text-slate-500">仅显示已关注作者的本地作品 · 包含关注前历史作品 · 非实时追踪 · 最近更新仅含 source_updated 事件</p>}
                <p className="mt-2 text-xs text-slate-500">{currentGame} · {withImages ? '优先浏览已保存图片的作品' : '浏览全部已收录作品'}</p>
                <p className="mt-2 text-xs text-slate-500">{sort === 'updated' ? '最近来源更新 · 仅显示具有来源更新时间的作品' : sort === 'first_seen' ? '本地首次发现 · 不代表来源新发布' : '新发布 · 按来源发布时间排序'}</p>
                {data?.discovery && <div className="mt-3 space-y-1 text-[11px] leading-5 text-slate-400">
                  <p>本地收录 {data.discovery.local_count} 条 · 不代表来源全量 · 时间范围完整性未验证</p>
                  <p>最近一条同步记录：{data.discovery.last_sync
                    ? `${syncTimeLabel(data.discovery.last_sync.ended_at || data.discovery.last_sync.started_at)} · ${syncStatusLabel(data.discovery.last_sync.status)} · 游戏 ${data.discovery.last_sync.game_id ?? '未指定'}`
                    : '暂无同步记录'}</p>
                  {!game && <p>全部游戏模式展示任一游戏最近一条记录，不代表六游戏同时完成。</p>}
                </div>}
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
            </div>
            {loading && !data && <div className="empty-state" role="status">正在读取本地作品…</div>}
            {error && <div className="error-banner" role="alert">{error}<button className="small-button mt-3" onClick={() => setRevision(revision + 1)}>重新读取</button></div>}
            {!loading && !error && data?.items.length === 0 && <div className="empty-state"><Icon name="folder" /><h2>这里还没有符合条件的作品</h2>
              <p>{feed === 'subscriptions' ? '可以在作品详情中关注作者；也可调整游戏、搜索或分级条件。' : '试试“全部作品”，或调整游戏与搜索条件。'}</p></div>}
            <div className="mod-grid">
              {data?.items.map((mod,index) => <PreviewCard key={`${mod.source}:${mod.item_type}:${mod.item_id}:${allowUnknown}`}
                mod={mod} priority={index<3} allowUnknown={allowUnknown} timeMode={sort} onOpen={() => openMod(mod)} onReadChange={()=>setFeedRevision(value=>value+1)} />)}
            </div>
            {data && <p className="mt-6 text-xs text-slate-400">匹配 {data.total_count} 条 · 本页 {data.items.length} 条 · 每次最多读取 20 条</p>}
          </>}</div>
          {isDetail && (detailError ? <div className="error-banner">{detailError}<button onClick={returnToList} className="back-link mt-4">返回作品库</button></div>
            : detail ? <ModDetail key={`${detail.source}:${detail.item_type}:${detail.item_id}:${allowUnknown}`} mod={detail} allowUnknown={allowUnknown} onBack={returnToList} onFollowChange={() => setFeedRevision(value => value + 1)} />
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
          <section className="border-t border-slate-100 pt-6">
            <h2 className="text-sm font-semibold">内容分级</h2>
            <p className="my-2 text-xs text-slate-500">来源标签，多选按 OR 筛选；与人工转载审核无关。</p>
            <div className="my-3 flex gap-3 text-xs">
              <button onClick={() => { setRatings(null); setPage(0) }}>全选</button>
              <button onClick={() => { setRatings([]); setPage(0) }}>取消全选</button>
              <button onClick={() => { setRatings(null); setPage(0) }}>恢复默认</button>
            </div>
            {ratingOptions.map(option => <label key={option._sAlias} className="my-2 flex gap-2 text-xs">
              <input type="checkbox" checked={ratings === null || ratings.includes(option._sAlias)} onChange={event => {
                const current = ratings ?? ratingOptions.map(item => item._sAlias)
                setRatings(event.target.checked ? [...current, option._sAlias] : current.filter(code => code !== option._sAlias)); setPage(0)
              }} />{option._sTitle}
            </label>)}
          </section>
          <div className="border-t border-slate-100 pt-6"><h2 className="flex items-center gap-2 text-sm font-semibold"><Icon name="folder" />分类</h2>
            <p className="mt-2 text-xs leading-6 text-slate-400">当前返回作品中已保存的分类。</p>
            <div className="mt-5 flex flex-wrap gap-2">{categories.map(category => <span className="category-tag" key={category}>{category}</span>)}</div>
            {categories.length === 0 && <p className="mt-5 text-xs text-slate-400">暂无已保存的分类信息</p>}
          </div>
          <div className="mt-auto border-t border-slate-100 pt-5 text-[11px] leading-6 text-slate-400">
            <p>ErYouToolbox · V0.4</p><p>数据来自本机 SQLite</p><p>图片来源于作品原帖</p>
          </div>
        </aside>
      </div>
    </div>
  </div>
}

