import { test } from 'node:test'
import assert from 'node:assert/strict'
import {listingPreferences,resizedPage,cardPreviewUrl,sourceUpdateDate,dateLabel} from './policy.ts'
import {createStartupRequest,requestDueCheck} from './autoStartup.ts'

test('periodic due checks preserve off, future, running, pending and saved mode',async()=>{
 for(const [mode,due,status,posts] of [['off',0,'success',0],['check',1001,'success',0],['apply',0,'checking',0],['apply',0,'manual_preview_pending',0],['check',0,'success',1],['apply',0,'success',1]] as const){
  let count=0
  const request=(async (_url:RequestInfo|URL,init?:RequestInit)=>{if(init)count++;return new Response(JSON.stringify(init?{status:'requested'}:{settings:{mode},next_due:new Date(due).toISOString(),last_run:{status}}))}) as typeof fetch
  await requestDueCheck(request,1000);assert.equal(count,posts)
 }
})
import { canShowImages, imageIndex, safeUrl, discoveryTime, syncTimeLabel, syncStatusLabel, subscriptionActivity, restoreScrollTop, restorePopularView, validBrowseSnapshot } from './policy.ts'

test('startup is once per document, off skips launch, enabled delegates due checks to server', async () => {
  for(const mode of ['off','check','apply']){
    const calls: {url:string;init?:RequestInit}[]=[]
    const start=createStartupRequest((async (url:RequestInfo|URL,init?:RequestInit)=>{
      calls.push({url:String(url),init})
      return new Response(JSON.stringify(init?{status:'requested'}:{settings:{mode}}),{status:200})
    }) as typeof fetch)
    const first=start();assert.equal(first,start());await Promise.all([first,start()])
    assert.equal(calls.length,mode==='off'?1:2)
    if(mode!=='off'){
      assert.equal(calls[1].url,'/api/auto-sync/startup')
      assert.equal(calls[1].init?.body,'{}') // Never forces or changes saved mode.
    }
  }
})

test('startup errors remain visible without automatic retry loops', async () => {
  let requests=0
  const start=createStartupRequest((async()=>{requests++;throw Error('offline')}) as typeof fetch)
  await assert.rejects(start(),/offline/);await assert.rejects(start(),/offline/)
  assert.equal(requests,1)
})

test('retired content policies and legacy hidden preferences no longer hide images',()=>{
 for(const rating of ['UNKNOWN','ADULT','NSFW','SAFE'])for(const code of ['UNKNOWN','-','pn','nu','sc','rp'])
  assert.equal(canShowImages(rating,false,[code],false,false),true)
})
test('legacy explicit image preferences remain harmless compatibility arguments',()=>{
 assert.equal(canShowImages('ADULT',true,['pn'],true,true),true)
 assert.equal(safeUrl('javascript:alert(1)'),null)
})

test('gallery index respects first, last, and empty image boundaries', () => {
  assert.equal(imageIndex(-1, 6), 0)
  assert.equal(imageIndex(6, 6), 5)
  assert.equal(imageIndex(2, 6), 2)
  assert.equal(imageIndex(1, 0), 0)
})
test('external links reject executable and credential-bearing URLs', () => {
  assert.equal(safeUrl('javascript:alert(1)'), null)
  assert.equal(safeUrl('https://user:pass@example.com'), null)
  assert.equal(safeUrl('https://gamebanana.com/mods/732438'), 'https://gamebanana.com/mods/732438')
})

test('source release, source update and local discovery use separate timestamps', () => {
  const mod = {created_at: '2020-01-01', updated_at: '2026-10-28', first_seen_at: '2026-10-29'}
  assert.deepEqual(discoveryTime(mod, 'created'), {label: '来源发布', value: '2020-01-01'})
  assert.deepEqual(discoveryTime(mod, 'updated'), {label: '来源更新', value: '2026-10-28'})
  assert.deepEqual(discoveryTime(mod, 'first_seen'), {label: '本地发现', value: '2026-10-29'})
  assert.equal(discoveryTime({created_at: '2026-10-29'}, 'updated').value, '2026-10-29')
  assert.deepEqual(sourceUpdateDate({created_at:'2026-10-29',updated_at:'invalid'}),{value:'2026-10-29',hasIndependentUpdate:false})
  assert.deepEqual(sourceUpdateDate({}),{value:null,hasIndependentUpdate:false})
  assert.equal(dateLabel(null),'暂无来源数据')
})

test('sync time and status never turn failure or missing data into success', () => {
  assert.equal(syncTimeLabel(null), '暂无时间')
  assert.equal(syncTimeLabel('invalid'), '暂无时间')
  assert.match(syncTimeLabel('2026-10-29T00:00:00Z'), /UTC$/)
  assert.equal(syncStatusLabel('failed'), '失败')
  assert.equal(syncStatusLabel('partial'), '部分成功')
  assert.equal(syncStatusLabel('unexpected'), '未知状态')
})

test('subscription history and new events stay distinct', () => {
  const base = {subscription_followed_at:'2026-10-29', created_at:'2020-01-01',local_first_seen_event_at:'2026-10-30'}
  assert.equal(subscriptionActivity(base),'已收录历史作品')
  assert.equal(subscriptionActivity({...base,created_at:'2026-10-30'}),'关注后新发布')
  assert.equal(subscriptionActivity({...base,source_update_detected_at:'2026-10-30'}),'关注后确认来源更新')
  assert.equal(subscriptionActivity({...base,source_update_detected_at:'2020-01-01'}),'已收录历史作品')
})

test('anchor restoration uses saved viewport offset, pixels are fallback',()=>{
  assert.equal(restoreScrollTop(500,1000,200,99),1300)
  assert.equal(restoreScrollTop(null,1000,200,99),99)
  assert.equal(restoreScrollTop(0,0,200,99),0)
  assert.equal(restoreScrollTop(null,0,0,NaN),0)
})
test('popular query and per-game pages survive history serialization',()=>{
  const value={sort:'views',scope:'recent',days:90,maxPages:3,groups:{8552:{loaded:true,page:3},18366:{loaded:false,page:1}}}
  assert.deepEqual(restorePopularView(JSON.parse(JSON.stringify(value))),value)
  assert.deepEqual(restorePopularView(undefined),{sort:'likes',scope:'recent',days:30,maxPages:2,groups:{}})
  assert.equal(restorePopularView({groups:{8552:{page:-1,loaded:true}},days:8}).days,30)
})
test('missing or malformed history is ignored rather than crashing a refreshed detail',()=>{
  const snapshot={feed:'latest',game:'8552',draft:'test',search:'test',sort:'created',readFilter:'all',anchor:'gamebanana:Mod:1',page:2,scrollY:800,anchorTop:200,withImages:false,allowUnknown:true,ratings:null}
  assert.equal(validBrowseSnapshot(snapshot),true)
  assert.equal(validBrowseSnapshot({...snapshot,author:{source:'gamebanana',author_id:7}}),true)
  assert.equal(validBrowseSnapshot({...snapshot,author:{source:'gamebanana',author_id:0}}),false)
  assert.equal(validBrowseSnapshot({...snapshot,author:{source:'gamebanana',author_id:'7'}}),false)
  assert.equal(validBrowseSnapshot({...snapshot,pageSize:50,viewMode:'compact'}),true)
  assert.equal(validBrowseSnapshot({...snapshot,pageSize:51}),false)
  assert.equal(validBrowseSnapshot({...snapshot,pageSize:'25'}),false)
  assert.equal(validBrowseSnapshot({...snapshot,category:'Skins',subcategory:'Baizhi'}),true)
  assert.equal(validBrowseSnapshot({...snapshot,category:{name:'invalid'}}),false)
  assert.equal(validBrowseSnapshot({...snapshot,viewMode:'unknown'}),false)
  for(const value of [undefined,{}, {...snapshot,ratings:{}},{...snapshot,page:-1},{...snapshot,scrollY:Infinity}])assert.equal(validBrowseSnapshot(value),false)
})

test('listing defaults and persisted preferences accept only supported densities and sizes',()=>{
  assert.deepEqual(listingPreferences(null),{viewMode:'compact',pageSize:25})
  for(const pageSize of [15,25,50])for(const viewMode of ['compact','standard']){
    const value={viewMode,pageSize}
    assert.deepEqual(listingPreferences(JSON.parse(JSON.stringify(value))),value)
  }
  assert.deepEqual(listingPreferences({viewMode:'unsafe',pageSize:1000}),{viewMode:'compact',pageSize:25})
})

test('changing page size keeps the former first item on the new page and clamps bounds',()=>{
  for(const oldSize of [15,25,50])for(const newSize of [15,25,50])for(let page=0;page<4;page++){
    const next=resizedPage(page,oldSize,newSize,797)
    assert.ok(next*newSize<=page*oldSize)
    assert.ok((next+1)*newSize>page*oldSize)
  }
  assert.equal(resizedPage(3,25,50,0),0)
  assert.equal(resizedPage(30,25,50,60),1)
})

test('compact covers prefer saved thumbnails and never choose a gallery original over them',()=>{
  const mod={preview_urls:['https://images.gamebanana.com/img/ss/mods/card.jpg'],preview_images:[{image_url:'https://images.gamebanana.com/img/ss/mods/original.jpg',thumbnail_url:'https://images.gamebanana.com/img/ss/mods/530-small.jpg',switch_url:'https://images.gamebanana.com/img/ss/mods/100-small.jpg'}]}
  assert.equal(cardPreviewUrl(mod,true),mod.preview_images[0].thumbnail_url)
  assert.equal(cardPreviewUrl(mod,false),mod.preview_urls[0])
  assert.equal(cardPreviewUrl({preview_urls:[],preview_images:[{thumbnail_url:'javascript:bad',switch_url:mod.preview_images[0].switch_url}]},true),mod.preview_images[0].switch_url)
  assert.equal(cardPreviewUrl({preview_urls:mod.preview_urls},true),mod.preview_urls[0])
  assert.equal(cardPreviewUrl({preview_urls:[]},true),null)
})
