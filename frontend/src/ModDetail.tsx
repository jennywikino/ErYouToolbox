import RelatedMods from './RelatedMods'
import type {Author} from './Authors'
import { useState } from 'react'
import type { Mod } from './types'
import { canShowImages, dateLabel, imageIndex, safeUrl } from './policy'
import Icon from './Icons'
import { ImagePlaceholder } from './PreviewCard'
import FollowAuthor from './FollowAuthor'
import ReadStateControl from './ReadStateControl'

export default function ModDetail({ mod, allowUnknown, onFollowChange, onBack, onOpenAuthor, onOpenMod, ratings }: { mod: Mod; allowUnknown: boolean; onFollowChange: () => void; onBack: () => void; onOpenAuthor:(a:Author)=>void; onOpenMod:(m:Mod)=>void; ratings?:string[]|null }) {
  const [index, setIndex] = useState(0)
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const [loadedUrl,setLoadedUrl]=useState<string|null>(null)
  const [failedThumbs,setFailedThumbs]=useState<Set<string>>(()=>new Set())
  const allowed = canShowImages(mod.content_rating_status, allowUnknown)
  const images = allowed ? (mod.preview_images || []) : []
  const current = images[imageIndex(index, images.length)]
  const currentUrl = safeUrl(current?.image_url)
  const authorUrl = safeUrl(mod.author_url)
  const originalUrl = safeUrl(mod.original_url)
  return <article>
    <ReadStateControl source={mod.source} itemId={mod.item_id} auto onChange={onFollowChange}/>
    <div className="mb-6">
      <button onClick={onBack} className="back-link"><Icon name="left" />返回作品库</button>
      <p className="mt-5 text-xs font-medium text-violet-600">{mod.game_name || '暂无游戏信息'} · MOD {mod.item_id}</p>
      <h1 className="mt-2 text-2xl font-semibold leading-snug text-slate-900">{mod.title || '暂无标题'}</h1>
    </div>
    <div className="detail-grid">
      <section className="min-w-0">
        <div className="gallery-stage relative" style={{height:'min(62vh, 650px)'}}>
          {currentUrl && currentUrl !== failedUrl
            ? <img src={currentUrl} alt={`${mod.title || '作品'} · 图片 ${index + 1}`}
                className="h-full max-h-[62vh] w-full object-contain" referrerPolicy="no-referrer" decoding="async" fetchPriority="high" loading="eager"
                onLoad={()=>setLoadedUrl(currentUrl)}
                onError={() => setFailedUrl(currentUrl)} />
            : <ImagePlaceholder reason={!allowed && mod.image_count > 0 ? '预览已隐藏，请检查内容分级设置'
              : failedUrl && currentUrl === failedUrl ? '图片加载失败，可尝试其他图片' : '暂无已保存图片'} />}
          {currentUrl&&currentUrl!==failedUrl&&loadedUrl!==currentUrl&&<span role="status" className="absolute bottom-2 left-2 rounded bg-white/90 px-2 py-1 text-xs text-slate-500">高清图片加载中…</span>}
          {currentUrl===failedUrl&&currentUrl&&<button className="small-button absolute bottom-3 left-3" onClick={()=>{setLoadedUrl(null);setFailedUrl(null)}}>重试高清图片</button>}
        </div>
        {images.length > 0 && <>
          <div className="my-3 flex items-center justify-between">
            <button className="small-button" disabled={index <= 0}
              onClick={() => setIndex(imageIndex(index - 1, images.length))}><Icon name="left" />上一张</button>
            <span className="text-xs tabular-nums text-slate-500">{index + 1} / {images.length}</span>
            <button className="small-button" disabled={index >= images.length - 1}
              onClick={() => setIndex(imageIndex(index + 1, images.length))}>下一张<Icon name="right" /></button>
          </div>
          <div className="flex gap-2 overflow-x-auto py-1" aria-label="作品图片缩略图">
            {images.map((image, i) => {
              const thumbnail = safeUrl(image.switch_url) || safeUrl(image.thumbnail_url)
              const thumbFailed=!!thumbnail&&failedThumbs.has(thumbnail)
              return <button key={image.image_url} onClick={() => {setIndex(i);if(thumbnail&&thumbFailed)setFailedThumbs(old=>{const next=new Set(old);next.delete(thumbnail);return next})}} aria-label={thumbFailed?`重试第 ${i + 1} 张缩略图`:`查看第 ${i + 1} 张`}
                aria-pressed={i === index} className={`gallery-thumb ${i === index ? 'selected' : ''}`}>
                {thumbnail&&!thumbFailed ? <img src={thumbnail} alt={`缩略图 ${i + 1}`} loading="lazy" decoding="async" fetchPriority="low" referrerPolicy="no-referrer"
                  onError={()=>setFailedThumbs(old=>new Set(old).add(thumbnail))} /> : <span className="text-[10px]">{thumbFailed?'失败 · 重试':'无缩略图'}</span>}
              </button>
            })}
          </div>
          {currentUrl && <a className="mt-4 inline-flex items-center gap-2 text-xs text-violet-700"
            href={currentUrl} target="_blank" rel="noopener noreferrer">单独打开当前图片<Icon name="external" /></a>}
        </>}
      </section>
      <aside className="detail-meta">
        <p className="section-kicker">作品信息</p>
        <h2 className="mt-3 text-lg font-semibold">{mod.author_id ? <button onClick={()=>onOpenAuthor({source:mod.source,author_id:mod.author_id!,name:mod.author_name||undefined})}>{mod.author_name || '暂无作者'}</button> : mod.author_name || '暂无作者'}</h2>
        <FollowAuthor source={mod.source} authorId={mod.author_id} onChange={onFollowChange} />
        {authorUrl && <a className="mt-2 inline-flex items-center gap-2 text-xs text-violet-700"
          href={authorUrl} target="_blank" rel="noopener noreferrer">作者主页<Icon name="external" /></a>}
        <dl className="metadata-list">
          <dt>发布时间</dt><dd>{dateLabel(mod.created_at)}</dd>
          <dt>来源更新时间</dt><dd>{dateLabel(mod.updated_at)}</dd>
          <dt>版本</dt><dd>{mod.version || '暂无数据'}</dd>
          <dt>分类</dt><dd>{[mod.category, mod.subcategory].filter(Boolean).join(' / ') || '暂无数据'}</dd>
          <dt>内容分级</dt><dd>{mod.source_ratings?.codes.join(' / ') || 'UNKNOWN · 尚未验证'}</dd>
        </dl>
        {!!mod.tags?.length && <div className="mt-4 flex flex-wrap gap-1.5">{mod.tags.map(tag => <span key={tag} className="rating-tag">{tag}</span>)}</div>}
        <div className="mt-5 border-t border-slate-100 pt-4">
          <p className="section-kicker">已保存简介</p>
          <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-slate-600">{mod.description || '暂无已保存的作品简介。'}</p>
        </div>
        {originalUrl && <a className="primary-button mt-6" href={originalUrl} target="_blank" rel="noopener noreferrer">
          查看 GameBanana 原帖<Icon name="external" /></a>}
        <RelatedMods ratings={ratings} mod={mod} allowUnknown={allowUnknown} onOpen={onOpenMod} onAuthor={onOpenAuthor}/>
      </aside>
    </div>
  </article>
}
