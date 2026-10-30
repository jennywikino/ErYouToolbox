import { useState, useEffect, useRef } from 'react'
import type { Mod } from './types'
import Icon from './Icons'
import ReadStateControl from './ReadStateControl'
import { canShowImages, dateLabel, discoveryTime, safeUrl, subscriptionActivity } from './policy'

export function ImagePlaceholder({ reason = '暂无已保存预览图' }: { reason?: string }) {
  return <div className="image-placeholder"><Icon name="image" /><span>{reason}</span></div>
}

export default function PreviewCard({ mod, allowUnknown, onOpen, timeMode = 'created', onReadChange, priority=false }: {
  mod: Mod; allowUnknown: boolean; onOpen: () => void; timeMode?: string; onReadChange?: () => void; priority?: boolean
}) {
  const [failed, setFailed] = useState(false)
  const [loaded,setLoaded]=useState(false),[near,setNear]=useState(priority)
  const cardRef=useRef<HTMLElement>(null)
  const imageRef=useRef<HTMLImageElement>(null)
  useEffect(()=>{if(priority){setNear(true);return}const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setNear(true);observer.disconnect()}},{rootMargin:'250px'});if(cardRef.current)observer.observe(cardRef.current);return()=>observer.disconnect()},[priority])
  const allowed = canShowImages(mod.content_rating_status, allowUnknown)
  const url = allowed ? safeUrl(mod.preview_urls[0]) : null
  useEffect(()=>{setFailed(false);setLoaded(!!imageRef.current?.complete && imageRef.current.naturalWidth>0)},[url,near])
  const hidden = mod.image_count > 0 && !allowed
  const timestamp = discoveryTime(mod, timeMode)
  return <article ref={cardRef} className="mod-card group"
    data-mod-identity={`${mod.source}:${mod.item_type}:${mod.item_id}`}>
    <button className="w-full text-left" onClick={onOpen} aria-label={`查看详情：${mod.title || mod.item_id}`}>
    <div className="relative aspect-[16/10] overflow-hidden bg-slate-100">
      {url && !failed && near ? <><img ref={imageRef} src={url} alt={mod.title || 'MOD 预览图'} loading={priority?'eager':'lazy'} decoding="async" fetchPriority={priority?'high':'low'}
        className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.025]"
        onLoad={()=>setLoaded(true)} onError={() => setFailed(true)} referrerPolicy="no-referrer" />{!loaded&&<span role="status" className="absolute bottom-2 left-2 rounded bg-white/90 px-2 py-1 text-xs text-slate-500">图片加载中…</span>}</>
        : <ImagePlaceholder reason={failed ? '图片暂时无法加载'
          : url&&!near ? '图片按需加载'
          : hidden ? (mod.content_rating_status === 'UNKNOWN' ? '未评级 · 预览已隐藏' : '分级限制 · 预览已隐藏')
          : '暂无已保存预览图'} />}
    </div>
    <div className="p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium tracking-wide text-violet-700">{mod.game_name || '暂无游戏信息'}</span>
        <span className="rating-tag">{mod.source_ratings?.codes.join(' / ') || 'UNKNOWN'}</span>
      </div>
      <h3 className="line-clamp-2 min-h-11 text-sm font-semibold leading-[1.55] text-slate-800">{mod.title || '暂无标题'}</h3>
      <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
        <span className="author-initial" aria-hidden="true">{(mod.author_name || '?').slice(0, 1).toUpperCase()}</span>
        <span className="min-w-0 flex-1 truncate">{mod.author_name || '暂无作者'}</span>
      </div>
      <p className="mt-2 text-[11px] text-slate-500">{timestamp.label} · <time title={timestamp.value || ''}>{dateLabel(timestamp.value)}</time></p>
      {timeMode !== 'first_seen' && mod.first_seen_at && <p className="mt-1 text-[11px] text-slate-400">本地首次发现 · {dateLabel(mod.first_seen_at)}</p>}
      {mod.rank !== undefined && <p className="mt-2 text-xs text-violet-700">{mod.ranking_scope === 'recent_sample' ? '近期候选集排名' : '来源排名'} #{mod.rank}{mod.metrics?.likes !== undefined ? ` · 累计喜欢 ${mod.metrics.likes}` : ''}{mod.metrics?.views !== undefined ? ` · 累计浏览 ${mod.metrics.views}` : ''}</p>}
      {mod.source_update_detected_at && <p className="mt-2 text-[11px] font-medium text-violet-700" title={mod.source_update_detected_at}>已记录来源更新</p>}
      {mod.subscription_followed_at && <p className="mt-2 text-[11px] text-slate-500">{subscriptionActivity(mod)}{mod.source_update_detected_at ? ` · 来源更新 ${dateLabel(mod.updated_at)}` : ''}</p>}
    </div>
    </button>
    {failed&&url&&<button className="small-button mx-4 my-2" onClick={()=>{setLoaded(false);setFailed(false)}}>重试预览图</button>}
    {onReadChange&&<ReadStateControl source={mod.source} itemId={mod.item_id} initial={mod.is_read} onChange={onReadChange}/>}
    {safeUrl(mod.original_url) && <a className="mx-4 mb-4 inline-block text-xs text-violet-700" href={safeUrl(mod.original_url)!} target="_blank" rel="noopener noreferrer">原站链接 ↗</a>}
  </article>
}
