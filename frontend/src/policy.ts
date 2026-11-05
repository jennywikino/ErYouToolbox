export function safeUrl(value: unknown): string | null {
  if (typeof value !== 'string' || value !== value.trim()) return null
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null
  } catch { return null }
}

export function gameBananaModId(value:string):number|null {
  const text=value.trim()
  if(text.length>2048)return null
  let digits=text
  if(!/^\d+$/.test(text)){
    try{
      const url=new URL(text)
      if(url.protocol!=='https:'||!['gamebanana.com','www.gamebanana.com'].includes(url.hostname)||url.username||url.password||url.port)return null
      const match=/^\/mods\/(\d+)\/?$/.exec(url.pathname)
      if(!match)return null
      digits=match[1]
    }catch{return null}
  }
  const id=Number(digits)
  return Number.isSafeInteger(id)&&id>0?id:null
}

export function imagePreferenceQuery(): string {
  return '' // Legacy preferences must not hide images after rc3.
}

export function imagePreferences(){
  return {sensitive:true,unknown:true} // Old per-rating storage is ignored.
}

export function canShowImages(rating: string, showImages: boolean, codes:string[]=['UNKNOWN'], sensitive=false, unknown=false): boolean {
  // Compatibility signature for old snapshots/components; policy is retired.
  void rating;void showImages;void codes;void sensitive;void unknown
  return true
}

export function canShowModImages(mod:{content_rating_status:string;source_ratings?:{codes:string[]}},showImages:boolean):boolean{
  const prefs=imagePreferences()
  return canShowImages(mod.content_rating_status,showImages,mod.source_ratings?.codes,prefs.sensitive,prefs.unknown)
}

export function imageIndex(index: number, count: number): number {
  return Math.max(0, Math.min(index, count - 1))
}

export function listingPreferences(value: unknown): {viewMode:'standard'|'compact';pageSize:15|25|50} {
  const v=(value&&typeof value==='object'?value:{}) as Record<string,unknown>
  return {viewMode:v.viewMode==='standard'?'standard':'compact',pageSize:v.pageSize===15?15:v.pageSize===50?50:25}
}

export function resizedPage(page:number,oldSize:number,newSize:number,total:number):number {
  return Math.min(Math.floor(page*oldSize/newSize),Math.max(0,Math.ceil(total/newSize)-1))
}

export function cardPreviewUrl(mod:{preview_urls:string[];preview_images?:{thumbnail_url?:string;switch_url?:string}[]},compact:boolean):string|null {
  const image=mod.preview_images?.[0]
  return (compact?(safeUrl(image?.thumbnail_url)||safeUrl(image?.switch_url)):null)||safeUrl(mod.preview_urls[0])
}

export function dateLabel(value: string | null | undefined): string {
  if (!value) return '暂无来源数据'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '暂无来源数据' : date.toLocaleDateString('zh-CN', { timeZone: 'UTC' })
}

export function sourceUpdateDate(mod:{created_at?:string|null;updated_at?:string|null}){
  const updated=mod.updated_at&&Number.isFinite(Date.parse(mod.updated_at))?mod.updated_at:null
  const created=mod.created_at&&Number.isFinite(Date.parse(mod.created_at))?mod.created_at:null
  return {value:updated||created,hasIndependentUpdate:!!updated}
}

export function discoveryTime(mod: {created_at?: string | null; updated_at?: string | null; first_seen_at?: string}, sort: string) {
  if (sort === 'updated') {const updated=sourceUpdateDate(mod);return { label: updated.hasIndependentUpdate?'来源更新':'暂无单独更新记录', value: updated.value }}
  if (sort === 'first_seen') return { label: '本地发现', value: mod.first_seen_at }
  return { label: '来源发布', value: mod.created_at }
}

export function syncTimeLabel(value: string | null | undefined): string {
  if (!value || Number.isNaN(new Date(value).getTime())) return '暂无时间'
  return new Date(value).toLocaleString('zh-CN', {timeZone: 'UTC'}) + ' UTC'
}

export function syncStatusLabel(status: string): string {
  return ({success: '成功', partial: '部分成功', failed: '失败', running: '运行中'} as Record<string, string>)[status] || '未知状态'
}

export function syncFailureCount(record:{failure_count?:number;failures?:unknown[];error?:string;status?:string;authors?:{status?:string;pending_count?:number}}|null|undefined):number {
  if(!record)return 0
  const errors=record.failures?.length||0
  const authors=record.authors?.status&&record.authors.status!=='success'?Math.max(1,record.authors.pending_count||0):0
  return Math.max(record.failure_count||0,errors+authors,(record.error||['failed','partial','stopped'].includes(record.status||''))?1:0)
}

export function restoreScrollTop(anchorTop:number|null,currentY:number,savedAnchorTop:number,pixelFallback:number):number{
  const target=anchorTop===null?pixelFallback:currentY+anchorTop-savedAnchorTop
  return Number.isFinite(target)?Math.max(0,target):0
}

export function restorePopularView(value:unknown){
  const v=(value&&typeof value==='object'?value:{}) as Record<string,unknown>
  const groups:Record<string,{loaded:boolean;page:number}>={}
  if(v.groups&&typeof v.groups==='object')for(const [key,item] of Object.entries(v.groups)){
    if(!/^[1-9]\d*$/.test(key))continue
    if(item&&typeof item==='object'&&Number.isInteger(item.page)&&item.page>=1&&item.page<=100&&typeof item.loaded==='boolean')groups[key]={page:item.page,loaded:item.loaded}
  }
  return {sort:['likes','views','downloads'].includes(String(v.sort))?String(v.sort):'likes',scope:v.scope==='history'?'history':'recent',days:[7,30,90].includes(Number(v.days))?Number(v.days):30,maxPages:Number.isInteger(v.maxPages)&&Number(v.maxPages)>=1&&Number(v.maxPages)<=5?Number(v.maxPages):2,groups}
}

export function validBrowseSnapshot(value:unknown):boolean{
  if(!value||typeof value!=='object')return false
  const v=value as Record<string,unknown>
  return ['latest','subscriptions','popular'].includes(String(v.feed))
    && (v.author==null||(typeof v.author==='object'&&typeof (v.author as Record<string,unknown>).source==='string'&&Number.isSafeInteger((v.author as Record<string,unknown>).author_id)&&Number((v.author as Record<string,unknown>).author_id)>0))
    && ['game','draft','search','sort','readFilter','anchor'].every(key=>typeof v[key]==='string')
    && ['category','subcategory'].every(key=>v[key]===undefined||typeof v[key]==='string')
    && ['all','read','unread'].includes(String(v.readFilter))
    && Number.isInteger(v.page)&&Number(v.page)>=0
    && (v.pageSize===undefined||[15,25,50].includes(Number(v.pageSize))&&typeof v.pageSize==='number')
    && (v.viewMode===undefined||v.viewMode==='standard'||v.viewMode==='compact')
    && typeof v.scrollY==='number'&&Number.isFinite(v.scrollY)&&v.scrollY>=0
    && typeof v.anchorTop==='number'&&Number.isFinite(v.anchorTop)
    && typeof v.withImages==='boolean'&&typeof v.allowUnknown==='boolean'
    && (v.ratings===null||(Array.isArray(v.ratings)&&v.ratings.every(item=>typeof item==='string')))
}

export function subscriptionActivity(mod: {subscription_followed_at?: string; author_baseline_at?: string | null; created_at?: string | null; local_first_seen_event_at?: string | null; source_update_detected_at?: string | null}): string {
  if (mod.author_baseline_at && Date.parse(mod.created_at || '') <= Date.parse(mod.author_baseline_at) && (!mod.source_update_detected_at || Date.parse(mod.source_update_detected_at) <= Date.parse(mod.author_baseline_at))) return '已收录历史作品'
  const followed = Date.parse(mod.subscription_followed_at || '')
  if (Date.parse(mod.source_update_detected_at || '') >= followed) return '关注后确认来源更新'
  if (Date.parse(mod.created_at || '') >= followed && Date.parse(mod.local_first_seen_event_at || '') >= followed) return '关注后新发布'
  if (!Number.isFinite(Date.parse(mod.created_at || ''))) return '发布时间未知 · 已收录作品'
  return '已收录历史作品'
}
export function globalSearchContext<T extends {game:string;draft:string}>(view:T) {
  return {...view,search:view.draft.trim(),category:'',subcategory:'',author:null,page:0} as Omit<T,'search'|'category'|'subcategory'|'author'|'page'> & {search:string;category:string;subcategory:string;author:null;page:number}
}
